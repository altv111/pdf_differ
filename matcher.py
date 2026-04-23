"""Section alignment logic between two documents using weighted similarity signals."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from models import HeuristicConfig, Section, SectionMatch
from utils import short_body_prefix

LOGGER = logging.getLogger("pdf_section_diff.matcher")

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None


@dataclass
class MatchConfig:
    """Weights and thresholds used by the matching scorer."""

    high_confidence_threshold: float = 0.78
    low_confidence_threshold: float = 0.55
    weight_title: float = 0.65
    weight_body: float = 0.25
    weight_anchor: float = 0.05
    weight_order: float = 0.05


class SectionMatcher:
    """Match semantic sections across two documents."""

    def __init__(self, heuristic_config: HeuristicConfig, match_config: Optional[MatchConfig] = None):
        self.heuristic_config = heuristic_config
        self.match_config = match_config or MatchConfig()

    def match(self, sections_a: List[Section], sections_b: List[Section]) -> List[SectionMatch]:
        """Produce one-to-one section matches plus unmatched entries."""

        pool_a = [s for s in sections_a if s.level <= 1 and s.anchor_type != "preamble"]
        pool_b = [s for s in sections_b if s.level <= 1 and s.anchor_type != "preamble"]

        candidates: List[Tuple[float, int, int, str]] = []

        for ia, sa in enumerate(pool_a):
            for ib, sb in enumerate(pool_b):
                score, reason = self._score(sa, sb, ia, ib, len(pool_a), len(pool_b))
                candidates.append((score, ia, ib, reason))

        candidates.sort(key=lambda c: c[0], reverse=True)

        used_a = set()
        used_b = set()
        results: List[SectionMatch] = []

        for score, ia, ib, reason in candidates:
            if score < self.match_config.low_confidence_threshold:
                break
            if ia in used_a or ib in used_b:
                continue
            used_a.add(ia)
            used_b.add(ib)
            confidence = (
                "matched"
                if score >= self.match_config.high_confidence_threshold
                else "low-confidence matched"
            )
            results.append(
                SectionMatch(
                    section_id_a=pool_a[ia].section_id,
                    section_id_b=pool_b[ib].section_id,
                    score=round(score, 4),
                    confidence=confidence,
                    reason=reason,
                )
            )

        for ia, sa in enumerate(pool_a):
            if ia not in used_a:
                results.append(
                    SectionMatch(
                        section_id_a=sa.section_id,
                        section_id_b=None,
                        score=0.0,
                        confidence="unmatched",
                        reason="No candidate passed threshold",
                    )
                )
        for ib, sb in enumerate(pool_b):
            if ib not in used_b:
                results.append(
                    SectionMatch(
                        section_id_a=None,
                        section_id_b=sb.section_id,
                        score=0.0,
                        confidence="unmatched",
                        reason="No candidate passed threshold",
                    )
                )

        return results

    def _score(
        self,
        a: Section,
        b: Section,
        idx_a: int,
        idx_b: int,
        total_a: int,
        total_b: int,
    ) -> Tuple[float, str]:
        """Compute weighted match score and a debug reason string."""

        title_score_raw = self._sim(a.title_normalized, b.title_normalized)
        title_core_a = self._strip_heading_prefix(a.title_normalized)
        title_core_b = self._strip_heading_prefix(b.title_normalized)
        title_score_core = self._sim(title_core_a, title_core_b)
        title_score = 0.35 * title_score_raw + 0.65 * title_score_core
        body_score = self._sim(short_body_prefix(a.body), short_body_prefix(b.body))
        anchor_score = 1.0 if a.anchor_type == b.anchor_type else 0.4

        span = max(1, max(total_a, total_b) - 1)
        order_distance = abs(idx_a - idx_b)
        order_score = max(0.0, 1.0 - (order_distance / span))

        mc = self.match_config
        score = (
            mc.weight_title * title_score
            + mc.weight_body * body_score
            + mc.weight_anchor * anchor_score
            + mc.weight_order * order_score
        )

        reason = (
            f"title_raw={title_score_raw:.3f}, title_core={title_score_core:.3f}, "
            f"title={title_score:.3f}, body={body_score:.3f}, "
            f"anchor={anchor_score:.3f}, order={order_score:.3f}"
        )
        return score, reason

    @staticmethod
    def _strip_heading_prefix(text: str) -> str:
        """Remove numbering/prefix tokens so title-core semantics can be compared."""

        value = text.strip()
        # Remove leading numbering labels (roman, numeric, letter) and named numbered prefixes.
        value = re.sub(r"^(?:[ivxlcdm]+|\d+|[a-z])\s*[.)-]\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(
            r"^(?:principle|article|section|chapter|standard|rule)\s+\d+[a-z]?\s*[:.-]?\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return value.strip()

    @staticmethod
    def _sim(a: str, b: str) -> float:
        """String similarity helper with rapidfuzz fallback to difflib."""

        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if fuzz is not None:
            return fuzz.token_set_ratio(a, b) / 100.0
        return SequenceMatcher(None, a, b).ratio()


def map_sections_by_id(sections: List[Section]) -> Dict[str, Section]:
    """Create id->section lookup map."""

    return {s.section_id: s for s in sections}
