from __future__ import annotations

from pathlib import Path

import numpy as np

from other_cluster.category_discovery import discover_categories
from other_cluster.domain import DiscoveryPointResult
from other_cluster.embeddings import EmbeddingResult, _row_map_entries
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


def _embedding_result(dataset) -> EmbeddingResult:
    vectors = np.zeros((len(dataset.processing_answers), 4096), dtype=np.float32)
    for index in range(len(dataset.processing_answers)):
        vectors[index, index] = 1.0
    return EmbeddingResult(
        vectors=vectors,
        row_map=tuple(_row_map_entries(dataset)),
        shape=vectors.shape,
    )


def test_discovery_uses_every_canonical_answer_and_keeps_duplicate_fanout(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = create_workbook(
        tmp_path / "all answers.xlsx", answers=["a", "b", "c", "a"]
    )
    dataset = ingest_workbook(input_path)

    class FakeHDBSCAN:
        def __init__(self, **kwargs):
            assert kwargs == {
                "min_cluster_size": 3,
                "min_samples": None,
                "metric": "euclidean",
                "cluster_selection_method": "eom",
                "cluster_selection_epsilon": 0.0,
                "allow_single_cluster": False,
            }

        def fit(self, vectors):
            self.labels_ = np.array([0, 0, 0], dtype=np.int64)
            self.probabilities_ = np.array([0.9, 0.8, 0.7], dtype=float)
            assert vectors.shape[0] == 3
            return self

    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", FakeHDBSCAN)
    result = discover_categories(dataset, _embedding_result(dataset))

    assert len(dataset.processing_answers) == 3
    assert len(result.points) == 3
    assert len(result.proposed_clusters) == 1
    assert result.proposed_clusters[0].processing_ids == tuple(
        sorted(item.processing_id for item in dataset.processing_answers)
    )
    duplicate = next(item for item in dataset.processing_answers if item.text == "a")
    point = next(
        item for item in result.points if item.processing_id == duplicate.processing_id
    )
    assert point.occurrence_count == 2
    assert point.answer_ids == duplicate.answer_ids
    assert result.unresolved_processing_ids == ()


def test_discovery_is_question_scoped_and_retains_noise_and_rare_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = create_workbook(
        tmp_path / "questions.xlsx", answers=["a", "b", "c", "d"]
    )
    dataset = ingest_workbook(input_path)

    # The fixture has one question. A four-text set lets the fake cluster emit
    # one accepted three-member cluster plus one explicit noise point.
    class FakeHDBSCAN:
        def __init__(self, **kwargs):
            assert kwargs["min_cluster_size"] == 4

        def fit(self, vectors):
            self.labels_ = np.array([0, 0, 0, -1], dtype=np.int64)
            self.probabilities_ = np.array([0.9, 0.8, 0.7, 0.0], dtype=float)
            return self

    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", FakeHDBSCAN)
    result = discover_categories(dataset, _embedding_result(dataset))
    assert len(result.proposed_clusters) == 1
    assert [item.status for item in result.points] == [
        "accepted_cluster",
        "accepted_cluster",
        "accepted_cluster",
        "noise",
    ]
    assert result.unresolved_processing_ids == (
        next(
            item.processing_id
            for item in dataset.processing_answers
            if item.text == "d"
        ),
    )


def test_discovery_reduces_cluster_size_to_the_question_answer_count(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = create_workbook(
        tmp_path / "three answers.xlsx", answers=["a", "b", "c"]
    )
    dataset = ingest_workbook(input_path)

    class FakeHDBSCAN:
        def __init__(self, **kwargs):
            assert kwargs["min_cluster_size"] == 3

        def fit(self, vectors):
            self.labels_ = np.array([0, 0, 0], dtype=np.int64)
            self.probabilities_ = np.array([0.9, 0.8, 0.7], dtype=float)
            return self

    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", FakeHDBSCAN)
    result = discover_categories(dataset, _embedding_result(dataset))

    assert len(result.proposed_clusters) == 1


def test_discovery_skips_provider_computation_for_fewer_than_three_texts(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = create_workbook(tmp_path / "rare.xlsx", answers=["a", "a", "b"])
    dataset = ingest_workbook(input_path)

    def fail_hdbscan(*args, **kwargs):
        raise AssertionError("HDBSCAN must not run for a rare question")

    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", fail_hdbscan)
    result = discover_categories(dataset, _embedding_result(dataset))
    assert result.proposed_clusters == ()
    assert all(
        point.status == "rare_insufficient_distinct_texts" for point in result.points
    )
    assert len(result.unresolved_processing_ids) == 2


def test_discovery_trusts_the_internal_embedding_result(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "alignment.xlsx", answers=["a", "b", "c"])
    dataset = ingest_workbook(input_path)
    result = _embedding_result(dataset)
    reordered = EmbeddingResult(
        vectors=result.vectors,
        row_map=tuple(reversed(result.row_map)),
        shape=result.shape,
    )
    assert len(discover_categories(dataset, reordered).points) == 3
