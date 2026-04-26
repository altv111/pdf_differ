"""Run A/B comparison between pymupdf and unstructured extraction backends."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from differ import SectionDiffer
from extractor import extract_pdf_lines
from matcher import SectionMatcher
from models import HeuristicConfig, to_dict
from sectionizer import sectionize_lines


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for extractor comparison runs."""

    parser = argparse.ArgumentParser(description="Compare pymupdf vs unstructured extractor backends")
    parser.add_argument("pdf_a", type=str)
    parser.add_argument("pdf_b", type=str)
    parser.add_argument("--mode", choices=["primary-semantic", "numeric-primary"], default="primary-semantic")
    parser.add_argument("--header-pattern", action="append", default=[])
    parser.add_argument("--footer-pattern", action="append", default=[])
    parser.add_argument("--output", type=str, default=None, help="Optional JSON output path")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> HeuristicConfig:
    """Create heuristic config from CLI arguments."""

    return HeuristicConfig(
        primary_section_patterns=[],
        child_item_patterns=[],
        ignore_patterns=[],
        use_numeric_as_primary=args.mode == "numeric-primary",
        min_header_footer_repeat_ratio=0.6,
        top_band_ratio=0.12,
        bottom_band_ratio=0.12,
        header_patterns=args.header_pattern or [],
        footer_patterns=args.footer_pattern or [],
    )


def run_backend(pdf_a: str, pdf_b: str, backend: str, cfg: HeuristicConfig) -> Dict[str, Any]:
    """Execute full diff pipeline for a single extraction backend."""

    t0 = time.perf_counter()
    result: Dict[str, Any] = {
        "backend": backend,
        "ok": False,
        "error": None,
        "timing_seconds": {},
    }

    try:
        t = time.perf_counter()
        ext_a = extract_pdf_lines(pdf_a, cfg, extractor_backend=backend)
        ext_b = extract_pdf_lines(pdf_b, cfg, extractor_backend=backend)
        result["timing_seconds"]["extract"] = round(time.perf_counter() - t, 3)

        t = time.perf_counter()
        doc_a = sectionize_lines(document=pdf_a, lines=ext_a.lines, config=cfg)
        doc_b = sectionize_lines(document=pdf_b, lines=ext_b.lines, config=cfg)
        result["timing_seconds"]["sectionize"] = round(time.perf_counter() - t, 3)

        t = time.perf_counter()
        matches = SectionMatcher(cfg).match(doc_a.sections, doc_b.sections)
        result["timing_seconds"]["match"] = round(time.perf_counter() - t, 3)

        t = time.perf_counter()
        report = SectionDiffer().build_report(doc_a, doc_b, matches)
        result["timing_seconds"]["diff"] = round(time.perf_counter() - t, 3)

        result["timing_seconds"]["total"] = round(time.perf_counter() - t0, 3)

        summary = to_dict(report.summary)
        result["summary"] = summary
        result["extraction"] = {
            "pdf_a": ext_a.debug,
            "pdf_b": ext_b.debug,
        }
        result["section_counts"] = {
            "pdf_a_total": len(doc_a.sections),
            "pdf_b_total": len(doc_b.sections),
            "pdf_a_primary": summary["total_sections_a"],
            "pdf_b_primary": summary["total_sections_b"],
        }
        denom = max(1, summary["matched"])
        result["quality_indicators"] = {
            "modified_ratio_in_matches": round(summary["modified"] / denom, 4),
            "unchanged_ratio_in_matches": round(summary["unchanged"] / denom, 4),
        }

        result["ok"] = True
        return result

    except Exception as exc:
        result["error"] = str(exc)
        result["timing_seconds"]["total"] = round(time.perf_counter() - t0, 3)
        return result


def print_comparison(report: Dict[str, Any]) -> None:
    """Print human-readable comparison to stdout."""

    print("Extractor comparison")
    print(f"PDF A: {report['pdf_a']}")
    print(f"PDF B: {report['pdf_b']}")
    print("")

    for backend in ("pymupdf", "unstructured"):
        r = report["results"].get(backend)
        if not r:
            continue
        print(f"[{backend}] ok={r['ok']}")
        if not r["ok"]:
            print(f"  error: {r.get('error')}")
            print(f"  total_s: {r['timing_seconds'].get('total')}")
            print("")
            continue

        s = r["summary"]
        print(
            "  sections A/B: "
            f"{s['total_sections_a']}/{s['total_sections_b']} | "
            f"matched={s['matched']} added={s['added']} removed={s['removed']} "
            f"modified={s['modified']} unchanged={s['unchanged']}"
        )
        print(
            "  timing_s: "
            f"extract={r['timing_seconds']['extract']} "
            f"sectionize={r['timing_seconds']['sectionize']} "
            f"match={r['timing_seconds']['match']} "
            f"diff={r['timing_seconds']['diff']} "
            f"total={r['timing_seconds']['total']}"
        )
        q = r["quality_indicators"]
        print(
            "  quality: "
            f"modified_ratio_in_matches={q['modified_ratio_in_matches']} "
            f"unchanged_ratio_in_matches={q['unchanged_ratio_in_matches']}"
        )
        print("")


def main() -> None:
    """CLI entrypoint."""

    args = parse_args()
    cfg = build_config(args)

    comparison = {
        "pdf_a": args.pdf_a,
        "pdf_b": args.pdf_b,
        "mode": args.mode,
        "results": {
            "pymupdf": run_backend(args.pdf_a, args.pdf_b, "pymupdf", cfg),
            "unstructured": run_backend(args.pdf_a, args.pdf_b, "unstructured", cfg),
        },
    }

    print_comparison(comparison)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote comparison JSON: {out}")


if __name__ == "__main__":
    main()
