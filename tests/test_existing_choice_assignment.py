from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest
from openpyxl import load_workbook

from other_cluster.embeddings import DIMENSIONS, EmbeddingResult
from other_cluster.errors import ExistingChoiceAssignmentError
from other_cluster.existing_choice_assignment import (
    API_VERSION,
    MAX_ATTEMPTS,
    MODEL,
    TIMEOUT_MILLISECONDS,
    assign_existing_choices,
)
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


class FakeInteractions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.interactions = FakeInteractions(responses)


def _embeddings(dataset) -> EmbeddingResult:
    vectors = np.zeros((len(dataset.processing_answers), DIMENSIONS), dtype=np.float32)
    return EmbeddingResult(vectors=vectors, row_map=(), shape=vectors.shape)


def _response(payload: object) -> SimpleNamespace:
    return SimpleNamespace(output_text=json.dumps(payload, ensure_ascii=False))


def _assign(input_path: Path, responses: list[object]):
    dataset = ingest_workbook(input_path)
    client = FakeClient(responses)
    result = assign_existing_choices(
        dataset,
        _embeddings(dataset),
        api_key="gemini-secret",
        client=client,
        sleep=lambda _: None,
        uniform=lambda _low, _high: 0.0,
    )
    return result, client


def test_accepted_choice_is_fanned_out_to_every_duplicate_answer_row(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["لبناني", "لبناني"])

    result, client = _assign(
        input_path,
        [_response({"decision": "assign", "selected_choice_value": 1})],
    )

    assert result.assignments_by_answer_id == {"B5_other:2": 1, "B5_other:3": 1}
    assert result.unassigned_answer_ids == ()
    assert result.verifications[0].status == "assigned"
    assert result.verifications[0].provider_evaluated is True
    assert len(client.interactions.calls) == 1
    call = client.interactions.calls[0]
    assert call["model"] == MODEL
    assert call["timeout"] == TIMEOUT_MILLISECONDS / 1000
    assert call["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["assign", "no_match"]},
                "selected_choice_value": {
                    "anyOf": [{"type": "integer"}, {"type": "null"}]
                },
            },
            "required": ["decision", "selected_choice_value"],
            "additionalProperties": False,
        },
    }
    assert '"answer":"لبناني"' in call["input"]
    assert '"value":1' in call["input"]
    assert '"value":2' in call["input"]


@pytest.mark.parametrize(
    "answer",
    ["maybe Lebanese", "Lebanese and Syrian"],
    ids=["uncertain", "ambiguous"],
)
def test_rejected_and_ambiguous_answers_remain_unchanged_for_discovery(
    tmp_path: Path, answer: str
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=[answer])

    result, _ = _assign(
        input_path,
        [_response({"decision": "no_match", "selected_choice_value": None})],
    )

    assert result.assignments == ()
    assert result.unassigned_answer_ids == ("B5_other:2",)
    assert result.verifications[0].status == "no_match"


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (
            {"decision": "assign", "selected_choice_value": 999},
            "selected unavailable choice value 999",
        ),
        (
            {"decision": "no_match", "selected_choice_value": 1},
            "invalid decision",
        ),
        (
            {"decision": "assign", "selected_choice_value": None},
            "must select an integer value",
        ),
        ({"decision": "no_match"}, "must contain only"),
        (
            {
                "decision": "no_match",
                "selected_choice_value": None,
                "confidence": 1,
            },
            "must contain only",
        ),
    ],
    ids=["invented-choice", "invalid-cross-field", "null-assign", "missing", "extra"],
)
def test_invalid_or_malformed_structured_response_stops_the_stage(
    tmp_path: Path, payload: object, match: str
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    with pytest.raises(ExistingChoiceAssignmentError, match=match):
        _assign(input_path, [_response(payload)])


def test_question_boundary_uses_only_the_current_questions_choices(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["Lebanese"])
    workbook = load_workbook(input_path)
    workbook["Survey"].append(["text", "B6", "Second question", "السؤال الثاني"])
    workbook["Code"].append(["B6_other", -96, "Other", "أخرى"])
    workbook["Code"].append(["B6_other", 7, "Jordanian", "أردني"])
    workbook["Data"].cell(row=1, column=5, value="B6_other")
    workbook["Data"].cell(row=2, column=5, value="Jordanian")
    workbook.save(input_path)

    result, client = _assign(
        input_path,
        [
            _response({"decision": "no_match", "selected_choice_value": None}),
            _response({"decision": "assign", "selected_choice_value": 7}),
        ],
    )

    assert result.assignments_by_answer_id == {"B6_other:2": 7}
    first_prompt, second_prompt = (call["input"] for call in client.interactions.calls)
    assert '"value":1' in first_prompt
    assert '"value":7' not in first_prompt
    assert '"value":7' in second_prompt
    assert '"value":1' not in second_prompt


def test_no_allowed_choices_skips_gemini_and_preserves_answer_for_discovery(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    workbook = load_workbook(input_path)
    workbook["Code"].delete_rows(3, 2)
    workbook.save(input_path)
    dataset = ingest_workbook(input_path)

    result = assign_existing_choices(dataset, _embeddings(dataset), api_key=None)

    assert result.assignments == ()
    assert result.unassigned_answer_ids == ("B5_other:2",)
    assert result.verifications[0].status == "skipped_no_choices"
    assert result.verifications[0].provider_evaluated is False


def test_existing_choices_require_gemini_api_key(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    dataset = ingest_workbook(input_path)

    with pytest.raises(
        ExistingChoiceAssignmentError, match="GEMINI_API_KEY is required"
    ):
        assign_existing_choices(dataset, _embeddings(dataset), api_key=None)


def test_duplicate_choice_values_fail_before_any_gemini_request(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    workbook = load_workbook(input_path)
    workbook["Code"].append(["B5_other", 1, "Duplicate", "مكرر"])
    workbook.save(input_path)
    dataset = ingest_workbook(input_path)
    client = FakeClient([])

    with pytest.raises(
        ExistingChoiceAssignmentError, match="duplicate existing-choice"
    ):
        assign_existing_choices(
            dataset,
            _embeddings(dataset),
            api_key="gemini-secret",
            client=client,
        )

    assert client.interactions.calls == []


def test_transient_provider_error_retries_with_exponential_backoff(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    delays: list[float] = []
    dataset = ingest_workbook(input_path)
    client = FakeClient(
        [
            httpx.ConnectError("offline"),
            _response({"decision": "assign", "selected_choice_value": 1}),
        ]
    )

    result = assign_existing_choices(
        dataset,
        _embeddings(dataset),
        api_key="gemini-secret",
        client=client,
        sleep=delays.append,
        uniform=lambda _low, _high: 0.0,
    )

    assert result.assignments_by_answer_id == {"B5_other:2": 1}
    assert len(client.interactions.calls) == 2
    assert delays == [1.0]


def test_non_transient_provider_error_does_not_retry(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    dataset = ingest_workbook(input_path)
    client = FakeClient([RuntimeError("bad request")])

    with pytest.raises(ExistingChoiceAssignmentError, match="request failed"):
        assign_existing_choices(
            dataset,
            _embeddings(dataset),
            api_key="gemini-secret",
            client=client,
            sleep=lambda _: None,
            uniform=lambda _low, _high: 0.0,
        )

    assert len(client.interactions.calls) == 1
    assert MAX_ATTEMPTS == 5
    assert API_VERSION == "v1"
