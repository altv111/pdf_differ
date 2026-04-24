"""Import classified-report labels into viewer_state.db for stable UI persistence.

Safe behavior:
- If classified file is missing, exits successfully with zero imported.
- If no matching section ids are found, exits successfully with zero imported.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from viewer_backend import _diff_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import classified JSON labels into viewer_state.db")
    parser.add_argument("diff_json", type=str, help="Path to diff report JSON")
    parser.add_argument("classified_json", type=str, help="Path to classified report JSON")
    parser.add_argument("--db", default="viewer_state.db", type=str, help="SQLite DB path")
    parser.add_argument("--source", default="classified_import", type=str, help="classification source tag")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    diff_path = Path(args.diff_json)
    cls_path = Path(args.classified_json)
    db_path = Path(args.db)

    if not diff_path.exists():
        raise FileNotFoundError(f"Diff JSON not found: {diff_path}")
    if not cls_path.exists():
        print("classified json not found; imported=0")
        return

    diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
    cls_payload = json.loads(cls_path.read_text(encoding="utf-8"))

    class_by_section = {
        row.get("section_id"): row.get("final_classification")
        for row in cls_payload.get("classifications", [])
        if row.get("section_id") and row.get("final_classification")
    }

    if not class_by_section:
        print("no classifications found; imported=0")
        return

    diffs = diff_payload.get("diffs", [])
    imported = 0

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS diff_classification (
                diff_id TEXT PRIMARY KEY,
                classification TEXT,
                source TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        for idx, item in enumerate(diffs):
            sid_b = item.get("section_id_b")
            sid_a = item.get("section_id_a")
            label = class_by_section.get(sid_b) or class_by_section.get(sid_a)
            if not label:
                continue
            diff_id = _diff_id(item, idx)
            conn.execute(
                """
                INSERT INTO diff_classification(diff_id, classification, source, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(diff_id) DO UPDATE SET
                    classification=excluded.classification,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (diff_id, label, args.source),
            )
            imported += 1

        conn.commit()
    finally:
        conn.close()

    print(f"imported={imported}")


if __name__ == "__main__":
    main()
