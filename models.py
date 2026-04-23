"""Core datamodels shared across extraction, sectionization, matching, and diffing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class HeuristicConfig:
    """Configuration knobs for extraction and section heuristics."""

    primary_section_patterns: List[str] = field(default_factory=list)
    child_item_patterns: List[str] = field(default_factory=list)
    ignore_patterns: List[str] = field(default_factory=list)
    use_numeric_as_primary: bool = False
    min_header_footer_repeat_ratio: float = 0.6
    top_band_ratio: float = 0.12
    bottom_band_ratio: float = 0.12
    header_patterns: List[str] = field(default_factory=list)
    footer_patterns: List[str] = field(default_factory=list)


@dataclass
class ExtractedLine:
    """Single reconstructed line from PDF layout extraction."""

    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    is_header_footer: bool = False
    source_block: Optional[int] = None


@dataclass
class ChildItem:
    """Nested list-like child item captured inside a parent section."""

    item_number: Optional[str]
    text: str


@dataclass
class Section:
    """Semantic section unit used for matching and comparison."""

    section_id: str
    parent_id: Optional[str]
    level: int
    anchor_type: str
    title: str
    title_normalized: str
    start_page: int
    end_page: int
    body: str
    body_lines: List[str]
    children: List[ChildItem] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentSections:
    """All extracted sections for one source document."""

    document: str
    sections: List[Section]


@dataclass
class SectionMatch:
    """Alignment result between one section in A and one section in B."""

    section_id_a: Optional[str]
    section_id_b: Optional[str]
    score: float
    confidence: str
    reason: str


@dataclass
class StructuredDiffChunk:
    """Normalized diff chunk with opcode tag and line slices for both sides."""

    tag: str
    lines_a: List[str]
    lines_b: List[str]


@dataclass
class TitleDiff:
    """Dedicated title-level diff payload for a matched section pair."""

    status: str
    structured_diff: List[StructuredDiffChunk]
    unified_diff: str


@dataclass
class SectionDiffResult:
    """Final section-wise diff result row emitted in a diff report."""

    status: str
    section_id_a: Optional[str]
    section_id_b: Optional[str]
    parent_section_id_a: Optional[str]
    parent_section_id_b: Optional[str]
    title_a: Optional[str]
    title_b: Optional[str]
    page_no_in_a: Optional[int]
    page_no_in_b: Optional[int]
    match_score: float
    match_confidence: Optional[str]
    low_confidence: bool
    anchor_type: Optional[str]
    title_diff: Optional[TitleDiff]
    structured_diff: List[StructuredDiffChunk]
    unified_diff: str
    semantic_status: str
    semantic_text_a: str
    semantic_text_b: str
    semantic_structured_diff: List[StructuredDiffChunk] = field(default_factory=list)
    semantic_unified_diff: str = ""
    change_classification: Optional[str] = None
    section_lines_a: List[str] = field(default_factory=list)
    section_lines_b: List[str] = field(default_factory=list)
    section_structured_diff: List[StructuredDiffChunk] = field(default_factory=list)


@dataclass
class DiffSummary:
    """Aggregate counts for the diff report."""

    total_sections_a: int
    total_sections_b: int
    matched: int
    added: int
    removed: int
    modified: int
    unchanged: int


@dataclass
class DiffReport:
    """Top-level diff output object serialized to JSON."""

    pdf_a: str
    pdf_b: str
    summary: DiffSummary
    diffs: List[SectionDiffResult]



def to_dict(dataclass_obj: Any) -> Dict[str, Any]:
    """Convert nested dataclasses into plain dictionaries."""

    return asdict(dataclass_obj)
