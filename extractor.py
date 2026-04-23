"""Layout-aware PDF extraction and running header/footer cleanup."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

from models import ExtractedLine, HeuristicConfig
from utils import (
    collapse_ws,
    is_page_number_only,
    line_is_likely_noise,
    normalize_header_footer_candidate,
)

LOGGER = logging.getLogger("pdf_section_diff.extractor")

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None


@dataclass
class ExtractionResult:
    """Cleaned extracted lines plus removed noise and debug counters."""

    lines: List[ExtractedLine]
    removed_header_footer_lines: List[ExtractedLine]
    debug: Dict[str, object]


class HeaderFooterDetector:
    """Detect repeated running headers/footers using top/bottom page bands."""

    def __init__(self, config: HeuristicConfig):
        self.config = config

    def detect(self, page_lines: Dict[int, List[ExtractedLine]], page_heights: Dict[int, float]) -> set[Tuple[int, str]]:
        """
        Identify removable header/footer lines.

        Detection combines exact normalized repeats, page-number-only detection,
        and fuzzy near-duplicate clustering in top/bottom page bands.
        """

        candidates: List[Tuple[int, str, str, str]] = []
        total_pages = max(1, len(page_lines))

        for page, lines in page_lines.items():
            if page not in page_heights:
                continue
            h = page_heights[page]
            top_cut = h * self.config.top_band_ratio
            bottom_cut = h * (1.0 - self.config.bottom_band_ratio)

            for line in lines:
                text = collapse_ws(line.text)
                if not text:
                    continue
                if line.y1 <= top_cut:
                    region = "top"
                elif line.y0 >= bottom_cut:
                    region = "bottom"
                else:
                    continue
                normalized = normalize_header_footer_candidate(text)
                candidates.append((page, text, normalized, region))

        repeats = Counter((norm, region) for _, _, norm, region in candidates)
        removable: set[Tuple[int, str]] = set()

        for page, text, normalized, region in candidates:
            repeat_ratio = repeats[(normalized, region)] / total_pages
            page_num_like = is_page_number_only(text)
            if page_num_like or repeat_ratio >= self.config.min_header_footer_repeat_ratio:
                removable.add((page, text))

        # Fuzzy near-duplicate clustering catches OCR / spacing artifacts in running footers.
        fuzzy_removable = self._detect_fuzzy_repeats(candidates, total_pages)
        removable.update(fuzzy_removable)

        return removable

    def _detect_fuzzy_repeats(
        self,
        candidates: List[Tuple[int, str, str, str]],
        total_pages: int,
    ) -> set[Tuple[int, str]]:
        """Cluster near-duplicate edge-band candidates and mark repeated clusters removable."""

        by_region: Dict[str, List[Tuple[int, str, str]]] = {"top": [], "bottom": []}
        for page, text, normalized, region in candidates:
            by_region.setdefault(region, []).append((page, text, normalized))

        removable: set[Tuple[int, str]] = set()
        for region, items in by_region.items():
            if len(items) < 2:
                continue

            clusters: List[List[Tuple[int, str, str]]] = []
            for item in items:
                page, text, normalized = item
                placed = False
                for cluster in clusters:
                    rep_norm = cluster[0][2]
                    if self._similar(normalized, rep_norm) >= 0.92:
                        cluster.append(item)
                        placed = True
                        break
                if not placed:
                    clusters.append([item])

            for cluster in clusters:
                pages = {p for p, _, _ in cluster}
                ratio = len(pages) / max(1, total_pages)
                if ratio >= self.config.min_header_footer_repeat_ratio:
                    for p, text, _ in cluster:
                        removable.add((p, text))

                # Additional "running title + page number" heuristic in page-edge bands.
                # Example: "Consultation on ... credit risk 11"
                if len(pages) >= 2:
                    for p, text, norm in cluster:
                        if self._looks_like_running_title_with_page(text, norm):
                            removable.add((p, text))

        return removable

    @staticmethod
    def _looks_like_running_title_with_page(text: str, normalized: str) -> bool:
        stripped = collapse_ws(text)
        if len(stripped) < 20:
            return False
        if not re.search(r"\b\d{1,4}\b$", stripped):
            return False
        # Disallow very short fragments that could be legitimate numbered body lines.
        alpha_chars = sum(ch.isalpha() for ch in stripped)
        if alpha_chars < 12:
            return False
        # Keep only page-edge running title style strings.
        return bool(re.search(r"[a-z]", normalized))

    @staticmethod
    def _similar(a: str, b: str) -> float:
        """Similarity helper using rapidfuzz when available, otherwise SequenceMatcher."""

        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if fuzz is not None:
            return fuzz.token_set_ratio(a, b) / 100.0
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio()


class PDFExtractor:
    """Layout-aware PDF extractor that reconstructs lines from positioned spans."""

    def __init__(self, config: HeuristicConfig):
        self.config = config
        self.detector = HeaderFooterDetector(config)

    def extract(self, pdf_path: str) -> ExtractionResult:
        """Extract and clean lines from a PDF file."""

        fitz = self._import_fitz()

        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to open PDF {pdf_path}: {exc}") from exc

        page_lines: Dict[int, List[ExtractedLine]] = {}
        page_heights: Dict[int, float] = {}

        for i, page in enumerate(doc):
            page_num = i + 1
            page_heights[page_num] = float(page.rect.height)
            lines = self._extract_page_lines(page, page_num)
            page_lines[page_num] = lines
            LOGGER.debug("Extracted %d lines from page %d", len(lines), page_num)

        removable = self.detector.detect(page_lines=page_lines, page_heights=page_heights)
        manual_header = [re.compile(p, flags=re.IGNORECASE) for p in self.config.header_patterns]
        manual_footer = [re.compile(p, flags=re.IGNORECASE) for p in self.config.footer_patterns]

        clean_lines: List[ExtractedLine] = []
        removed_lines: List[ExtractedLine] = []

        for page, lines in page_lines.items():
            for line in lines:
                stripped = collapse_ws(line.text)
                if not stripped:
                    continue

                auto_remove = (page, stripped) in removable
                manual_remove = any(r.search(stripped) for r in manual_header + manual_footer)
                page_num_only = is_page_number_only(stripped)
                noise = line_is_likely_noise(stripped, self.config.ignore_patterns)

                if auto_remove or manual_remove or page_num_only or noise:
                    line.is_header_footer = True
                    removed_lines.append(line)
                else:
                    clean_lines.append(line)

        debug = {
            "total_pages": len(page_lines),
            "total_lines": sum(len(v) for v in page_lines.values()),
            "removed_lines": len(removed_lines),
            "remaining_lines": len(clean_lines),
        }
        return ExtractionResult(lines=clean_lines, removed_header_footer_lines=removed_lines, debug=debug)

    def _extract_page_lines(self, page, page_num: int) -> List[ExtractedLine]:
        """Reconstruct reading-order lines by grouping nearby spans by y-position."""

        data = page.get_text("dict")
        spans: List[Dict[str, float | str | int]] = []

        for b_index, block in enumerate(data.get("blocks", [])):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text", ""))
                    text = collapse_ws(text)
                    if not text:
                        continue
                    x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                    spans.append(
                        {
                            "text": text,
                            "x0": float(x0),
                            "y0": float(y0),
                            "x1": float(x1),
                            "y1": float(y1),
                            "block": b_index,
                        }
                    )

        spans.sort(key=lambda s: (round(float(s["y0"]), 1), float(s["x0"])))

        lines: List[ExtractedLine] = []
        current: List[Dict[str, float | str | int]] = []
        y_tol = 2.0

        def flush_current() -> None:
            nonlocal current
            if not current:
                return
            current.sort(key=lambda s: float(s["x0"]))
            text = " ".join(str(s["text"]) for s in current)
            line = ExtractedLine(
                text=text,
                page=page_num,
                x0=min(float(s["x0"]) for s in current),
                y0=min(float(s["y0"]) for s in current),
                x1=max(float(s["x1"]) for s in current),
                y1=max(float(s["y1"]) for s in current),
                source_block=int(current[0]["block"]),
            )
            lines.append(line)
            current = []

        for span in spans:
            if not current:
                current.append(span)
                continue
            base_y = float(current[-1]["y0"])
            if abs(float(span["y0"]) - base_y) <= y_tol:
                current.append(span)
            else:
                flush_current()
                current.append(span)

        flush_current()
        lines.sort(key=lambda ln: (ln.page, ln.y0, ln.x0))
        return lines

    @staticmethod
    def _import_fitz():
        """Import PyMuPDF lazily to provide a clearer dependency error."""

        try:
            import fitz  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised when dependency missing
            raise RuntimeError(
                "PyMuPDF is required for PDF extraction. Install dependencies from requirements.txt"
            ) from exc
        return fitz


def extract_pdf_lines(
    pdf_path: str,
    config: HeuristicConfig,
) -> ExtractionResult:
    """Convenience wrapper for one-shot PDF extraction."""

    extractor = PDFExtractor(config=config)
    return extractor.extract(pdf_path)
