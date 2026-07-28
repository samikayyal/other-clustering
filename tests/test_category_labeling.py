from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from other_cluster.category_labeling import (
    MAX_LABEL_GENERATIONS,
    label_discovered_clusters,
)
from other_cluster.domain import (
    CategoryDiscoveryResult,
    DiscoveredCluster,
    DiscoveryPointResult,
)
from other_cluster.errors import CategoryLabelingError
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


class FakeInteractions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.interactions = FakeInteractions(responses)


def _response(payload: object) -> SimpleNamespace:
    return SimpleNamespace(output_text=json.dumps(payload, ensure_ascii=False))


def _discovery(dataset, *, probabilities: list[float] | None = None):
    probabilities = probabilities or [0.9] * len(dataset.processing_answers)
    cluster_id = f"{dataset.questions[0].question_id}:cluster:0"
    processing_ids = tuple(item.processing_id for item in dataset.processing_answers)
    answer_ids = tuple(
        answer_id
        for item in dataset.processing_answers
        for answer_id in item.answer_ids
    )
    return CategoryDiscoveryResult(
        reductions=(),
        points=tuple(
            DiscoveryPointResult(
                processing_id=item.processing_id,
                question_id=item.question_id,
                answer_ids=item.answer_ids,
                occurrence_count=item.occurrence_count,
                raw_cluster_label=0,
                membership_probability=probabilities[index],
                status="accepted_cluster",
                cluster_id=cluster_id,
            )
            for index, item in enumerate(dataset.processing_answers)
        ),
        proposed_clusters=(
            DiscoveredCluster(
                cluster_id=cluster_id,
                question_id=dataset.questions[0].question_id,
                raw_cluster_label=0,
                processing_ids=processing_ids,
                answer_ids=answer_ids,
            ),
        ),
        unresolved_answer_ids=(),
        merge_suggestions=(),
    )


def test_labels_a_cluster_with_schema_constrained_context_and_allocates_value(
    tmp_path,
) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    )
    client = FakeClient(
        [
            _response(
                {
                    "decision": "label",
                    "english_label": "Local Origins",
                    "arabic_label": "اصول محلية",
                    "rejection_reason": None,
                }
            )
        ]
    )

    result = label_discovered_clusters(
        dataset,
        _discovery(dataset),
        api_key="secret",
        client=client,
    )

    assert result.proposed_categories[0].proposed_value == 101
    assert result.proposed_categories[0].member_processing_ids == tuple(
        item.processing_id for item in dataset.processing_answers
    )
    call = client.interactions.calls[0]
    assert call["response_format"]["schema"]["additionalProperties"] is False
    assert '"text":"a"' in call["input"]
    assert "respondent-1" not in call["input"]


def test_invalid_label_is_regenerated_with_the_validation_reason(tmp_path) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    )
    client = FakeClient(
        [
            _response(
                {
                    "decision": "label",
                    "english_label": "Lebanese",
                    "arabic_label": "لبناني",
                    "rejection_reason": None,
                }
            ),
            _response(
                {
                    "decision": "label",
                    "english_label": "Local Origins",
                    "arabic_label": "اصول محلية",
                    "rejection_reason": None,
                }
            ),
        ]
    )

    result = label_discovered_clusters(
        dataset, _discovery(dataset), api_key="secret", client=client
    )

    assert len(client.interactions.calls) == 2
    assert (
        "must not duplicate an existing choice" in client.interactions.calls[1]["input"]
    )
    assert result.proposed_categories[0].english_label == "Local Origins"


def test_schema_valid_rejection_is_preserved_without_regeneration(tmp_path) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    )
    client = FakeClient(
        [
            _response(
                {
                    "decision": "reject",
                    "english_label": None,
                    "arabic_label": None,
                    "rejection_reason": "mixed_meanings",
                }
            )
        ]
    )

    result = label_discovered_clusters(
        dataset, _discovery(dataset), api_key="secret", client=client
    )

    assert result.proposed_categories == ()
    assert result.decisions[0].rejection_reason == "mixed_meanings"
    assert len(client.interactions.calls) == 1


def test_allocation_skips_existing_workbook_values_greater_than_100(tmp_path) -> None:
    path = create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    workbook = load_workbook(path)
    workbook["Code"].append(["B5_other", 101, "Old Category", "فئة قديمة"])
    workbook.save(path)
    dataset = ingest_workbook(path)
    client = FakeClient(
        [
            _response(
                {
                    "decision": "label",
                    "english_label": "Local Origins",
                    "arabic_label": "اصول محلية",
                    "rejection_reason": None,
                }
            )
        ]
    )

    result = label_discovered_clusters(
        dataset, _discovery(dataset), api_key="secret", client=client
    )

    assert result.proposed_categories[0].proposed_value == 102


def test_large_cluster_uses_fifty_distinct_deterministic_members(tmp_path) -> None:
    answers = [f"answer {index}" for index in range(51)]
    dataset = ingest_workbook(create_workbook(tmp_path / "input.xlsx", answers=answers))
    client = FakeClient(
        [
            _response(
                {
                    "decision": "label",
                    "english_label": "Local Origins",
                    "arabic_label": "اصول محلية",
                    "rejection_reason": None,
                }
            )
        ]
    )

    label_discovered_clusters(
        dataset,
        _discovery(dataset, probabilities=[0.9] * 51),
        api_key="secret",
        client=client,
    )

    context = json.loads(client.interactions.calls[0]["input"].rsplit("\n\n", 1)[1])
    members = context["accepted_cluster_members"]
    assert len(members) == 50
    assert len({member["processing_id"] for member in members}) == 50


def test_three_invalid_generations_fail_without_a_partial_result(tmp_path) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    )
    invalid = {
        "decision": "label",
        "english_label": "Other",
        "arabic_label": "اخرى",
        "rejection_reason": None,
    }
    client = FakeClient([_response(invalid) for _ in range(MAX_LABEL_GENERATIONS)])

    with pytest.raises(CategoryLabelingError, match="could not produce a valid label"):
        label_discovered_clusters(
            dataset, _discovery(dataset), api_key="secret", client=client
        )
