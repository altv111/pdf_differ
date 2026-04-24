"""CLI wrapper for running hybrid classification over a diff report JSON."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from classifier import classify_diff_report


def parse_args() -> argparse.Namespace:
    """Parse classification CLI arguments."""

    parser = argparse.ArgumentParser(description="Classify a diff report into editorial/slight/significant")
    parser.add_argument("input_json", type=str, help="Diff report JSON path")
    parser.add_argument("--output", required=True, type=str, help="Output classified JSON path")
    parser.add_argument("--no-progress", action="store_true", help="Disable progress logs")
    parser.add_argument("--llm-events", action="store_true", help="Print per-section LLM call events")
    return parser.parse_args()


def read_json(path: Path) -> Dict[str, Any]:
    """Read JSON file from disk."""

    if not path.exists():
        raise FileNotFoundError(f"Input JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON file to disk with stable formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    """CLI entrypoint."""

    args = parse_args()
    report = read_json(Path(args.input_json))
    total = len(report.get("diffs", []))

    started_at = time.time()
    current_section_start = [started_at]

    def progress_callback(idx: int, count: int, payload: Dict[str, Any]) -> None:
        if args.no_progress:
            return
        now = time.time()
        if idx > 1:
            prev_elapsed = now - current_section_start[0]
            print(f"[done] {idx - 1}/{count} in {prev_elapsed:.1f}s", flush=True)
        current_section_start[0] = now

        sid = payload.get("section_id") or "(no-section-id)"
        title = (payload.get("section_title") or "").strip()
        title_preview = title[:80] + ("..." if len(title) > 80 else "")
        print(f"[{idx}/{count}] classifying {sid} | {title_preview}", flush=True)

    def event_hook(event: str, data: Dict[str, Any]) -> None:
        if not args.llm_events:
            return
        if event == "pre_llm":
            print("  -> calling LLM...", flush=True)
        elif event == "post_llm":
            print(
                f"  <- LLM done (label={data.get('llm_label')}, stub={data.get('stub')})",
                flush=True,
            )

    try:
        if not args.no_progress:
            print(f"Classifying {total} sections...", flush=True)
        classified = classify_diff_report(
            report,
            progress_callback=progress_callback,
            event_hook=event_hook,
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user. No output file was written.", flush=True)
        return

    if not args.no_progress and total > 0:
        last_elapsed = time.time() - current_section_start[0]
        print(f"[done] {total}/{total} in {last_elapsed:.1f}s", flush=True)

    write_json(Path(args.output), classified)
    if not args.no_progress:
        print(f"Wrote classified report: {args.output}", flush=True)
        print(f"Total runtime: {time.time() - started_at:.1f}s", flush=True)


if __name__ == "__main__":
    main()
