from export_table import build_rows, extract_section_number


def test_extract_section_number() -> None:
    assert extract_section_number("Principle 12: Something", None) == "12"
    assert extract_section_number("II. Intro", None) == "II"
    assert extract_section_number("3. Scope", None) == "3"


def test_build_rows_minimal() -> None:
    report = {
        "diffs": [
            {
                "page_no_in_a": 4,
                "section_id_a": "s001",
                "title_a": "Principle 5: Sample",
                "section_lines_a": ["Principle 5: Sample", "Body A"],
                "page_no_in_b": 7,
                "section_id_b": "s010",
                "title_b": "Principle 5: Sample",
                "section_lines_b": ["Principle 5: Sample", "Body B"],
                "match_score": 0.987,
            }
        ]
    }

    rows = build_rows(report)
    assert len(rows) == 1
    r = rows[0]
    assert r["page_number_file_a"] == 4
    assert r["section_number_file_a"] == "5"
    assert "Body A" in r["text_file_a"]
    assert r["page_number_file_b"] == 7
    assert r["section_number_file_b"] == "5"
    assert "Body B" in r["text_file_b"]
    assert r["diff_score"] == 0.987
