"""Standalone exporter that converts diff JSON into CSV/Excel tabular format."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List


def extract_section_number(title: str | None, section_id: str | None) -> str:
    """Best-effort extraction of a section number/label from a heading title."""

    if title:
        t = title.strip()
        patterns = [
            r"^(?P<num>[IVXLCDM]+)\.\s+",  # I. II. III.
            r"^(?P<num>\d+)\.\s+",  # 1. 2. 3.
            r"^(?P<num>[A-Za-z])\.\s+",  # A. B. a.
            r"^(?:principle|article|section|chapter|standard|rule)\s+(?P<num>\d+[A-Za-z]?)\b",
        ]
        for pat in patterns:
            m = re.match(pat, t, flags=re.IGNORECASE)
            if m:
                return m.group("num")
    return section_id or ""


def section_text(diff_item: Dict[str, Any], side: str) -> str:
    """Return full section text (title + body) for one side."""

    title_key = "title_a" if side == "a" else "title_b"
    lines_key = "section_lines_a" if side == "a" else "section_lines_b"

    lines = diff_item.get(lines_key)
    if isinstance(lines, list) and lines:
        return "\n".join(str(x) for x in lines)

    title = diff_item.get(title_key)
    return str(title) if title else ""


def build_rows(diff_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Transform diff report rows into the tabular export schema."""

    rows: List[Dict[str, Any]] = []
    for d in diff_report.get("diffs", []):
        title_a = d.get("title_a")
        title_b = d.get("title_b")
        section_id_a = d.get("section_id_a")
        section_id_b = d.get("section_id_b")

        rows.append(
            {
                "page_number_file_a": d.get("page_no_in_a") or "",
                "section_number_file_a": extract_section_number(title_a, section_id_a),
                "text_file_a": section_text(d, "a"),
                "page_number_file_b": d.get("page_no_in_b") or "",
                "section_number_file_b": extract_section_number(title_b, section_id_b),
                "text_file_b": section_text(d, "b"),
                "diff_score": d.get("match_score", ""),
            }
        )
    return rows


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Write tabular rows to CSV."""

    headers = [
        "page_number_file_a",
        "section_number_file_a",
        "text_file_a",
        "page_number_file_b",
        "section_number_file_b",
        "text_file_b",
        "diff_score",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_excel(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Write tabular rows to XLSX (requires openpyxl)."""

    try:
        from openpyxl import Workbook  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Excel export requires openpyxl. Install with: pip install openpyxl"
        ) from exc

    headers = [
        "page_number_file_a",
        "section_number_file_a",
        "text_file_a",
        "page_number_file_b",
        "section_number_file_b",
        "text_file_b",
        "diff_score",
    ]

    wb = Workbook()
    ws = wb.active
    ws.title = "diff_sections"
    ws.append(headers)

    for row in rows:
        ws.append([row[h] for h in headers])

    # Simple readable widths
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 80
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 22
    ws.column_dimensions["F"].width = 80
    ws.column_dimensions["G"].width = 14

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def parse_args() -> argparse.Namespace:
    """Parse exporter CLI arguments."""

    parser = argparse.ArgumentParser(description="Export diff JSON to table format (CSV/Excel)")
    parser.add_argument("input_json", type=str, help="Diff JSON path")
    parser.add_argument("--csv", dest="csv_out", type=str, default=None, help="CSV output path")
    parser.add_argument("--excel", dest="excel_out", type=str, default=None, help="Excel output path (.xlsx)")
    return parser.parse_args()


def main() -> None:
    """Exporter entrypoint."""

    args = parse_args()
    input_path = Path(args.input_json)

    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON not found: {input_path}")

    if not args.csv_out and not args.excel_out:
        raise ValueError("Provide at least one output: --csv and/or --excel")

    report = json.loads(input_path.read_text(encoding="utf-8"))
    rows = build_rows(report)

    if args.csv_out:
        write_csv(Path(args.csv_out), rows)
    if args.excel_out:
        write_excel(Path(args.excel_out), rows)


if __name__ == "__main__":
    main()
