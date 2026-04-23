"""Command-line interface for section extraction and section-wise PDF diffing."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from differ import SectionDiffer
from extractor import extract_pdf_lines
from matcher import SectionMatcher
from models import DocumentSections, HeuristicConfig, to_dict
from sectionizer import sectionize_lines
from utils import configure_logging, safe_write_json


def build_parser() -> argparse.ArgumentParser:
    """Create top-level argument parser with `extract` and `diff` subcommands."""

    parser = argparse.ArgumentParser(description="PDF semantic section extractor and differ")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="Extract semantic sections from a single PDF")
    p_extract.add_argument("input_pdf", type=str)
    p_extract.add_argument("--output", required=True, type=str)
    _add_common_flags(p_extract)

    p_diff = sub.add_parser("diff", help="Diff two PDFs section-wise")
    p_diff.add_argument("pdf_a", type=str)
    p_diff.add_argument("pdf_b", type=str)
    p_diff.add_argument("--output", required=True, type=str)
    _add_common_flags(p_diff)

    return parser


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    """Attach shared heuristic and debug options to a subcommand parser."""

    parser.add_argument("--mode", choices=["primary-semantic", "numeric-primary"], default="primary-semantic")
    parser.add_argument("--header-pattern", action="append", default=[])
    parser.add_argument("--footer-pattern", action="append", default=[])
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--dump-intermediate", action="store_true")


def build_config(args: argparse.Namespace) -> HeuristicConfig:
    """Map CLI flags to a heuristic configuration object."""

    use_numeric = args.mode == "numeric-primary"
    return HeuristicConfig(
        primary_section_patterns=[],
        child_item_patterns=[],
        ignore_patterns=[],
        use_numeric_as_primary=use_numeric,
        min_header_footer_repeat_ratio=0.6,
        top_band_ratio=0.12,
        bottom_band_ratio=0.12,
        header_patterns=args.header_pattern or [],
        footer_patterns=args.footer_pattern or [],
    )


def run_extract(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute extraction pipeline and return JSON-serializable payload."""

    cfg = build_config(args)
    extraction = extract_pdf_lines(args.input_pdf, cfg)
    doc = sectionize_lines(document=args.input_pdf, lines=extraction.lines, config=cfg)

    output = to_dict(doc)
    if args.dump_intermediate:
        output["intermediate"] = {
            "extraction_debug": extraction.debug,
            "removed_header_footer_lines": [to_dict(x) for x in extraction.removed_header_footer_lines],
            "clean_line_count": len(extraction.lines),
        }
    return output


def _extract_sections(pdf_path: str, cfg: HeuristicConfig, dump_intermediate: bool = False) -> tuple[DocumentSections, Dict[str, Any]]:
    """Extract cleaned sections for one PDF plus optional intermediate diagnostics."""

    extraction = extract_pdf_lines(pdf_path, cfg)
    doc = sectionize_lines(document=pdf_path, lines=extraction.lines, config=cfg)
    intermediate: Dict[str, Any] = {}
    if dump_intermediate:
        intermediate = {
            "extraction_debug": extraction.debug,
            "removed_header_footer_count": len(extraction.removed_header_footer_lines),
            "clean_line_count": len(extraction.lines),
        }
    return doc, intermediate


def run_diff(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute end-to-end diff pipeline and return JSON-serializable report."""

    cfg = build_config(args)
    doc_a, ia = _extract_sections(args.pdf_a, cfg, args.dump_intermediate)
    doc_b, ib = _extract_sections(args.pdf_b, cfg, args.dump_intermediate)

    matches = SectionMatcher(cfg).match(doc_a.sections, doc_b.sections)
    report = SectionDiffer().build_report(doc_a, doc_b, matches)

    payload = to_dict(report)
    if args.dump_intermediate:
        payload["intermediate"] = {
            "pdf_a": ia,
            "pdf_b": ib,
            "matches": [to_dict(m) for m in matches],
        }
    return payload


def main() -> None:
    """CLI entrypoint."""

    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.debug)

    if args.command == "extract":
        data = run_extract(args)
        safe_write_json(args.output, data)
    elif args.command == "diff":
        data = run_diff(args)
        safe_write_json(args.output, data)
    else:  # pragma: no cover
        raise ValueError(f"Unknown command {args.command}")


if __name__ == "__main__":
    main()
