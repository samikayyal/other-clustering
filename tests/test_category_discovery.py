from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from other_cluster.category_discovery import discover_categories
from other_cluster.domain import ExistingChoiceAssignmentResult
from other_cluster.embeddings import DIMENSIONS, EmbeddingResult
from other_cluster.errors import CategoryDiscoveryError
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


def _row_map(dataset) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "row": row,
            "processing_id": item.processing_id,
            "question_id": item.question_id,
            "text": item.text,
            "answer_ids": list(item.answer_ids),
        }
        for row, item in enumerate(dataset.processing_answers)
    )


def _embeddings(dataset, vectors: np.ndarray, *, row_map=None) -> EmbeddingResult:
    return EmbeddingResult(
        vectors=vectors,
        row_map=_row_map(dataset) if row_map is None else row_map,
        shape=vectors.shape,
    )


def _unit_vectors(count: int) -> np.ndarray:
    vectors = np.zeros((count, DIMENSIONS), dtype=np.float32)
    for index in range(count):
        vectors[index, index % 8] = 1.0
    return vectors


def _unassigned(dataset) -> ExistingChoiceAssignmentResult:
    return ExistingChoiceAssignmentResult(
        verifications=(),
        assignments=(),
        unassigned_answer_ids=tuple(answer.answer_id for answer in dataset.answers),
    )


class _FakeHDBSCAN:
    responses: list[tuple[list[int], list[float]]] = []

    def __init__(self, **kwargs) -> None:
        assert kwargs == {
            "min_cluster_size": 3,
            "min_samples": None,
            "metric": "euclidean",
            "cluster_selection_method": "eom",
            "cluster_selection_epsilon": 0.0,
            "allow_single_cluster": True,
        }

    def fit(self, vectors: np.ndarray):
        labels, probabilities = self.responses.pop(0)
        assert len(labels) == len(vectors)
        return SimpleNamespace(
            labels_=np.asarray(labels, dtype=np.intp),
            probabilities_=np.asarray(probabilities, dtype=np.float64),
        )


def test_small_question_skips_pca_and_preserves_duplicate_fanout(tmp_path) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "input.xlsx", answers=["one", "one", "two"])
    )

    result = discover_categories(
        dataset,
        _embeddings(dataset, _unit_vectors(len(dataset.processing_answers))),
        _unassigned(dataset),
    )

    assert result.reductions == ()
    assert [point.status for point in result.points] == [
        "rare_insufficient_distinct_texts",
        "rare_insufficient_distinct_texts",
    ]
    assert result.points[0].occurrence_count == 2
    assert result.unresolved_answer_ids == ("B5_other:2", "B5_other:3", "B5_other:4")
    assert result.proposed_clusters == ()


def test_dense_cluster_is_proposed_without_weighting_duplicate_occurrences(
    tmp_path, monkeypatch
) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "input.xlsx", answers=["one", "one", "two", "three"])
    )
    _FakeHDBSCAN.responses = [([0, 0, 0], [1.0, 0.9, 0.8])]
    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", _FakeHDBSCAN)

    result = discover_categories(
        dataset,
        _embeddings(dataset, _unit_vectors(len(dataset.processing_answers))),
        _unassigned(dataset),
    )

    assert result.reductions[0].requested_components == 50
    assert result.reductions[0].effective_components == 2
    assert len(result.proposed_clusters) == 1
    cluster = result.proposed_clusters[0]
    assert cluster.processing_ids == tuple(
        item.processing_id for item in dataset.processing_answers
    )
    assert cluster.answer_ids == (
        "B5_other:2",
        "B5_other:3",
        "B5_other:4",
        "B5_other:5",
    )
    assert {point.status for point in result.points} == {"accepted_cluster"}
    assert result.unresolved_answer_ids == ()


def test_noise_low_probability_and_rejected_cluster_remain_unresolved(
    tmp_path, monkeypatch
) -> None:
    dataset = ingest_workbook(
        create_workbook(
            tmp_path / "input.xlsx", answers=["one", "two", "three", "four"]
        )
    )
    _FakeHDBSCAN.responses = [([-1, 0, 0, 0], [0.0, 0.4, 0.9, 0.9])]
    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", _FakeHDBSCAN)

    result = discover_categories(
        dataset,
        _embeddings(dataset, _unit_vectors(len(dataset.processing_answers))),
        _unassigned(dataset),
    )

    assert [point.status for point in result.points] == [
        "noise",
        "low_probability",
        "rejected_cluster",
        "rejected_cluster",
    ]
    assert [point.raw_cluster_label for point in result.points] == [-1, 0, 0, 0]
    assert result.proposed_clusters == ()
    assert result.unresolved_answer_ids == (
        "B5_other:2",
        "B5_other:3",
        "B5_other:4",
        "B5_other:5",
    )


