"""Utility helpers for normalization, serialization, and logging."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable, List


LOGGER = logging.getLogger("pdf_section_diff")


PUNCT_RE = re.compile(r"[^\w\s]")
WHITESPACE_RE = re.compile(r"\s+")
STANDALONE_NUM_RE = re.compile(r"\b\d+\b")
TOC_DOT_LEADER_RE = re.compile(r"^(?P<title>.+?)\s*[.\u2026·]{3,}\s*(?P<page>\d{1,4})\s*$")
TRAILING_PAGE_RE = re.compile(r"^(?P<title>.+?)\s+(?P<page>\d{1,4})\s*$")


def configure_logging(debug: bool = False) -> None:
    """Configure project-wide logging format and verbosity."""

    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def collapse_ws(text: str) -> str:
    """Collapse repeated whitespace into single spaces and trim edges."""

    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_header_footer_candidate(text: str) -> str:
    """Normalize noisy running header/footer text for repeat detection."""

    lowered = text.lower()
    lowered = collapse_ws(lowered)
    lowered = STANDALONE_NUM_RE.sub("<num>", lowered)
    return lowered


def normalize_title(text: str, remove_boilerplate: Iterable[str] | None = None) -> str:
    """Normalize section titles for robust matching and deduplication."""

    value = strip_toc_artifacts(text).lower()
    value = PUNCT_RE.sub(" ", value)
    value = collapse_ws(value)
    if remove_boilerplate:
        tokens = value.split()
        boilerplate = set(t.lower() for t in remove_boilerplate)
        tokens = [t for t in tokens if t not in boilerplate]
        value = " ".join(tokens)
    return value


def strip_toc_artifacts(text: str) -> str:
    """
    Remove common TOC-like suffix artifacts from headings:
    - dot leaders + trailing page number
    - trailing page number after long heading phrase
    """

    value = collapse_ws(text)
    m = TOC_DOT_LEADER_RE.match(value)
    if m:
        return collapse_ws(m.group("title"))

    m = TRAILING_PAGE_RE.match(value)
    if m:
        title = collapse_ws(m.group("title"))
        # Apply only to likely heading-like lines, not to short numeric statements.
        if len(title.split()) >= 4 and re.search(
            r"^(?:[IVXLCDM]+\.\s+|(?:chapter|section|part|annex)\b)",
            title,
            flags=re.IGNORECASE,
        ):
            return title
    return value


def normalize_body(text: str) -> str:
    """Normalize body text for case/whitespace-insensitive comparisons."""

    return collapse_ws(text.lower())


def safe_write_json(path: str | Path, data: object) -> None:
    """Write JSON to disk, creating parent directories as needed."""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def is_page_number_only(text: str) -> bool:
    """Return True when text looks like a standalone page-number artifact."""

    candidate = collapse_ws(text)
    if not candidate:
        return False
    return bool(re.fullmatch(r"(?:page\s+)?\d+(?:\s*/\s*\d+)?", candidate, flags=re.IGNORECASE))


def slugify(text: str) -> str:
    """Build a stable, filesystem-safe slug from title text."""

    slug = normalize_title(text)
    slug = slug.replace(" ", "-")
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"


def short_body_prefix(text: str, limit: int = 240) -> str:
    """Return normalized body prefix used as a lightweight matching signal."""

    norm = normalize_body(text)
    if len(norm) <= limit:
        return norm
    return norm[:limit]


def line_is_likely_noise(text: str, ignore_patterns: List[str]) -> bool:
    """Check whether a line should be dropped by configurable ignore rules."""

    stripped = text.strip()
    if not stripped:
        return True
    for pat in ignore_patterns:
        if re.search(pat, stripped, flags=re.IGNORECASE):
            return True
    return False
