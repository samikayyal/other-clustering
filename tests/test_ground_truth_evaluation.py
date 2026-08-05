from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from openpyxl import Workbook

from other_cluster.errors import GroundTruthError
from other_cluster.ground_truth_evaluation import (
    GroundTruthGroup,
    evaluate_ground_truth_document,
    format_ground_truth_evaluation,
    materialize_ground_truth,
)


def _mapping(key: str, row: int) -> dict[str, object]:
    return {
        "answer_id": f"q1:{row}",
        "respondent_key": key,
        "sheet": "Data",
        "row": row,
        "column": 2,
        "coordinate": f"B{row}",
    }


def _answer(
    processing_id: str,
    text: str,
    mappings: list[dict[str, object]],
    cluster_id: str | None,
) -> dict[str, object]:
    return {
        "processing_id": processing_id,
        "text": text,
        "occurrence_count": len(mappings),
        "row_mappings": mappings,
        "discovery_evidence": {
            "raw_cluster_label": 0 if cluster_id else -1,
            "membership_probability": 0.9 if cluster_id else 0.0,
            "status": "accepted_cluster" if cluster_id else "noise",
            "cluster_id": cluster_id,
        },
    }


def _document(answers: list[dict[str, object]]) -> dict[str, object]:
    return {
        "questions": [
            {
                "question_id": "q1",
                "answers": answers,
            }
        ]
    }


