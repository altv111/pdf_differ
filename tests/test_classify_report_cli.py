import json
import subprocess
import sys
from pathlib import Path


def test_classify_report_cli_end_to_end(tmp_path: Path) -> None:
    inp = tmp_path / "in.json"
    out = tmp_path / "out.json"

    inp.write_text(
        json.dumps(
            {
                "pdf_a": "a.pdf",
                "pdf_b": "b.pdf",
                "diffs": [
                    {
                        "section_id_a": "a1",
                        "section_id_b": "b1",
                        "title_a": "Principle 1",
                        "title_b": "Principle 1",
                        "semantic_text_a": "Banks should report exposures.",
                        "semantic_text_b": "Banks should report exposures.",
                        "match_score": 0.99,
                        "semantic_status": "unchanged",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "classify_report.py"),
            str(inp),
            "--output",
            str(out),
        ],
        check=True,
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "summary" in payload
    assert payload["summary"]["total"] == 1
    assert "classifications" in payload
    assert payload["classifications"][0]["final_classification"] in {"editorial", "slight", "significant"}
