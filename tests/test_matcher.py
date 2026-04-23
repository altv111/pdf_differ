from matcher import SectionMatcher
from models import HeuristicConfig, Section


def _section(section_id: str, title: str, body: str, anchor_type: str = "named_numbered_heading") -> Section:
    return Section(
        section_id=section_id,
        parent_id=None,
        level=1,
        anchor_type=anchor_type,
        title=title,
        title_normalized=title.lower(),
        start_page=1,
        end_page=1,
        body=body,
        body_lines=body.splitlines() if body else [],
        children=[],
        metadata={},
    )


def test_matcher_aligns_similar_titles() -> None:
    a = [_section("a1", "Principle 5: Credit risk", "Banks should manage risk.")]
    b = [_section("b1", "Principle 5 - Credit Risk", "Banks should manage credit risk.")]
    matches = SectionMatcher(HeuristicConfig()).match(a, b)
    matched = [m for m in matches if m.section_id_a and m.section_id_b]
    assert len(matched) == 1
    assert matched[0].score >= 0.55


def test_matcher_handles_heading_number_style_changes() -> None:
    a = [_section("a1", "C. Maintaining an appropriate credit administration", "same text")]
    b = [_section("b1", "IV. Maintaining an appropriate credit administration", "same text")]
    matches = SectionMatcher(HeuristicConfig()).match(a, b)
    matched = [m for m in matches if m.section_id_a and m.section_id_b]
    assert len(matched) == 1
    assert matched[0].score >= 0.7
