from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from other_cluster.category_discovery import discover_categories
from other_cluster.cluster_classification import (
    MODEL,
    ClusterClassificationError,
    RequestRateLimiter,
    classify_clusters,
    sample_cluster_members,
    validate_classification_response,
)
from other_cluster.domain import (
    CategoryDiscoveryResult,
    ClusterProposal,
    DiscoveryPointResult,
)
from other_cluster.embeddings import EmbeddingResult, _row_map_entries
from other_cluster.errors import ClusterClassificationError as DomainClassificationError
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


def _embedding_result(dataset) -> EmbeddingResult:
    vectors = np.zeros((len(dataset.processing_answers), 4096), dtype=np.float32)
    for index in range(len(dataset.processing_answers)):
        vectors[index, index] = 1.0
    return EmbeddingResult(vectors, tuple(_row_map_entries(dataset)), vectors.shape)


def _discovery(dataset, monkeypatch):
    class FakeHDBSCAN:
        def __init__(self, **kwargs):
            pass

        def fit(self, vectors):
            self.labels_ = np.zeros(len(vectors), dtype=np.int64)
            self.probabilities_ = np.linspace(0.9, 0.7, len(vectors))
            return self

    monkeypatch.setattr("other_cluster.category_discovery.HDBSCAN", FakeHDBSCAN)
    return discover_categories(dataset, _embedding_result(dataset))


class FakeClient:
    def __init__(self, payloads=None, error=None):
        self.payloads = list(payloads or [])
        self.error = error
        self.calls = []
        self.interactions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        payload = self.payloads.pop(0)
        return SimpleNamespace(output_text=json.dumps(payload, ensure_ascii=False))


class CountingRateLimiter:
    def __init__(self):
        self.acquisitions = 0

    def acquire(self):
        self.acquisitions += 1


def test_rate_limiter_waits_before_the_sixteenth_request() -> None:
    now = [0.0]
    waits = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    limiter = RequestRateLimiter(clock=lambda: now[0], sleep=sleep)
    for _ in range(15):
        limiter.acquire()
    limiter.acquire()

    assert waits == [60.0]
    assert now[0] == 60.0


def test_transport_retries_each_consume_a_rate_limit_request(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "cluster.xlsx", answers=["a", "b", "c"])
    )
    discovery = _discovery(dataset, monkeypatch)
    client = FakeClient(error=TimeoutError("network timeout"))
    rate_limiter = CountingRateLimiter()

    classify_clusters(
        dataset,
        discovery,
        api_key="secret",
        client=client,
        rate_limiter=rate_limiter,
        sleep=lambda _: None,
    )

    assert rate_limiter.acquisitions == 5


def test_one_request_classifies_a_whole_cluster_as_existing_choice(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "cluster.xlsx", answers=["a", "b", "c"])
    )
    discovery = _discovery(dataset, monkeypatch)
    client = FakeClient(
        [
            {
                "decision": "existing_choice",
                "selected_choice_value": 1,
                "english_label": None,
                "arabic_label": None,
                "rejection_reason": None,
            }
        ]
    )
    result = classify_clusters(
        dataset, discovery, api_key="secret", client=client, sleep=lambda _: None
    )
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == MODEL == "gemini-3.5-flash-lite"
    assert "respondent-1" not in client.calls[0]["input"]
    prompt_context = json.loads(client.calls[0]["input"].split("\n\n", 1)[1])
    assert all(
        set(member) == {"text", "occurrence_count", "membership_probability"}
        for member in prompt_context["cluster_members"]
    )
    assert len(result.proposals) == 1
    assert result.proposals[0].decision == "existing_choice"
    assert result.proposals[0].provider_error is None