def test_clusters_are_kept_strictly_within_their_question(
    tmp_path, monkeypatch
) -> None:
    input_path = create_workbook(
        tmp_path / "input.xlsx", answers=["one", "two", "three"]
    )
    workbook = __import__("openpyxl").load_workbook(input_path)
    workbook["Survey"].append(["text", "B6", "Second", "الثاني"])
    workbook["Code"].append(["B6_other", -96, "Other", "أخرى"])
    workbook["Data"].cell(row=1, column=5, value="B6_other")
    for row, answer in enumerate(["four", "five", "six"], start=2):
        workbook["Data"].cell(row=row, column=5, value=answer)
    workbook.save(input_path)
    dataset = ingest_workbook(input_path)
    _FakeHDBSCAN.responses = [([0, 0, 0], [1.0, 1.0, 1.0])] * 2
    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", _FakeHDBSCAN)

    result = discover_categories(
        dataset,
        _embeddings(dataset, _unit_vectors(len(dataset.processing_answers))),
        _unassigned(dataset),
    )

    assert [cluster.question_id for cluster in result.proposed_clusters] == [
        "B5_other",
        "B6_other",
    ]
    assert result.merge_suggestions == ()


def test_same_question_clusters_emit_original_embedding_merge_evidence(
    tmp_path, monkeypatch
) -> None:
    dataset = ingest_workbook(
        create_workbook(
            tmp_path / "input.xlsx",
            answers=["one", "two", "three", "four", "five", "six"],
        )
    )
    vectors = np.zeros((6, DIMENSIONS), dtype=np.float32)
    vectors[:3, 0] = 1.0
    vectors[3:, 0] = 0.99995
    vectors[3:, 1] = 0.0099995
    _FakeHDBSCAN.responses = [([0, 0, 0, 1, 1, 1], [1.0] * 6)]
    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", _FakeHDBSCAN)

    result = discover_categories(
        dataset, _embeddings(dataset, vectors), _unassigned(dataset)
    )

    assert len(result.proposed_clusters) == 2
    assert len(result.merge_suggestions) == 1
    suggestion = result.merge_suggestions[0]
    assert suggestion.question_id == "B5_other"
    assert suggestion.cosine_similarity > 0.99
    assert suggestion.first_cluster_id == "B5_other:cluster:0"
    assert suggestion.second_cluster_id == "B5_other:cluster:1"


def test_missing_embedding_row_map_is_rejected(tmp_path) -> None:
    dataset = ingest_workbook(create_workbook(tmp_path / "input.xlsx"))

    with pytest.raises(CategoryDiscoveryError, match="embedding row map"):
        discover_categories(
            dataset,
            _embeddings(
                dataset,
                _unit_vectors(len(dataset.processing_answers)),
                row_map=(),
            ),
            _unassigned(dataset),
        )


def test_reordered_embedding_row_map_is_rejected(tmp_path) -> None:
    dataset = ingest_workbook(create_workbook(tmp_path / "input.xlsx"))
    reversed_row_map = tuple(reversed(_row_map(dataset)))

    with pytest.raises(CategoryDiscoveryError, match="row map entry 0"):
        discover_categories(
            dataset,
            _embeddings(
                dataset,
                _unit_vectors(len(dataset.processing_answers)),
                row_map=reversed_row_map,
            ),
            _unassigned(dataset),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("processing_id", "wrong-processing-id"),
        ("answer_ids", ["wrong-answer-id"]),
    ],
)
def test_mismatched_embedding_row_map_identity_is_rejected(
    tmp_path, field: str, value: object
) -> None:
    dataset = ingest_workbook(create_workbook(tmp_path / "input.xlsx"))
    row_map = [dict(entry) for entry in _row_map(dataset)]
    row_map[0][field] = value

    with pytest.raises(CategoryDiscoveryError, match="row map entry 0"):
        discover_categories(
            dataset,
            _embeddings(
                dataset,
                _unit_vectors(len(dataset.processing_answers)),
                row_map=tuple(row_map),
            ),
            _unassigned(dataset),
        )
