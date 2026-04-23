from models import ExtractedLine, HeuristicConfig
from sectionizer import sectionize_lines


def _line(text: str, page: int = 1) -> ExtractedLine:
    return ExtractedLine(text=text, page=page, x0=0, y0=0, x1=10, y1=10)


def test_primary_semantic_mode_groups_numeric_children() -> None:
    cfg = HeuristicConfig(use_numeric_as_primary=False)
    lines = [
        _line("Principle 5: Banks should establish overall credit limits"),
        _line("Intro body text"),
        _line("28. First child line"),
        _line("29. Second child line"),
        _line("Principle 6: Governance"),
        _line("More text"),
    ]

    doc = sectionize_lines("doc.pdf", lines, cfg)
    assert len([s for s in doc.sections if s.level == 1]) == 2
    first = doc.sections[0]
    assert first.title.startswith("Principle 5")
    assert len(first.children) == 2
    assert first.children[0].item_number == "28"


def test_numeric_primary_mode_promotes_numeric_headings() -> None:
    cfg = HeuristicConfig(use_numeric_as_primary=True)
    lines = [
        _line("1. Overview"),
        _line("body"),
        _line("2. Scope"),
    ]
    doc = sectionize_lines("doc.pdf", lines, cfg)
    titles = [s.title for s in doc.sections if s.level == 1]
    assert "1. Overview" in titles
    assert "2. Scope" in titles


def test_toc_artifact_is_cleaned_from_heading_title() -> None:
    cfg = HeuristicConfig(use_numeric_as_primary=False)
    lines = [
        _line("II. Establishing an appropriate credit risk environment ........................................................................ 5"),
        _line("body text"),
    ]
    doc = sectionize_lines("doc.pdf", lines, cfg)
    # TOC-style line should be treated as reference_line and not become a section.
    assert len(doc.sections) == 1
    assert doc.sections[0].title == "Preamble"


def test_wrapped_heading_continuation_is_merged_into_title() -> None:
    cfg = HeuristicConfig(use_numeric_as_primary=False)
    lines = [
        _line("Principle 7: All extensions of credit must be made on an arm's-length basis. In"),
        _line("particular, credits to related companies and individuals must be authorised on an"),
        _line("exception basis and monitored carefully."),
    ]
    doc = sectionize_lines("doc.pdf", lines, cfg)
    s = doc.sections[0]
    assert s.title.endswith("particular, credits to related companies and individuals must be authorised on an")
    assert s.body_lines == ["exception basis and monitored carefully."]
