"""Line classification and state-machine-based semantic section construction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from models import ChildItem, DocumentSections, ExtractedLine, HeuristicConfig, Section
from utils import collapse_ws, normalize_title, slugify, strip_toc_artifacts

LOGGER = logging.getLogger("pdf_section_diff.sectionizer")


ROMAN_RE = re.compile(r"^(?P<num>[IVXLCDM]+)\.\s+(?P<title>.+)$")
NUMERIC_RE = re.compile(r"^(?P<num>\d+)\.\s+(?P<title>.+)$")
LETTER_RE = re.compile(r"^(?P<num>[A-Za-z])\.\s+(?P<title>.+)$")
NAMED_NUMBERED_RE = re.compile(
    r"^(?P<kind>principle|article|section|chapter|standard|rule)\s+(?P<num>\d+[A-Za-z]?)\s*(?:[:.-])?\s*(?P<title>.+)?$",
    flags=re.IGNORECASE,
)
FOOTNOTE_LABEL_RE = re.compile(r"^(?:\[\d+\]|\d+\)|\d+)\s*$")
REFERENCE_LINE_RE = re.compile(r"^(?:references?|source|bibliography|annex|appendix)\b", flags=re.IGNORECASE)
TOC_ENTRY_RE = re.compile(r"^.+?[.\u2026·]{3,}\s*\d{1,4}\s*$")


@dataclass
class ClassifiedLine:
    """Line plus classifier label used by the sectionization state machine."""

    line: ExtractedLine
    label: str
    anchor_type: Optional[str] = None


class LineClassifier:
    """Rule-based heading/body classifier for cleaned PDF lines."""

    def classify(self, line: ExtractedLine) -> ClassifiedLine:
        """Assign a structural label to a line using heading/reference heuristics."""

        text = collapse_ws(line.text)
        if line.is_header_footer:
            return ClassifiedLine(line=line, label="footer_or_header")
        if TOC_ENTRY_RE.match(text):
            return ClassifiedLine(line=line, label="reference_line")
        if FOOTNOTE_LABEL_RE.match(text):
            return ClassifiedLine(line=line, label="footnote_label")
        if REFERENCE_LINE_RE.match(text):
            return ClassifiedLine(line=line, label="reference_line")
        if ROMAN_RE.match(text):
            return ClassifiedLine(line=line, label="major_heading", anchor_type="roman")
        if NAMED_NUMBERED_RE.match(text):
            return ClassifiedLine(line=line, label="named_numbered_heading", anchor_type="named_numbered")
        if NUMERIC_RE.match(text):
            return ClassifiedLine(line=line, label="numeric_heading", anchor_type="numeric")
        if LETTER_RE.match(text):
            return ClassifiedLine(line=line, label="letter_heading", anchor_type="letter")
        return ClassifiedLine(line=line, label="body")


class Sectionizer:
    """Section-building state machine driven by configurable heading heuristics."""

    def __init__(self, config: HeuristicConfig):
        self.config = config
        self.classifier = LineClassifier()

    def sectionize(self, document: str, lines: List[ExtractedLine]) -> DocumentSections:
        """Build hierarchical sections from classified lines."""

        classified = [self.classifier.classify(line) for line in lines]

        sections: List[Section] = []
        preamble_lines: List[str] = []
        current: Optional[Section] = None

        for item in classified:
            line_text = collapse_ws(item.line.text)
            if not line_text:
                continue

            is_primary, level = self._is_primary(item)
            if is_primary:
                if current:
                    current.body = "\n".join(current.body_lines).strip()
                    sections.append(current)
                elif preamble_lines:
                    sections.append(self._build_preamble_section(document, preamble_lines, lines[0].page))
                    preamble_lines = []

                current = self._new_section(item=item, level=level, index=len(sections) + 1)
                continue

            if item.label == "reference_line" and current is None:
                continue

            if current is None:
                preamble_lines.append(line_text)
                continue

            current.body_lines.append(line_text)
            current.end_page = item.line.page
            self._maybe_add_child(current, item)

        if current:
            current.body = "\n".join(current.body_lines).strip()
            sections.append(current)
        elif preamble_lines and lines:
            sections.append(self._build_preamble_section(document, preamble_lines, lines[0].page))

        self._promote_heading_continuations(sections)
        self._assign_parent_links(sections)
        LOGGER.debug("Sectionized %d sections", len(sections))
        return DocumentSections(document=document, sections=sections)

    def _is_primary(self, item: ClassifiedLine) -> Tuple[bool, int]:
        """Decide whether a classified line starts a new primary section."""

        if item.label == "major_heading":
            return True, 1
        if item.label == "named_numbered_heading":
            return True, 1
        if item.label == "letter_heading":
            return True, 2
        if item.label == "numeric_heading":
            if self.config.use_numeric_as_primary:
                return True, 1
            return False, 0
        return False, 0

    def _new_section(self, item: ClassifiedLine, level: int, index: int) -> Section:
        """Create a new section object anchored on a heading line."""

        raw_title = collapse_ws(item.line.text)
        title = strip_toc_artifacts(raw_title)
        title_norm = normalize_title(title)
        sid = f"s{index:04d}-{slugify(title)[:40]}"
        return Section(
            section_id=sid,
            parent_id=None,
            level=level,
            anchor_type=item.label,
            title=title,
            title_normalized=title_norm,
            start_page=item.line.page,
            end_page=item.line.page,
            body="",
            body_lines=[],
            children=[],
            metadata={
                "anchor_type": item.anchor_type or item.label,
                "debug_label": item.label,
                "raw_title": raw_title,
            },
        )

    def _build_preamble_section(self, document: str, lines: List[str], page: int) -> Section:
        """Create a synthetic preamble section for text before first heading."""

        del document  # not currently needed for id generation
        text = "\n".join(lines).strip()
        return Section(
            section_id="preamble",
            parent_id=None,
            level=0,
            anchor_type="preamble",
            title="Preamble",
            title_normalized="preamble",
            start_page=page,
            end_page=page,
            body=text,
            body_lines=list(lines),
            children=[],
            metadata={"synthetic": True},
        )

    def _maybe_add_child(self, section: Section, item: ClassifiedLine) -> None:
        """Capture numeric/letter child items under current section when applicable."""

        text = collapse_ws(item.line.text)
        if item.label == "numeric_heading" and not self.config.use_numeric_as_primary:
            m = NUMERIC_RE.match(text)
            if m:
                section.children.append(ChildItem(item_number=m.group("num"), text=m.group("title")))
        elif item.label == "letter_heading" and section.level == 1:
            m = LETTER_RE.match(text)
            if m:
                section.children.append(ChildItem(item_number=m.group("num"), text=m.group("title")))

    def _assign_parent_links(self, sections: List[Section]) -> None:
        """Assign parent pointers for non-level-1 sections."""

        last_level_1: Optional[str] = None
        for section in sections:
            if section.level <= 1:
                last_level_1 = section.section_id if section.level == 1 else last_level_1
                continue
            section.parent_id = last_level_1

    def _promote_heading_continuations(self, sections: List[Section]) -> None:
        """
        Merge wrapped heading continuation lines back into section titles.

        PDFs often split long headings across lines. When a heading appears truncated
        and the first body line looks like a continuation (eg starts lowercase), we
        treat that first line as part of the title.
        """

        for s in sections:
            if not s.body_lines or s.anchor_type == "preamble":
                continue
            if s.anchor_type not in {"major_heading", "named_numbered_heading"}:
                continue
            if len(s.title.split()) < 8:
                continue

            merged = 0
            # Merge at most one continuation line to avoid swallowing body text.
            if s.body_lines and self._looks_like_title_continuation(s.title, s.body_lines[0]):
                continuation = s.body_lines.pop(0)
                s.title = collapse_ws(f"{s.title} {continuation}")
                merged = 1

            if merged:
                s.title_normalized = normalize_title(s.title)
                s.body = "\n".join(s.body_lines).strip()

    @staticmethod
    def _looks_like_title_continuation(title: str, first_body_line: str) -> bool:
        """Heuristic gate to decide if first body line should be appended to title."""

        t = collapse_ws(title)
        b = collapse_ws(first_body_line)
        if not t or not b:
            return False

        # Continuation lines typically start lowercase/punctuation after a wrap.
        if not re.match(r"^[a-z(,;]", b):
            return False

        # Heading likely incomplete if ending with connector words or non-terminal punctuation.
        if re.search(r"\b(in|to|of|and|or|for|with|on|at|by|from|under|within)$", t, flags=re.IGNORECASE):
            return True
        if re.search(r"[,:;/-]$", t):
            return True
        if not re.search(r"[.?!]$", t):
            return True
        return False


def sectionize_lines(document: str, lines: List[ExtractedLine], config: HeuristicConfig) -> DocumentSections:
    """Convenience wrapper for sectionization."""

    return Sectionizer(config=config).sectionize(document=document, lines=lines)
