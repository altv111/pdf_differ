"""Section-wise diff generation and report assembly."""

from __future__ import annotations

import difflib
import re
from typing import Callable, Dict, List, Optional

from matcher import map_sections_by_id
from models import (
    DiffReport,
    DiffSummary,
    DocumentSections,
    Section,
    SectionDiffResult,
    SectionMatch,
    StructuredDiffChunk,
    TitleDiff,
)
from utils import normalize_body, normalize_title

ChangeClassifierHook = Callable[[str, str], Optional[str]]


class SectionDiffer:
    """Build structured section-level diffs from matched sections."""

    def __init__(self, change_classifier: Optional[ChangeClassifierHook] = None):
        """Initialize differ with an optional post-diff change classifier hook."""

        self.change_classifier = change_classifier

    def build_report(
        self,
        doc_a: DocumentSections,
        doc_b: DocumentSections,
        matches: List[SectionMatch],
    ) -> DiffReport:
        """Assemble full diff report including summary counts and per-section results."""

        sections_a = map_sections_by_id(doc_a.sections)
        sections_b = map_sections_by_id(doc_b.sections)

        diffs: List[SectionDiffResult] = []
        matched_count = 0
        added = 0
        removed = 0
        modified = 0
        unchanged = 0

        for m in matches:
            sa = sections_a.get(m.section_id_a) if m.section_id_a else None
            sb = sections_b.get(m.section_id_b) if m.section_id_b else None

            if sa and sb:
                matched_count += 1
                result = self._diff_matched(sa, sb, m.score, m.confidence)
                if result.status == "unchanged":
                    unchanged += 1
                else:
                    modified += 1
                diffs.append(result)
            elif sa and not sb:
                removed += 1
                diffs.append(self._wrap_unmatched(sa, None, "removed"))
            elif sb and not sa:
                added += 1
                diffs.append(self._wrap_unmatched(None, sb, "added"))

        summary = DiffSummary(
            total_sections_a=len([s for s in doc_a.sections if s.level <= 1 and s.anchor_type != "preamble"]),
            total_sections_b=len([s for s in doc_b.sections if s.level <= 1 and s.anchor_type != "preamble"]),
            matched=matched_count,
            added=added,
            removed=removed,
            modified=modified,
            unchanged=unchanged,
        )

        return DiffReport(pdf_a=doc_a.document, pdf_b=doc_b.document, summary=summary, diffs=diffs)

    def _diff_matched(self, a: Section, b: Section, score: float, confidence: str) -> SectionDiffResult:
        """Generate a detailed diff for one matched section pair."""

        title_same = normalize_title(a.title) == normalize_title(b.title)
        body_same = normalize_body(a.body) == normalize_body(b.body)
        renumber_only = body_same and self._is_renumbering_only_title_change(a.title, b.title)

        if title_same and body_same:
            status = "unchanged"
        elif renumber_only:
            status = "renumbering_only"
        else:
            status = "modified"

        chunks = self._structured_diff(a.body_lines, b.body_lines)
        section_lines_a = [a.title, *a.body_lines]
        section_lines_b = [b.title, *b.body_lines]
        section_chunks = self._structured_diff(section_lines_a, section_lines_b, include_equal=True)
        unified = "\n".join(
            difflib.unified_diff(
                a.body.splitlines(),
                b.body.splitlines(),
                fromfile=f"{a.section_id}:old",
                tofile=f"{b.section_id}:new",
                lineterm="",
            )
        )
        title_chunks = self._structured_diff([a.title], [b.title])
        title_unified = "\n".join(
            difflib.unified_diff(
                [a.title],
                [b.title],
                fromfile=f"{a.section_id}:title_old",
                tofile=f"{b.section_id}:title_new",
                lineterm="",
            )
        )
        title_diff = TitleDiff(
            status="unchanged" if title_same else "modified",
            structured_diff=title_chunks,
            unified_diff=title_unified,
        )

        classification = None
        if self.change_classifier and status == "modified":
            classification = self.change_classifier(a.body, b.body)

        return SectionDiffResult(
            status=status,
            section_id_a=a.section_id,
            section_id_b=b.section_id,
            parent_section_id_a=a.parent_id,
            parent_section_id_b=b.parent_id,
            title_a=a.title,
            title_b=b.title,
            page_no_in_a=a.start_page,
            page_no_in_b=b.start_page,
            match_score=round(score, 4),
            match_confidence=confidence,
            low_confidence=confidence == "low-confidence matched",
            anchor_type=a.anchor_type,
            title_diff=title_diff,
            structured_diff=chunks,
            unified_diff=unified,
            change_classification=classification,
            section_lines_a=section_lines_a,
            section_lines_b=section_lines_b,
            section_structured_diff=section_chunks,
        )

    def _wrap_unmatched(
        self,
        a: Optional[Section],
        b: Optional[Section],
        status: str,
    ) -> SectionDiffResult:
        """Create a diff result for added/removed unmatched sections."""

        section_lines_a = [a.title, *a.body_lines] if a else []
        section_lines_b = [b.title, *b.body_lines] if b else []
        if a and not b:
            section_structured = [StructuredDiffChunk(tag="delete", lines_a=section_lines_a, lines_b=[])]
        elif b and not a:
            section_structured = [StructuredDiffChunk(tag="insert", lines_a=[], lines_b=section_lines_b)]
        else:
            section_structured = []

        return SectionDiffResult(
            status=status,
            section_id_a=a.section_id if a else None,
            section_id_b=b.section_id if b else None,
            parent_section_id_a=a.parent_id if a else None,
            parent_section_id_b=b.parent_id if b else None,
            title_a=a.title if a else None,
            title_b=b.title if b else None,
            page_no_in_a=a.start_page if a else None,
            page_no_in_b=b.start_page if b else None,
            match_score=0.0,
            match_confidence="unmatched",
            low_confidence=False,
            anchor_type=(a.anchor_type if a else b.anchor_type if b else None),
            title_diff=None,
            structured_diff=[],
            unified_diff="",
            change_classification=None,
            section_lines_a=section_lines_a,
            section_lines_b=section_lines_b,
            section_structured_diff=section_structured,
        )

    @staticmethod
    def _structured_diff(
        lines_a: List[str],
        lines_b: List[str],
        include_equal: bool = False,
    ) -> List[StructuredDiffChunk]:
        """Convert difflib opcodes into structured diff chunks."""

        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
        chunks: List[StructuredDiffChunk] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal" and not include_equal:
                continue
            chunks.append(
                StructuredDiffChunk(
                    tag=tag,
                    lines_a=lines_a[i1:i2],
                    lines_b=lines_b[j1:j2],
                )
            )
        return chunks

    @staticmethod
    def _title_core(text: str) -> str:
        """Normalize title while stripping numbering prefixes for semantic comparison."""

        value = normalize_title(text)
        value = re.sub(r"^(?:[ivxlcdm]+|\d+|[a-z])\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(
            r"^(?:principle|article|section|chapter|standard|rule)\s+\d+[a-z]?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return value.strip()

    def _is_renumbering_only_title_change(self, title_a: str, title_b: str) -> bool:
        """Return True when title change is only numbering/label renaming."""

        if normalize_title(title_a) == normalize_title(title_b):
            return False
        return self._title_core(title_a) == self._title_core(title_b)
