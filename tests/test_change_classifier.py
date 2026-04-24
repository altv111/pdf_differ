from classifier import (
    arbitrate_classification,
    classify_diff_report,
    classify_section,
    classify_with_rules,
    extract_features,
)


def test_feature_extraction_detects_numeric_date_currency_and_negation() -> None:
    payload = {
        "section_title": "Principle X",
        "before_text": "The bank must report by 2025-01-01 and keep USD 10,000. This is not optional.",
        "after_text": "The bank may report by 2026-01-01 and keep USD 12,000. This is optional.",
    }
    f = extract_features(payload)
    assert f["numeric_changes_count"] > 0
    assert f["dates_changed"] > 0
    assert f["currency_changed"] > 0
    assert f["obligation_change"] is True
    assert f["negation_change"] is True


def test_rule_engine_marks_significant_on_hard_signal() -> None:
    features = {
        "change_ratio": 0.01,
        "lines_added": 0,
        "lines_removed": 0,
        "changed_pairs_count": 0,
        "numeric_changes_count": 0,
        "dates_changed": 0,
        "percentages_changed": 0,
        "currency_changed": 0,
        "obligation_change": True,
        "negation_change": False,
        "scope_change_cues": False,
        "table_change_detected": False,
        "token_jaccard": 0.99,
        "sentence_overlap": 0.99,
    }
    rule = classify_with_rules(features)
    assert rule.label == "significant"


def test_rule_engine_marks_editorial_for_tiny_surface_change() -> None:
    payload = {
        "section_title": "Intro",
        "before_text": "Banks should manage risk prudently.",
        "after_text": "Banks should manage risk prudently.",
    }
    features = extract_features(payload)
    rule = classify_with_rules(features)
    assert rule.label == "editorial"


def test_arbitration_flags_disagreement_and_preserves_llm_final() -> None:
    payload = {
        "section_id": "s1",
        "section_title": "Principle 1",
        "before_text": "Banks must report all exposures.",
        "after_text": "Banks may report some exposures.",
        "llm_mock_label": "slight",
    }
    result = classify_section(payload)
    assert result["rule_classification"]["label"] == "significant"
    assert result["llm_classification"]["label"] == "slight"
    assert result["disagreement_flag"] is True
    assert result["final_classification"] == "slight"
    assert result["override_candidate"] == "significant"


def test_classify_diff_report_maps_existing_diff_shape() -> None:
    report = {
        "pdf_a": "a.pdf",
        "pdf_b": "b.pdf",
        "diffs": [
            {
                "section_id_a": "a1",
                "section_id_b": "b1",
                "title_a": "Principle 11: ...",
                "title_b": "Principle 11: ...",
                "semantic_text_a": "Banks should report all exposures.",
                "semantic_text_b": "Banks should report all exposures.",
                "match_score": 0.99,
                "semantic_status": "unchanged",
                "anchor_type": "named_numbered_heading",
            }
        ],
    }
    out = classify_diff_report(report)
    assert out["summary"]["total"] == 1
    assert out["classifications"][0]["section_id"] == "b1"
    assert out["classifications"][0]["features"]["change_ratio"] == 0.0
