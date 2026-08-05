from __future__ import annotations

from pathlib import Path

import numpy as np

from other_cluster.category_discovery import discover_categories
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


def test_discovery_uses_every_canonical_answer_and_keeps_duplicate_fanout(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = create_workbook(
        tmp_path / "all answers.xlsx", answers=["a", "b", "c", "a"]
    )
    dataset = ingest_workbook(input_path)

    def fake_cluster(features, **kwargs):
        assert features.shape[0] == 3
        return np.array([0, 0, 0]), np.ones(3)

    monkeypatch.setattr("other_cluster.category_discovery._cluster", fake_cluster)
    result = discover_categories(dataset)

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
    def fake_cluster(features, **kwargs):
        return np.array([0, 0, 0, -1]), np.array([1.0, 1.0, 1.0, 0.0])

    monkeypatch.setattr("other_cluster.category_discovery._cluster", fake_cluster)
    result = discover_categories(dataset)
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


def test_discovery_can_propose_a_two_text_cluster(tmp_path: Path, monkeypatch) -> None:
    input_path = create_workbook(
        tmp_path / "two answers.xlsx", answers=["food support", "food assistance"]
    )
    dataset = ingest_workbook(input_path)

    def fake_cluster(features, **kwargs):
        return np.array([0, 0]), np.ones(2)

    monkeypatch.setattr("other_cluster.category_discovery._cluster", fake_cluster)
    result = discover_categories(dataset)

    assert len(result.proposed_clusters) == 1
    assert len(result.proposed_clusters[0].processing_ids) == 2


def test_discovery_skips_text_representation_for_one_distinct_text(
    tmp_path: Path, monkeypatch
) -> None:
    input_path = create_workbook(tmp_path / "rare.xlsx", answers=["a", "a"])
    dataset = ingest_workbook(input_path)

    def fail_representation(*args, **kwargs):
        raise AssertionError("representation must not run for a one-text question")

    monkeypatch.setattr(
        "other_cluster.category_discovery._text_features", fail_representation
    )
    result = discover_categories(dataset)
    assert result.proposed_clusters == ()
    assert all(
        point.status == "rare_insufficient_distinct_texts" for point in result.points
    )
    assert len(result.unresolved_processing_ids) == 1


def test_discovery_is_deterministic_without_an_embedding_provider(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "alignment.xlsx", answers=["a", "b", "c"])
    dataset = ingest_workbook(input_path)
    first = discover_categories(dataset)
    second = discover_categories(dataset)
    assert first == second
