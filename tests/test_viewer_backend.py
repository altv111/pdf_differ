from pathlib import Path

from viewer_backend import (
    ClassificationUpdateRequest,
    ReviewStore,
    ReviewUpdateRequest,
    _diff_id,
    discover_external_classifications,
    list_available_csvs,
    list_available_reports,
    load_external_classifications,
    merge_runtime_fields,
    resolve_csv_path,
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


def test_list_available_csvs(tmp_path: Path) -> None:
    (tmp_path / "x.csv").write_text("a,b", encoding="utf-8")
    (tmp_path / "y.csv").write_text("a,b", encoding="utf-8")
    (tmp_path / "not.csv.json").write_text("{}", encoding="utf-8")
    assert list_available_csvs(tmp_path) == ["x.csv", "y.csv"]


def test_resolve_csv_path_allows_local_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "out.csv"
    csv_path.write_text("h1,h2", encoding="utf-8")
    resolved = resolve_csv_path(tmp_path, "out.csv")
    assert resolved == csv_path.resolve()


def test_load_external_classifications_missing_file_is_safe(tmp_path: Path) -> None:
    missing = tmp_path / "x_classified.json"
    data = load_external_classifications(missing)
    assert data == {}


def test_discover_external_classifications_loads_when_present(tmp_path: Path) -> None:
    diff_path = tmp_path / "sample_diff.json"
    diff_path.write_text("{}", encoding="utf-8")
    cls_path = tmp_path / "sample_classified.json"
    cls_path.write_text(
        '{\"classifications\":[{\"section_id\":\"s1\",\"final_classification\":\"slight\"}]}',
        encoding="utf-8",
    )
    mapping, source = discover_external_classifications(diff_path)
    assert mapping == {"s1": "slight"}
    assert source == cls_path


def test_merge_runtime_fields_applies_external_classifications(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "state.db")
    diffs = [{"section_id_a": "a1", "section_id_b": "b1", "status": "modified"}]
    merged = merge_runtime_fields(store, diffs, external_classifications={"b1": "significant"})
    assert merged[0]["change_classification"] == "significant"
    assert merged[0]["classification_source"] == "classified_report"
