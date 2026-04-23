from differ import SectionDiffer
from models import DocumentSections, Section, SectionMatch


def _section(section_id: str, title: str, body_lines: list[str]) -> Section:
    return Section(
        section_id=section_id,
        parent_id=None,
        level=1,
        anchor_type="named_numbered_heading",
        title=title,
        title_normalized=title.lower(),
        start_page=1,
        end_page=1,
        body="\n".join(body_lines),
        body_lines=body_lines,
        children=[],
        metadata={},
    )


def test_diff_reports_modified_section() -> None:
    a_sec = _section("a1", "Principle 1: Scope", ["old text", "line2"])
    b_sec = _section("b1", "Principle 1: Scope", ["new text", "line2"])

    doc_a = DocumentSections(document="a.pdf", sections=[a_sec])
    doc_b = DocumentSections(document="b.pdf", sections=[b_sec])
    matches = [SectionMatch(section_id_a="a1", section_id_b="b1", score=0.9, confidence="matched", reason="")]

    report = SectionDiffer().build_report(doc_a, doc_b, matches)
    assert report.summary.modified == 1
    assert report.diffs[0].status == "modified"
    assert report.diffs[0].title_diff is not None
    assert report.diffs[0].title_diff.status == "unchanged"
    assert report.diffs[0].match_confidence == "matched"
    assert report.diffs[0].low_confidence is False
    assert report.diffs[0].section_lines_a[0] == "Principle 1: Scope"
    assert report.diffs[0].section_lines_b[0] == "Principle 1: Scope"
    assert report.diffs[0].section_structured_diff
    assert report.diffs[0].structured_diff


def test_toc_style_title_suffix_is_ignored_as_noise() -> None:
    a_sec = _section("a1", "I. Intro ................................................................ 4", ["same body"])
    b_sec = _section("b1", "I. Intro", ["same body"])

    doc_a = DocumentSections(document="a.pdf", sections=[a_sec])
    doc_b = DocumentSections(document="b.pdf", sections=[b_sec])
    matches = [SectionMatch(section_id_a="a1", section_id_b="b1", score=0.8, confidence="matched", reason="")]

    report = SectionDiffer().build_report(doc_a, doc_b, matches)
    diff = report.diffs[0]
    assert diff.status == "unchanged"
    assert diff.structured_diff == []
    assert diff.unified_diff == ""
    assert diff.title_diff is not None
    assert diff.title_diff.status == "unchanged"
    assert diff.section_lines_a[0].startswith("I. Intro")
    assert diff.section_lines_b[0] == "I. Intro"


def test_diff_reports_renumbering_only() -> None:
    a_sec = _section("a1", "C. Maintaining an appropriate credit administration", ["same body"])
    b_sec = _section("b1", "IV. Maintaining an appropriate credit administration", ["same body"])

    doc_a = DocumentSections(document="a.pdf", sections=[a_sec])
    doc_b = DocumentSections(document="b.pdf", sections=[b_sec])
    matches = [SectionMatch(section_id_a="a1", section_id_b="b1", score=0.81, confidence="matched", reason="")]

    report = SectionDiffer().build_report(doc_a, doc_b, matches)
    diff = report.diffs[0]
    assert diff.status == "renumbering_only"


def test_diff_propagates_low_confidence_match_flag() -> None:
    a_sec = _section("a1", "Principle 9: X", ["body A"])
    b_sec = _section("b1", "Principle 9: Y", ["body B"])
    doc_a = DocumentSections(document="a.pdf", sections=[a_sec])
    doc_b = DocumentSections(document="b.pdf", sections=[b_sec])
    matches = [SectionMatch(section_id_a="a1", section_id_b="b1", score=0.62, confidence="low-confidence matched", reason="")]

    report = SectionDiffer().build_report(doc_a, doc_b, matches)
    diff = report.diffs[0]
    assert diff.match_confidence == "low-confidence matched"
    assert diff.low_confidence is True