def _ground_truth(path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    work = workbook.active
    work.title = "Work"
    work.append(["KEY", "q1", "q1_Coded", "q1_C1"])
    for row in rows:
        work.append(row)
    workbook.save(path)
    workbook.close()
    return path


def test_ground_truth_metrics_are_label_invariant_and_occurrence_weighted(
    tmp_path: Path,
) -> None:
    path = _ground_truth(
        tmp_path / "coded.xlsx",
        [
            ["k1", "alpha", "Label A", 101],
            ["k2", "beta", "Label A", 101],
            ["k3", "gamma", "Label B", 102],
            ["k4", "alpha", "Label A", 101],
        ],
    )
    document = _document(
        [
            _answer("a", "alpha", [_mapping("k1", 2), _mapping("k4", 5)], "c1"),
            _answer("b", "beta", [_mapping("k2", 3)], "c1"),
            _answer("c", "gamma", [_mapping("k3", 4)], None),
        ]
    )

    result = evaluate_ground_truth_document(document, path)

    assert result.alignment.labeled_canonical_answers == 3
    assert result.alignment.labeled_occurrences == 4
    assert result.alignment.sentinel_code_occurrences == 0
    assert result.human_cluster_count == 2
    assert result.canonical.item_count == 3
    assert result.canonical.clustered_percentage == pytest.approx(200 / 3)
    assert result.canonical.adjusted_rand_index == 1.0
    assert result.canonical.pairwise_precision == 1.0
    assert result.canonical.pairwise_recall == 1.0
    assert result.canonical.pairwise_f1 == 1.0
    assert result.canonical_question_macro.question_count == 1
    assert result.canonical_question_macro.adjusted_rand_index == 1.0
    assert result.canonical_question_macro.pairwise_f1 == 1.0
    assert result.occurrences.item_count == 4
    assert result.occurrences.clustered_percentage == 75.0
    assert result.occurrences.adjusted_rand_index == 1.0
    assert result.questions[0].ground_truth_groups == (
        GroundTruthGroup("101", "Label A", ("a", "b")),
        GroundTruthGroup("102", "Label B", ("c",)),
    )
    assert "Question: q1 (2 human clusters)" in format_ground_truth_evaluation(result)


def test_sentinel_ground_truth_codes_are_excluded_from_benchmark(
    tmp_path: Path,
) -> None:
    path = _ground_truth(
        tmp_path / "sentinels.xlsx",
        [
            ["k1", "alpha", "Label A", 101],
            ["k2", "beta", "No response", -9999],
            ["k3", "gamma", "Don't know", -9998],
            ["k4", "beta", "Label B", 102],
        ],
    )
    document = _document(
        [
            _answer("a", "alpha", [_mapping("k1", 2)], None),
            _answer(
                "b",
                "beta",
                [_mapping("k2", 3), _mapping("k4", 5)],
                None,
            ),
            _answer("c", "gamma", [_mapping("k3", 4)], None),
        ]
    )

    result = evaluate_ground_truth_document(document, path)

    assert result.alignment.review_canonical_answers == 3
    assert result.alignment.review_occurrences == 4
    assert result.alignment.labeled_canonical_answers == 2
    assert result.alignment.labeled_occurrences == 2
    assert result.alignment.unlabeled_occurrences == 0
    assert result.alignment.sentinel_code_occurrences == 2
    assert result.canonical.item_count == 2
    assert result.canonical_question_macro.question_count == 1
    report = format_ground_truth_evaluation(result)
    assert "sentinel_code=2" in report
    assert "Question-macro canonical" in report


def test_conflicting_duplicate_text_codes_are_excluded_and_reported(
    tmp_path: Path,
) -> None:
    path = _ground_truth(
        tmp_path / "conflict.xlsx",
        [
            ["k1", "same", "Label A", 101],
            ["k2", "same", "Label B", 102],
        ],
    )
    document = _document(
        [
            _answer(
                "same",
                "same",
                [_mapping("k1", 2), _mapping("k2", 3)],
                "c1",
            )
        ]
    )

    result = evaluate_ground_truth_document(document, path)

    assert result.alignment.ambiguous_canonical_answers == 1
    assert result.alignment.labeled_canonical_answers == 0
    assert result.alignment.labeled_occurrences == 0
    assert result.canonical.item_count == 0


def test_work_code_must_map_to_one_human_label(tmp_path: Path) -> None:
    path = _ground_truth(
        tmp_path / "bad-labels.xlsx",
        [
            ["k1", "alpha", "Label A", 101],
            ["k2", "beta", "Different label", 101],
        ],
    )
    document = _document(
        [
            _answer("a", "alpha", [_mapping("k1", 2)], "c1"),
            _answer("b", "beta", [_mapping("k2", 3)], "c1"),
        ]
    )

    with pytest.raises(GroundTruthError, match="maps to multiple labels"):
        evaluate_ground_truth_document(document, path)


def test_alignment_reports_unlabeled_missing_and_mismatched_rows(
    tmp_path: Path,
) -> None:
    path = _ground_truth(
        tmp_path / "partial.xlsx",
        [
            ["unlabeled", "one", None, None],
            ["mismatch", "different", "Label", 101],
        ],
    )
    document = _document(
        [
            _answer("one", "one", [_mapping("unlabeled", 2)], None),
            _answer("two", "two", [_mapping("missing", 3)], None),
            _answer("three", "three", [_mapping("mismatch", 4)], None),
        ]
    )

    result = evaluate_ground_truth_document(document, path)

    assert result.alignment.unlabeled_occurrences == 1
    assert result.alignment.missing_key_occurrences == 1
    assert result.alignment.text_mismatch_occurrences == 1
    assert result.alignment.labeled_canonical_answers == 0


def test_gsheet_pointer_resolves_to_google_sheet_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pointer = tmp_path / "coded.gsheet"
    pointer.write_text(json.dumps({"doc_id": "sheet_123"}), encoding="utf-8")
    materialized = tmp_path / "downloaded.xlsx"

    @contextmanager
    def fake_materialize(source: str):
        assert source == ("https://docs.google.com/spreadsheets/d/sheet_123/edit")
        yield materialized

    monkeypatch.setattr(
        "other_cluster.ground_truth_evaluation.materialize_input",
        fake_materialize,
    )

    with materialize_ground_truth(pointer) as path:
        assert path == materialized
