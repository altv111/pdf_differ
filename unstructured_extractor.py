"""Optional extraction backend using Unstructured's PDF partitioner.

This backend is intended for A/B testing against the primary PyMuPDF extractor.
It returns `ExtractedLine` objects with best-effort page and coordinate metadata.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from models import ExtractedLine
from utils import collapse_ws


def extract_with_unstructured(
    pdf_path: str,
) -> tuple[Dict[int, List[ExtractedLine]], Dict[int, float], Dict[str, object], bool]:
    """Extract page lines from a PDF via unstructured.partition.pdf.

    Returns:
    - page_lines: grouped extracted lines by page
    - page_heights: best-effort page heights
    - backend_debug: backend-specific stats
    - has_reliable_positions: whether positional header/footer heuristics are safe
    """

    try:
        from unstructured.partition.pdf import partition_pdf  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency-gated
        raise RuntimeError(
            "Unstructured backend requires extra dependencies. "
            "Install with: pip install \"unstructured[pdf]\""
        ) from exc

    # Default to fast for text PDFs and lower dependency/runtime overhead.
    strategy = "fast"
    elements = partition_pdf(filename=pdf_path, strategy=strategy)

    page_lines: Dict[int, List[ExtractedLine]] = {}
    page_heights: Dict[int, float] = {}

    total = 0
    with_coords = 0

    per_page_row = {}

    for idx, el in enumerate(elements):
        text = collapse_ws(getattr(el, "text", "") or "")
        if not text:
            continue

        meta = getattr(el, "metadata", None)
        page = int(getattr(meta, "page_number", 1) or 1)

        y_fallback = float(per_page_row.get(page, 0))
        per_page_row[page] = per_page_row.get(page, 0) + 1

        x0 = 0.0
        y0 = y_fallback
        x1 = float(len(text))
        y1 = y_fallback + 1.0

        coords = getattr(meta, "coordinates", None)
        if coords is not None and getattr(coords, "points", None):
            pts = coords.points
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            x0 = min(xs)
            y0 = min(ys)
            x1 = max(xs)
            y1 = max(ys)
            with_coords += 1
            layout_h = getattr(coords, "layout_height", None)
            if layout_h:
                page_heights[page] = max(page_heights.get(page, 0.0), float(layout_h))

        if page not in page_heights:
            # Best-effort fallback height when coordinates are absent.
            page_heights[page] = 1000.0

        page_lines.setdefault(page, []).append(
            ExtractedLine(
                text=text,
                page=page,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                source_block=idx,
            )
        )
        total += 1

    for page, lines in page_lines.items():
        lines.sort(key=lambda ln: (ln.y0, ln.x0))

    coordinate_ratio = (with_coords / total) if total else 0.0
    has_reliable_positions = coordinate_ratio >= 0.8

    backend_debug = {
        "elements_total": total,
        "elements_with_coordinates": with_coords,
        "coordinate_ratio": round(coordinate_ratio, 4),
        "strategy": strategy,
    }

    return page_lines, page_heights, backend_debug, has_reliable_positions
