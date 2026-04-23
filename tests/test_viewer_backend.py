from pathlib import Path

from viewer_backend import (
    ClassificationUpdateRequest,
    ReviewStore,
    ReviewUpdateRequest,
    _diff_id,
    list_available_reports,
    merge_runtime_fields,
    resolve_report_path,
)


def test_diff_id_stable() -> None:
    d = {"section_id_a": "a1", "section_id_b": "b2"}
    assert _diff_id(d, 7) == "7:a1->b2"


def test_merge_runtime_fields_defaults(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "state.db")
    diffs = [{"section_id_a": "a1", "section_id_b": "b1", "status": "modified"}]
    merged = merge_runtime_fields(store, diffs)
    assert len(merged) == 1
    assert merged[0]["human_review"]["validation_status"] == "needs_review"


def test_review_and_classification_overlay(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "state.db")
    diff = {"section_id_a": "a1", "section_id_b": "b1", "status": "modified"}
    diff_id = _diff_id(diff, 0)

    store.set_review(
        diff_id,
        ReviewUpdateRequest(validation_status="approved", reviewer="alice", note="looks good"),
    )
    store.set_classification(
        diff_id,
        ClassificationUpdateRequest(classification="slight", source="manual"),
    )

    merged = merge_runtime_fields(store, [diff])
    assert merged[0]["human_review"]["validation_status"] == "approved"
    assert merged[0]["change_classification"] == "slight"


def test_list_available_reports(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    reports = list_available_reports(tmp_path)
    assert reports == ["a.json", "b.json"]


def test_resolve_report_path_allows_local_json(tmp_path: Path) -> None:
    current = tmp_path / "a.json"
    current.write_text("{}", encoding="utf-8")
    target = tmp_path / "b.json"
    target.write_text("{}", encoding="utf-8")

    resolved = resolve_report_path(tmp_path, "b.json", current)
    assert resolved == target.resolve()
