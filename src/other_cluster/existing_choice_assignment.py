"""Conservative, question-scoped Gemini verification of existing choices."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import numpy as np

from .domain import (
    ChoiceRecord,
    ExistingChoiceAssignment,
    ExistingChoiceAssignmentResult,
    ExistingChoiceVerification,
    ProcessingAnswerRecord,
    WorkbookDataset,
)
from .embeddings import DIMENSIONS, EmbeddingResult
from .errors import ExistingChoiceAssignmentError

MODEL = "gemini-3.5-flash"
API_VERSION = "v1"
TIMEOUT_MILLISECONDS = 120_000
MAX_ATTEMPTS = 5
INITIAL_RETRY_DELAY_SECONDS = 1.0
RETRY_MULTIPLIER = 2.0
MAX_RETRY_DELAY_SECONDS = 60.0

_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["assign", "no_match"]},
        "selected_choice_value": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    },
    "required": ["decision", "selected_choice_value"],
    "additionalProperties": False,
}


def assign_existing_choices(
    dataset: WorkbookDataset,
    embeddings: EmbeddingResult,
    *,
    api_key: str | None,
    client: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
    uniform: Callable[[float, float], float] = random.uniform,
) -> ExistingChoiceAssignmentResult:
    """Verify every canonical answer only against its own question's choices.

    The embedding result is an explicit stage input and is validated for alignment,
    but Feature 03 deliberately does not use vector similarity to shortlist choices.
    """

    _validate_embedding_alignment(dataset.processing_answers, embeddings)
    choices_by_question = dataset.choices_by_question
    _validate_unique_choice_values(choices_by_question)
    questions = {question.question_id: question for question in dataset.questions}

    owned_client = client
    verifications: list[ExistingChoiceVerification] = []
    assignments: list[ExistingChoiceAssignment] = []
    unassigned_answer_ids: list[str] = []
    try:
        for processing_answer in dataset.processing_answers:
            question = questions.get(processing_answer.question_id)
            if question is None:
                raise ExistingChoiceAssignmentError(
                    "processing answer references unknown question "
                    f"'{processing_answer.question_id}'"
                )
            choices = choices_by_question[processing_answer.question_id]
            if not choices:
                verifications.append(
                    ExistingChoiceVerification(
                        processing_id=processing_answer.processing_id,
                        question_id=processing_answer.question_id,
                        status="skipped_no_choices",
                        selected_choice_value=None,
                        provider_evaluated=False,
                    )
                )
                unassigned_answer_ids.extend(processing_answer.answer_ids)
                continue

            if owned_client is None:
                owned_client = _build_gemini_client(api_key)
            decision = _request_decision(
                owned_client,
                question_english=question.english_text,
                question_arabic=question.arabic_text,
                answer_text=processing_answer.text,
                choices=choices,
                sleep=sleep,
                uniform=uniform,
            )
            selected_value = _validate_decision(
                decision,
                choices=choices,
                processing_id=processing_answer.processing_id,
            )
            if selected_value is None:
                verifications.append(
                    ExistingChoiceVerification(
                        processing_id=processing_answer.processing_id,
                        question_id=processing_answer.question_id,
                        status="no_match",
                        selected_choice_value=None,
                        provider_evaluated=True,
                    )
                )
                unassigned_answer_ids.extend(processing_answer.answer_ids)
                continue

            verifications.append(
                ExistingChoiceVerification(
                    processing_id=processing_answer.processing_id,
                    question_id=processing_answer.question_id,
                    status="assigned",
                    selected_choice_value=selected_value,
                    provider_evaluated=True,
                )
            )
            assignments.extend(
                ExistingChoiceAssignment(
                    answer_id=answer_id,
                    question_id=processing_answer.question_id,
                    choice_value=selected_value,
                )
                for answer_id in processing_answer.answer_ids
            )
    finally:
        if client is None and owned_client is not None:
            close = getattr(owned_client, "close", None)
            if callable(close):
                close()

    return ExistingChoiceAssignmentResult(
        verifications=tuple(verifications),
        assignments=tuple(assignments),
        unassigned_answer_ids=tuple(unassigned_answer_ids),
    )


def _validate_embedding_alignment(
    processing_answers: tuple[ProcessingAnswerRecord, ...], embeddings: EmbeddingResult
) -> None:
    expected_shape = (len(processing_answers), DIMENSIONS)
    if embeddings.shape != expected_shape or embeddings.vectors.shape != expected_shape:
        raise ExistingChoiceAssignmentError(
            "embedding result is not aligned with processing answers: "
            f"expected shape {expected_shape}, got {embeddings.shape}"
        )
    if embeddings.vectors.dtype != np.float32:
        raise ExistingChoiceAssignmentError("embedding result vectors must be float32")


def _validate_unique_choice_values(
    choices_by_question: Mapping[str, tuple[ChoiceRecord, ...]],
) -> None:
    for question_id, choices in choices_by_question.items():
        seen: set[int] = set()
        duplicates: set[int] = set()
        for choice in choices:
            if choice.value in seen:
                duplicates.add(choice.value)
            seen.add(choice.value)
        if duplicates:
            values = ", ".join(str(value) for value in sorted(duplicates))
            raise ExistingChoiceAssignmentError(
                f"question '{question_id}' has duplicate existing-choice value(s): {values}"
            )


def _build_gemini_client(api_key: str | None) -> Any:
    if api_key is None or not api_key.strip():
        raise ExistingChoiceAssignmentError(
            "GEMINI_API_KEY is required for questions with existing choices"
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - dependency is installed normally.
        raise ExistingChoiceAssignmentError(
            "google-genai is required for existing-choice assignment"
        ) from exc
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version=API_VERSION,
            timeout=TIMEOUT_MILLISECONDS,
        ),
    )


def _request_decision(
    client: Any,
    *,
    question_english: str,
    question_arabic: str,
    answer_text: str,
    choices: tuple[ChoiceRecord, ...],
    sleep: Callable[[float], None],
    uniform: Callable[[float, float], float],
) -> object:
    prompt = _build_prompt(
        question_english=question_english,
        question_arabic=question_arabic,
        answer_text=answer_text,
        choices=choices,
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            interaction = client.interactions.create(
                model=MODEL,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": _DECISION_SCHEMA,
                },
                timeout=TIMEOUT_MILLISECONDS / 1000,
            )
            output_text = getattr(interaction, "output_text", None)
            if not isinstance(output_text, str):
                raise ExistingChoiceAssignmentError(
                    "Gemini structured response did not contain output_text"
                )
            try:
                return json.loads(output_text)
            except json.JSONDecodeError as exc:
                raise ExistingChoiceAssignmentError(
                    "Gemini structured response was not valid JSON"
                ) from exc
        except ExistingChoiceAssignmentError:
            raise
        except Exception as exc:
            if not _is_transient_provider_error(exc) or attempt == MAX_ATTEMPTS:
                raise ExistingChoiceAssignmentError(
                    "Gemini existing-choice request failed"
                ) from exc
            sleep(_retry_delay(attempt, uniform=uniform))
    raise AssertionError("unreachable")


def _build_prompt(
    *,
    question_english: str,
    question_arabic: str,
    answer_text: str,
    choices: tuple[ChoiceRecord, ...],
) -> str:
    context = {
        "question": {"english": question_english, "arabic": question_arabic},
        "answer": answer_text,
        "allowed_existing_choices": [
            {
                "value": choice.value,
                "english": choice.label,
                "arabic": choice.label_arabic,
            }
            for choice in choices
        ],
    }
    return (
        "You are a conservative survey-coding verifier. Evaluate the exact original "
        "answer only against the supplied choices for this one question. Assign only "
        "when exactly one choice captures the answer's complete asserted meaning. "
        "Return no match for ambiguity, uncertainty, negation, partial or merely "
        "related overlap, multiple meanings not fully captured by one choice, "
        "insufficient context, or more than one plausible choice. Do not translate, "
        "invent choices, rewrite values, or create categories.\n\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


def _validate_decision(
    payload: object,
    *,
    choices: tuple[ChoiceRecord, ...],
    processing_id: str,
) -> int | None:
    if not isinstance(payload, dict):
        raise ExistingChoiceAssignmentError("Gemini decision must be a JSON object")
    expected_keys = {"decision", "selected_choice_value"}
    if set(payload) != expected_keys:
        raise ExistingChoiceAssignmentError(
            "Gemini decision must contain only decision and selected_choice_value"
        )
    decision = payload["decision"]
    selected_value = payload["selected_choice_value"]
    if decision == "no_match" and selected_value is None:
        return None
    if decision != "assign":
        raise ExistingChoiceAssignmentError(
            f"Gemini decision for '{processing_id}' has an invalid decision"
        )
    if isinstance(selected_value, bool) or not isinstance(selected_value, int):
        raise ExistingChoiceAssignmentError(
            f"Gemini assign decision for '{processing_id}' must select an integer value"
        )
    allowed_values = {choice.value for choice in choices}
    if selected_value not in allowed_values:
        raise ExistingChoiceAssignmentError(
            f"Gemini assign decision for '{processing_id}' selected unavailable "
            f"choice value {selected_value}"
        )
    return selected_value


def _is_transient_provider_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, OSError, httpx.RequestError)):
        return True
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int):
        status_code = getattr(exc, "code", None)
    return isinstance(status_code, int) and (
        status_code in {408, 429} or 500 <= status_code <= 599
    )


def _retry_delay(attempt: int, *, uniform: Callable[[float, float], float]) -> float:
    base_delay = min(
        INITIAL_RETRY_DELAY_SECONDS * (RETRY_MULTIPLIER ** (attempt - 1)),
        MAX_RETRY_DELAY_SECONDS,
    )
    return min(MAX_RETRY_DELAY_SECONDS, base_delay + uniform(0.0, base_delay))
