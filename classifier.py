"""Hybrid section-diff classifier (deterministic rules + LLM hook).

This module classifies each section diff into:
- editorial
- slight
- significant

Design:
1) deterministic feature extraction
2) rule-based classification with confidence + triggered rules
3) LLM stub classification hook (no external calls)
4) arbitration + disagreement flag

Current policy:
- final_classification defaults to LLM classification label when present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from llm_client import classify_with_llm

WORD_RE = re.compile(r"[A-Za-z0-9%$€£.,/-]+")
NUM_RE = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b")
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%\b")
CURRENCY_RE = re.compile(r"(?:[$€£]\s?\d+(?:,\d{3})*(?:\.\d+)?|\b(?:usd|eur|gbp|aud|cad|inr)\s?\d+(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE)
DATE_RE = re.compile(
    r"(?:\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b)",
    re.IGNORECASE,
)

OBLIGATION_CUES = {"must", "shall", "required", "require", "mandatory", "prohibited", "forbidden", "may not"}
NEGATION_CUES = {"not", "no", "never", "without", "none", "cannot", "can't", "won't", "unless"}
SCOPE_CUES = {
    "all",
    "any",
    "only",
    "except",
    "including",
    "excluding",
    "solely",
    "limited to",
    "at least",
    "at most",
    "across",
    "within",
}


@dataclass
class RuleResult:
    """Rule-engine output used in arbitration."""

    label: str
    confidence: float
    triggered_rules: List[str]


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in WORD_RE.findall(text or "")]


def _sentences(text: str) -> List[str]:
    clean = _normalize_spaces(text)
    if not clean:
        return []
    parts = re.split(r"(?<=[.?!])\s+", clean)
    return [p.strip().lower() for p in parts if p.strip()]


def _set_diff_count(pattern: re.Pattern[str], before: str, after: str) -> int:
    a = {m.group(0).lower() for m in pattern.finditer(before)}
    b = {m.group(0).lower() for m in pattern.finditer(after)}
    return len(a.symmetric_difference(b))


def _contains_any_cue(text: str, cues: Iterable[str]) -> bool:
    lower = (text or "").lower()
    return any(cue in lower for cue in cues)


def _line_change_counts(before: str, after: str) -> Tuple[int, int, int]:
    """Return lines_added, lines_removed, changed_pairs_count from line diff opcodes."""

    lines_a = before.splitlines()
    lines_b = after.splitlines()
    matcher = SequenceMatcher(None, lines_a, lines_b)

    lines_added = 0
    lines_removed = 0
    changed_pairs = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            lines_added += j2 - j1
        elif tag == "delete":
            lines_removed += i2 - i1
        elif tag == "replace":
            removed = i2 - i1
            added = j2 - j1
            lines_removed += removed
            lines_added += added
            changed_pairs += max(removed, added)

    return lines_added, lines_removed, changed_pairs


def extract_features(section_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract deterministic features from one section payload."""

    before = section_payload.get("before_text", "") or ""
    after = section_payload.get("after_text", "") or ""

    ratio = SequenceMatcher(None, _normalize_spaces(before), _normalize_spaces(after)).ratio()
    change_ratio = 1.0 - ratio

    lines_added, lines_removed, changed_pairs_count = _line_change_counts(before, after)

    tokens_a = set(_tokens(before))
    tokens_b = set(_tokens(after))
    token_union = tokens_a.union(tokens_b)
    token_jaccard = (len(tokens_a.intersection(tokens_b)) / len(token_union)) if token_union else 1.0

    sent_a = set(_sentences(before))
    sent_b = set(_sentences(after))
    sent_union = sent_a.union(sent_b)
    sentence_overlap = (len(sent_a.intersection(sent_b)) / len(sent_union)) if sent_union else 1.0

    obligation_change = _contains_any_cue(before, OBLIGATION_CUES) != _contains_any_cue(after, OBLIGATION_CUES)
    negation_change = _contains_any_cue(before, NEGATION_CUES) != _contains_any_cue(after, NEGATION_CUES)
    scope_change_cues = _contains_any_cue(before, SCOPE_CUES) != _contains_any_cue(after, SCOPE_CUES)

    numeric_changes_count = _set_diff_count(NUM_RE, before, after)
    dates_changed = _set_diff_count(DATE_RE, before, after)
    percentages_changed = _set_diff_count(PERCENT_RE, before, after)
    currency_changed = _set_diff_count(CURRENCY_RE, before, after)

    table_like_before = bool(re.search(r"\|", before) or re.search(r"\t", before) or re.search(r"\s{3,}\S+\s{3,}", before))
    table_like_after = bool(re.search(r"\|", after) or re.search(r"\t", after) or re.search(r"\s{3,}\S+\s{3,}", after))
    table_change_detected = table_like_before != table_like_after

    return {
        "change_ratio": round(change_ratio, 6),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "changed_pairs_count": changed_pairs_count,
        "numeric_changes_count": numeric_changes_count,
        "dates_changed": dates_changed,
        "percentages_changed": percentages_changed,
        "currency_changed": currency_changed,
        "obligation_change": obligation_change,
        "negation_change": negation_change,
        "scope_change_cues": scope_change_cues,
        "table_change_detected": table_change_detected,
        "token_jaccard": round(token_jaccard, 6),
        "sentence_overlap": round(sentence_overlap, 6),
    }