def test_valid_new_category_and_rejection_are_preserved_without_values(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "cluster.xlsx", answers=["a", "b", "c"])
    )
    discovery = _discovery(dataset, monkeypatch)
    client = FakeClient(
        [
            {
                "decision": "new_category",
                "selected_choice_value": None,
                "english_label": "New meaning",
                "arabic_label": "معنى جديد",
                "rejection_reason": None,
            }
        ]
    )
    result = classify_clusters(
        dataset, discovery, api_key="secret", client=client, sleep=lambda _: None
    )
    proposal = result.proposals[0]
    assert proposal.decision == "new_category"
    assert proposal.english_label == "New meaning"
    assert proposal.rejection_reason is None

    reject_client = FakeClient(
        [
            {
                "decision": "reject_cluster",
                "selected_choice_value": None,
                "english_label": None,
                "arabic_label": None,
                "rejection_reason": "mixed_meanings",
            }
        ]
    )
    rejected = classify_clusters(
        dataset, discovery, api_key="secret", client=reject_client, sleep=lambda _: None
    )
    assert rejected.proposals[0].decision == "reject_cluster"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "decision": "existing_choice",
            "selected_choice_value": 99,
            "english_label": None,
            "arabic_label": None,
            "rejection_reason": None,
        },
        {
            "decision": "existing_choice",
            "selected_choice_value": 1,
            "english_label": "x",
            "arabic_label": None,
            "rejection_reason": None,
        },
        {
            "decision": "new_category",
            "selected_choice_value": 1,
            "english_label": "New",
            "arabic_label": "جديد",
            "rejection_reason": None,
        },
        {
            "decision": "new_category",
            "selected_choice_value": None,
            "english_label": "New",
            "arabic_label": None,
            "rejection_reason": None,
        },
        {
            "decision": "reject_cluster",
            "selected_choice_value": None,
            "english_label": None,
            "arabic_label": None,
            "rejection_reason": None,
        },
    ],
)
def test_invalid_cross_field_responses_are_rejected(payload) -> None:
    with pytest.raises(Exception):
        validate_classification_response(
            payload,
            choice_values={1},
            existing_normalized=set(),
            proposed_normalized=set(),
        )


def test_invalid_label_uses_corrective_generation(tmp_path: Path, monkeypatch) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "cluster.xlsx", answers=["a", "b", "c"])
    )
    discovery = _discovery(dataset, monkeypatch)
    client = FakeClient(
        [
            {
                "decision": "new_category",
                "selected_choice_value": None,
                "english_label": "Other",
                "arabic_label": "أخرى",
                "rejection_reason": None,
            },
            {
                "decision": "new_category",
                "selected_choice_value": None,
                "english_label": "Fresh meaning",
                "arabic_label": "معنى واضح",
                "rejection_reason": None,
            },
        ]
    )
    result = classify_clusters(
        dataset, discovery, api_key="secret", client=client, sleep=lambda _: None
    )
    assert len(client.calls) == 2
    assert result.proposals[0].english_label == "Fresh meaning"
    assert "previous invalid result" in client.calls[1]["input"].lower()


def test_exhausted_provider_call_becomes_nonfatal_provider_error(
    tmp_path: Path, monkeypatch
) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "cluster.xlsx", answers=["a", "b", "c"])
    )
    discovery = _discovery(dataset, monkeypatch)
    client = FakeClient(error=TimeoutError("network timeout"))
    result = classify_clusters(
        dataset, discovery, api_key="secret", client=client, sleep=lambda _: None
    )
    assert len(client.calls) == 5
    assert result.proposals[0].decision == "provider_error"
    assert result.provider_error_count == 1
    assert result.warnings[0]["code"] == "gemini_cluster_provider_error"


def test_no_api_key_required_when_no_proposal_cluster(tmp_path: Path) -> None:
    dataset = ingest_workbook(
        create_workbook(tmp_path / "rare.xlsx", answers=["a", "a", "b"])
    )
    points = tuple(
        DiscoveryPointResult(
            processing_id=item.processing_id,
            question_id=item.question_id,
            answer_ids=item.answer_ids,
            occurrence_count=item.occurrence_count,
            raw_cluster_label=None,
            membership_probability=None,
            status="rare_insufficient_distinct_texts",
        )
        for item in dataset.processing_answers
    )
    result = classify_clusters(
        dataset,
        CategoryDiscoveryResult(
            points,
            (),
            tuple(item.processing_id for item in dataset.processing_answers),
        ),
        api_key=None,
    )
    assert result.proposals == ()


def test_large_cluster_sampling_uses_probability_edges_and_processing_id_ties() -> None:
    points = tuple(
        DiscoveryPointResult(
            processing_id=f"p-{index:03d}",
            question_id="q",
            answer_ids=(f"a-{index}",),
            occurrence_count=1,
            raw_cluster_label=0,
            membership_probability=0.5 if index < 55 else 0.9,
            status="accepted_cluster",
            cluster_id="q:cluster:0",
        )
        for index in range(60)
    )
    processing = tuple(
        type(
            "Processing",
            (),
            {
                "processing_id": f"p-{index:03d}",
                "text": str(index),
                "occurrence_count": 1,
            },
        )()
        for index in range(60)
    )
    sample = sample_cluster_members(
        tuple(item.processing_id for item in points),
        points=points,
        processing_answers=processing,
    )
    assert len(sample) == 50
    sampled_texts = [item["text"] for item in sample]
    assert sampled_texts[:25] == [str(index) for index in range(55, 60)] + [
        str(index) for index in range(20)
    ]
    assert sampled_texts[25:] == [str(index) for index in range(20, 45)]