def classify_with_rules(features: Dict[str, Any]) -> RuleResult:
    """Classify section diff using deterministic production rules."""

    triggered: List[str] = []

    hard_signals = {
        "obligation_change": bool(features["obligation_change"]),
        "negation_change": bool(features["negation_change"]),
        "scope_change_cues": bool(features["scope_change_cues"]),
        "numeric_changes": int(features["numeric_changes_count"]) > 0,
        "date_changes": int(features["dates_changed"]) > 0,
        "percentage_changes": int(features["percentages_changed"]) > 0,
        "currency_changes": int(features["currency_changed"]) > 0,
    }

    if hard_signals["obligation_change"]:
        triggered.append("obligation_change")
    if hard_signals["negation_change"]:
        triggered.append("negation_change")
    if hard_signals["scope_change_cues"]:
        triggered.append("scope_change_cues")
    if hard_signals["numeric_changes"]:
        triggered.append("numeric_changes")
    if hard_signals["date_changes"]:
        triggered.append("date_changes")
    if hard_signals["percentage_changes"]:
        triggered.append("percentage_changes")
    if hard_signals["currency_changes"]:
        triggered.append("currency_changes")

    if any(hard_signals.values()):
        return RuleResult(label="significant", confidence=0.9, triggered_rules=triggered)

    if (
        features["change_ratio"] <= 0.03
        and features["token_jaccard"] >= 0.97
        and features["sentence_overlap"] >= 0.95
    ):
        triggered.append("high_similarity_low_change_ratio")
        return RuleResult(label="editorial", confidence=0.88, triggered_rules=triggered)

    if features["change_ratio"] >= 0.45 or features["token_jaccard"] < 0.5:
        triggered.append("large_change_surface")
        return RuleResult(label="significant", confidence=0.78, triggered_rules=triggered)

    triggered.append("default_small_semantic_change")
    return RuleResult(label="slight", confidence=0.7, triggered_rules=triggered)


def arbitrate_classification(
    features: Dict[str, Any],
    rule_result: RuleResult,
    llm_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Combine rule and LLM outputs, expose disagreement + override candidate."""

    llm_label = llm_result.get("label")
    hard_signal_flags = {
        "obligation_change": bool(features["obligation_change"]),
        "negation_change": bool(features["negation_change"]),
        "scope_change_cues": bool(features["scope_change_cues"]),
        "numeric_or_value_changes": (
            int(features["numeric_changes_count"]) > 0
            or int(features["dates_changed"]) > 0
            or int(features["percentages_changed"]) > 0
            or int(features["currency_changed"]) > 0
        ),
    }

    disagreement_flag = bool(llm_label and llm_label != rule_result.label)

    override_candidate = None
    if any(hard_signal_flags.values()) and llm_label in {"editorial", "slight"}:
        override_candidate = "significant"

    # Current policy requested by product: final follows LLM result.
    final_classification = llm_label or rule_result.label

    return {
        "hard_signal_flags": hard_signal_flags,
        "disagreement_flag": disagreement_flag,
        "override_candidate": override_candidate,
        "final_classification": final_classification,
    }


def classify_section(
    section_payload: Dict[str, Any],
    event_hook: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """End-to-end hybrid classification for one section diff payload."""

    features = extract_features(section_payload)
    rule = classify_with_rules(features)
    if event_hook:
        event_hook(
            "pre_llm",
            {
                "section_id": section_payload.get("section_id"),
                "section_title": section_payload.get("section_title"),
                "rule_label": rule.label,
            },
        )
    llm = classify_with_llm(section_payload)
    if event_hook:
        event_hook(
            "post_llm",
            {
                "section_id": section_payload.get("section_id"),
                "section_title": section_payload.get("section_title"),
                "llm_label": llm.get("label"),
                "stub": llm.get("stub"),
            },
        )
    arbitration = arbitrate_classification(features, rule, llm)

    return {
        "section_id": section_payload.get("section_id"),
        "section_title": section_payload.get("section_title"),
        "features": features,
        "rule_classification": {
            "label": rule.label,
            "confidence": rule.confidence,
            "triggered_rules": rule.triggered_rules,
        },
        "llm_classification": llm,
        "hard_signal_flags": arbitration["hard_signal_flags"],
        "disagreement_flag": arbitration["disagreement_flag"],
        "override_candidate": arbitration["override_candidate"],
        "final_classification": arbitration["final_classification"],
    }


def _section_payload_from_diff_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map existing diff JSON row into classifier input schema."""

    title = item.get("title_b") or item.get("title_a") or item.get("section_title")
    before_text = item.get("semantic_text_a") or "\n".join(item.get("section_lines_a", []))
    after_text = item.get("semantic_text_b") or "\n".join(item.get("section_lines_b", []))

    return {
        "section_id": item.get("section_id_b") or item.get("section_id_a"),
        "section_title": title,
        "before_text": before_text,
        "after_text": after_text,
        "diff_score": item.get("match_score"),
        "metadata": {
            "status": item.get("semantic_status") or item.get("status"),
            "anchor_type": item.get("anchor_type"),
            "low_confidence": item.get("low_confidence"),
        },
    }


def classify_diff_report(
    diff_report: Dict[str, Any],
    progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
    event_hook: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Classify every section diff entry from a precomputed diff report."""

    diffs = diff_report.get("diffs", [])
    total = len(diffs)
    classifications = []
    for idx, item in enumerate(diffs, start=1):
        payload = _section_payload_from_diff_item(item)
        if progress_callback:
            progress_callback(idx, total, payload)
        classifications.append(classify_section(payload, event_hook=event_hook))

    summary = {
        "total": len(classifications),
        "editorial": sum(1 for c in classifications if c["final_classification"] == "editorial"),
        "slight": sum(1 for c in classifications if c["final_classification"] == "slight"),
        "significant": sum(1 for c in classifications if c["final_classification"] == "significant"),
        "disagreements": sum(1 for c in classifications if c["disagreement_flag"]),
    }

    return {
        "source_pdf_a": diff_report.get("pdf_a"),
        "source_pdf_b": diff_report.get("pdf_b"),
        "summary": summary,
        "classifications": classifications,
    }
