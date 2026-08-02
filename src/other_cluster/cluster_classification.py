"""One-call-per-cluster Gemini classification for Cluster-First V1."""

from __future__ import annotations

import json
import random
import threading
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from typing import Any

import httpx

from .domain import (
    CategoryDiscoveryResult,
    ClusterClassificationResult,
    ClusterProposal,
    DiscoveryPointResult,
    ProcessingAnswerRecord,
    WorkbookDataset,
)
from .errors import ClusterClassificationError
from .label_policy import collapse_whitespace, normalize_label, validate_label_pair

MODEL = "gemini-3.5-flash-lite"
API_VERSION = "v1"
TIMEOUT_MILLISECONDS = 120_000
GEMINI_REQUESTS_PER_MINUTE = 15
GEMINI_RATE_WINDOW_SECONDS = 60.0
MAX_TRANSPORT_ATTEMPTS = 5
MAX_STRUCTURED_GENERATIONS = 3
INITIAL_RETRY_DELAY_SECONDS = 1.0
RETRY_MULTIPLIER = 2.0
MAX_RETRY_DELAY_SECONDS = 60.0
MAX_MEMBER_SAMPLE_SIZE = 50
SAMPLE_EDGE_SIZE = 25
REJECTION_REASONS = {
    "mixed_meanings",
    "insufficient_common_meaning",
    "unsafe_to_label",
}

# Gemini's response_json_schema accepts standard JSON Schema. The provider
# enforces field shape; local validation enforces decision-specific semantics.
CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["existing_choice", "new_category", "reject_cluster"],
        },
        "selected_choice_value": {"type": ["integer", "null"]},
        "english_label": {"type": ["string", "null"]},
        "arabic_label": {"type": ["string", "null"]},
        "rejection_reason": {
            "type": ["string", "null"],
        },
    },
    "required": [
        "decision",
        "selected_choice_value",
        "english_label",
        "arabic_label",
        "rejection_reason",
    ],
    "additionalProperties": False,
}


class _InvalidStructuredResponse(Exception):
    """A schema or local cross-field/label validation failure."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class _ProviderCallExhausted(Exception):
    """A Gemini transport call cannot produce a response after its retries."""


class RequestRateLimiter:
    """Allow at most a fixed number of requests in a rolling time window."""

    def __init__(
        self,
        *,
        max_requests: int = GEMINI_REQUESTS_PER_MINUTE,
        window_seconds: float = GEMINI_RATE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._request_times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Wait until the next request can be made under the rate limit."""

        while True:
            with self._lock:
                now = self._clock()
                while (
                    self._request_times
                    and now - self._request_times[0] >= self._window_seconds
                ):
                    self._request_times.popleft()
                if len(self._request_times) < self._max_requests:
                    self._request_times.append(now)
                    return
                wait_seconds = self._window_seconds - (now - self._request_times[0])
            self._sleep(wait_seconds)


_GEMINI_RATE_LIMITER = RequestRateLimiter()


def classify_clusters(
    dataset: WorkbookDataset,
    discovery: CategoryDiscoveryResult,
    *,
    api_key: str | None,
    client: Any | None = None,
    rate_limiter: RequestRateLimiter | None = None,
    sleep: Callable[[float], None] = time.sleep,
    uniform: Callable[[float, float], float] = random.uniform,
    progress: Callable[[str], None] | None = None,
) -> ClusterClassificationResult:
    """Classify each proposal-eligible cluster exactly once."""

    clusters = tuple(
        sorted(
            discovery.proposed_clusters,
            key=lambda item: (item.question_id, item.cluster_id),
        )
    )
    if not clusters:
        if progress is not None:
            progress("classification: no proposal-eligible clusters; Gemini skipped")
        return ClusterClassificationResult(proposals=())
    if client is None and (api_key is None or not api_key.strip()):
        raise ClusterClassificationError(
            "GEMINI_API_KEY is required when proposal-eligible clusters exist"
        )
    active_rate_limiter = rate_limiter or _GEMINI_RATE_LIMITER

    points_by_id = {point.processing_id: point for point in discovery.points}
    processing_by_id = {item.processing_id: item for item in dataset.processing_answers}
    existing_labels = _existing_labels(dataset)
    proposed_labels: dict[str, set[str]] = defaultdict(set)
    proposals: list[ClusterProposal] = []
    warnings: list[dict[str, str | None]] = []
    owned_client = client
    cluster_total = len(clusters)
    if progress is not None:
        progress(
            "classification: starting; "
            f"proposal_eligible_clusters={cluster_total}; "
            f"max_generations={MAX_STRUCTURED_GENERATIONS}; "
            f"max_transport_attempts={MAX_TRANSPORT_ATTEMPTS}"
        )
    try:
        for cluster_index, cluster in enumerate(clusters, start=1):
            if progress is not None:
                progress(
                    "classification: cluster "
                    f"{cluster_index}/{cluster_total} started; "
                    f"question='{cluster.question_id}'; "
                    f"members={len(cluster.processing_ids)}"
                )
            question = _question_by_id(dataset, cluster.question_id)
            sample = sample_cluster_members(
                cluster.processing_ids,
                points=points_by_id,
                processing_answers=processing_by_id,
            )
            corrective_reasons: list[str] = []
            final_proposal: ClusterProposal | None = None
            for generation in range(MAX_STRUCTURED_GENERATIONS):
                if progress is not None:
                    progress(
                        "classification: cluster "
                        f"{cluster_index}/{cluster_total}; "
                        f"generation={generation + 1}/{MAX_STRUCTURED_GENERATIONS}"
                    )
                if owned_client is None:
                    owned_client = _build_gemini_client(api_key)
                try:
                    payload = _request_generation(
                        owned_client,
                        question_id=question.question_id,
                        question_english=question.english_text,
                        question_arabic=question.arabic_text,
                        choices=question.choices,
                        sample=sample,
                        corrective_reasons=corrective_reasons,
                        rate_limiter=active_rate_limiter,
                        sleep=sleep,
                        uniform=uniform,
                        progress=(
                            None
                            if progress is None
                            else lambda message: progress(
                                "classification: cluster "
                                f"{cluster_index}/{cluster_total}; "
                                f"question='{question.question_id}'; "
                                f"cluster_id='{cluster.cluster_id}'; {message}"
                            )
                        ),
                    )
                except _ProviderCallExhausted as exc:
                    final_proposal = _provider_error_proposal(
                        cluster.cluster_id, question.question_id
                    )
                    warnings.append(_provider_warning(cluster.cluster_id))
                    if progress is not None:
                        progress(
                            "classification: cluster "
                            f"{cluster_index}/{cluster_total} provider error; "
                            f"error={exc}; "
                            "decision=provider_error"
                        )
                    break
                try:
                    validated = validate_classification_response(
                        payload,
                        choice_values={choice.value for choice in question.choices},
                        existing_normalized=existing_labels[question.question_id],
                        proposed_normalized=proposed_labels[question.question_id],
                    )
                except _InvalidStructuredResponse as exc:
                    corrective_reasons = exc.reasons
                    if progress is not None:
                        next_generation = generation + 2
                        next_step = (
                            f"corrective_generation={next_generation}/"
                            f"{MAX_STRUCTURED_GENERATIONS}"
                            if next_generation <= MAX_STRUCTURED_GENERATIONS
                            else "no_generations_remaining"
                        )
                        progress(
                            "classification: cluster "
                            f"{cluster_index}/{cluster_total}; "
                            f"invalid response ({'; '.join(exc.reasons)}); {next_step}"
                        )
                    if generation == MAX_STRUCTURED_GENERATIONS - 1:
                        final_proposal = _provider_error_proposal(
                            cluster.cluster_id, question.question_id
                        )
                        warnings.append(_provider_warning(cluster.cluster_id))
                    continue
                final_proposal = ClusterProposal(
                    cluster_id=cluster.cluster_id,
                    question_id=question.question_id,
                    decision=validated["decision"],
                    selected_choice_value=validated["selected_choice_value"],
                    english_label=validated["english_label"],
                    arabic_label=validated["arabic_label"],
                    rejection_reason=validated["rejection_reason"],
                )
                if final_proposal.decision == "new_category":
                    assert final_proposal.english_label is not None
                    assert final_proposal.arabic_label is not None
                    proposed_labels[question.question_id].update(
                        {
                            normalize_label(final_proposal.english_label),
                            normalize_label(final_proposal.arabic_label),
                        }
                    )
                break
            if final_proposal is None:  # pragma: no cover - defensive guard.
                raise ClusterClassificationError(
                    f"cluster '{cluster.cluster_id}' did not receive a classification"
                )
            if progress is not None:
                progress(
                    "classification: cluster "
                    f"{cluster_index}/{cluster_total} complete; "
                    f"decision={final_proposal.decision}; "
                    f"completed={cluster_index}/{cluster_total}"
                )
            proposals.append(final_proposal)
    finally:
        if client is None and owned_client is not None:
            close = getattr(owned_client, "close", None)
            if callable(close):
                close()
    result = ClusterClassificationResult(
        proposals=tuple(proposals),
        warnings=tuple(warnings),
    )
    if progress is not None:
        decision_counts = Counter(proposal.decision for proposal in result.proposals)
        decisions = ",".join(
            f"{decision}={decision_counts[decision]}"
            for decision in sorted(decision_counts)
        )
        progress(
            "classification: complete; "
            f"clusters={len(result.proposals)}; "
            f"decisions={decisions or 'none'}; "
            f"provider_errors={result.provider_error_count}; "
            f"warnings={len(result.warnings)}"
        )
    return result


def sample_cluster_members(
    processing_ids: tuple[str, ...],
    *,
    points: dict[str, DiscoveryPointResult] | tuple[DiscoveryPointResult, ...],
    processing_answers: dict[str, ProcessingAnswerRecord]
    | tuple[ProcessingAnswerRecord, ...],
) -> list[dict[str, object]]:
    """Return the deterministic all/25-high+25-low cluster sample."""

    points_by_id = (
        points
        if isinstance(points, dict)
        else {item.processing_id: item for item in points}
    )
    processing_by_id = (
        processing_answers
        if isinstance(processing_answers, dict)
        else {item.processing_id: item for item in processing_answers}
    )
    members: list[DiscoveryPointResult] = []
    for processing_id in processing_ids:
        point = points_by_id.get(processing_id)
        if point is None or point.membership_probability is None:
            raise ClusterClassificationError(
                f"cluster member '{processing_id}' is missing membership evidence"
            )
        if processing_id not in processing_by_id:
            raise ClusterClassificationError(
                f"cluster member '{processing_id}' is missing its canonical answer"
            )
        members.append(point)
    if len(members) <= MAX_MEMBER_SAMPLE_SIZE:
        selected = sorted(members, key=lambda item: item.processing_id)
    else:
        highest = sorted(
            members,
            key=lambda item: (-float(item.membership_probability), item.processing_id),
        )[:SAMPLE_EDGE_SIZE]
        highest_ids = {item.processing_id for item in highest}
        lowest = [
            item
            for item in sorted(
                members,
                key=lambda item: (
                    float(item.membership_probability),
                    item.processing_id,
                ),
            )
            if item.processing_id not in highest_ids
        ][:SAMPLE_EDGE_SIZE]
        selected = highest + lowest
        if len(selected) != MAX_MEMBER_SAMPLE_SIZE:
            raise ClusterClassificationError(
                "large cluster sampling did not produce 50 members"
            )
    return [
        {
            "text": processing_by_id[point.processing_id].text,
            "occurrence_count": processing_by_id[point.processing_id].occurrence_count,
            "membership_probability": point.membership_probability,
        }
        for point in selected
    ]


def validate_classification_response(
    payload: object,
    *,
    choice_values: set[int],
    existing_normalized: set[str],
    proposed_normalized: set[str],
) -> dict[str, str | int | None]:
    """Validate decision-specific data and normalize irrelevant response fields."""

    if not isinstance(payload, dict):
        raise _InvalidStructuredResponse(["response must be one JSON object"])
    expected = {
        "decision",
        "selected_choice_value",
        "english_label",
        "arabic_label",
        "rejection_reason",
    }
    if set(payload) != expected:
        raise _InvalidStructuredResponse(
            ["response must contain exactly the five classification fields"]
        )
    decision = payload["decision"]
    selected = payload["selected_choice_value"]
    english = payload["english_label"]
    arabic = payload["arabic_label"]
    rejection = payload["rejection_reason"]
    if decision == "existing_choice":
        if (
            isinstance(selected, bool)
            or not isinstance(selected, int)
            or selected not in choice_values
        ):
            raise _InvalidStructuredResponse(
                ["existing_choice requires one supplied choice integer"]
            )
        return {
            "decision": decision,
            "selected_choice_value": selected,
            "english_label": None,
            "arabic_label": None,
            "rejection_reason": None,
        }
    if decision == "reject_cluster":
        if not isinstance(rejection, str) or rejection not in REJECTION_REASONS:
            raise _InvalidStructuredResponse(
                ["reject_cluster requires one allowed reason"]
            )
        return {
            "decision": decision,
            "selected_choice_value": None,
            "english_label": None,
            "arabic_label": None,
            "rejection_reason": rejection,
        }
    if decision != "new_category":
        raise _InvalidStructuredResponse(
            ["decision must be existing_choice, new_category, or reject_cluster"]
        )
    if not isinstance(english, str) or not isinstance(arabic, str):
        raise _InvalidStructuredResponse(["new_category requires two labels"])
    errors = validate_label_pair(
        english,
        arabic,
        existing_normalized=existing_normalized,
        proposed_normalized=proposed_normalized,
    )
    if errors:
        raise _InvalidStructuredResponse(errors)
    return {
        "decision": decision,
        "selected_choice_value": None,
        "english_label": collapse_whitespace(english),
        "arabic_label": collapse_whitespace(arabic),
        "rejection_reason": None,
    }


def _existing_labels(dataset: WorkbookDataset) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = defaultdict(set)
    for question in dataset.questions:
        for choice in question.choices:
            labels[question.question_id].update(
                {
                    normalize_label(choice.label),
                    normalize_label(choice.label_arabic),
                }
            )
    return labels


def _question_by_id(dataset: WorkbookDataset, question_id: str):
    for question in dataset.questions:
        if question.question_id == question_id:
            return question
    raise ClusterClassificationError(f"unknown question '{question_id}'")


def _provider_error_proposal(cluster_id: str, question_id: str) -> ClusterProposal:
    return ClusterProposal(
        cluster_id=cluster_id,
        question_id=question_id,
        decision="provider_error",
        selected_choice_value=None,
        english_label=None,
        arabic_label=None,
        rejection_reason=None,
        provider_error="Gemini classification exhausted; analyst decision required",
    )


def _provider_warning(cluster_id: str) -> dict[str, str | None]:
    return {
        "code": "gemini_cluster_provider_error",
        "message": f"Gemini classification exhausted for cluster '{cluster_id}'; analyst decision is required.",
        "source_cell": None,
    }


def _build_gemini_client(api_key: str | None) -> Any:
    if api_key is None or not api_key.strip():
        raise ClusterClassificationError(
            "GEMINI_API_KEY is required when proposal-eligible clusters exist"
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - dependency is installed normally.
        raise ClusterClassificationError(
            "google-genai is required for cluster classification"
        ) from exc
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version=API_VERSION,
            timeout=TIMEOUT_MILLISECONDS,
        ),
    )


def _request_generation(
    client: Any,
    *,
    question_id: str,
    question_english: str,
    question_arabic: str,
    choices: tuple[Any, ...],
    sample: list[dict[str, object]],
    corrective_reasons: list[str],
    rate_limiter: RequestRateLimiter,
    sleep: Callable[[float], None],
    uniform: Callable[[float, float], float],
    progress: Callable[[str], None] | None = None,
) -> object:
    prompt = _build_prompt(
        question_id=question_id,
        question_english=question_english,
        question_arabic=question_arabic,
        choices=choices,
        sample=sample,
        corrective_reasons=corrective_reasons,
    )
    for attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
        if progress is not None:
            progress(
                "transport attempt "
                f"{attempt}/{MAX_TRANSPORT_ATTEMPTS}; waiting for rate limit"
            )
        rate_limiter.acquire()
        if progress is not None:
            progress(
                f"transport attempt {attempt}/{MAX_TRANSPORT_ATTEMPTS}; sending request"
            )
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": CLASSIFICATION_SCHEMA,
                },
            )
            output_text = _output_text(response)
            if progress is not None:
                progress(
                    "transport attempt "
                    f"{attempt}/{MAX_TRANSPORT_ATTEMPTS}; "
                    "response_body="
                    f"{json.dumps(output_text, ensure_ascii=False)}"
                )
            if not isinstance(output_text, str):
                return None
            try:
                return json.loads(output_text)
            except json.JSONDecodeError:
                return None
        except Exception as exc:
            error_summary = _provider_error_summary(exc)
            if progress is not None:
                progress(
                    "transport attempt "
                    f"{attempt}/{MAX_TRANSPORT_ATTEMPTS} failed; "
                    f"error={error_summary}"
                )
            if (
                not _is_transient_provider_error(exc)
                or attempt == MAX_TRANSPORT_ATTEMPTS
            ):
                raise _ProviderCallExhausted(error_summary) from exc
            retry_delay = _retry_delay(attempt, uniform=uniform)
            if progress is not None:
                progress(
                    "transport attempt "
                    f"{attempt}/{MAX_TRANSPORT_ATTEMPTS}; "
                    f"retry_in={retry_delay:.1f}s"
                )
            sleep(retry_delay)
    raise AssertionError("unreachable")


def _output_text(interaction: Any) -> str | None:
    value = getattr(interaction, "text", None)
    if isinstance(value, str):
        return value
    value = getattr(interaction, "output_text", None)
    if isinstance(value, str):
        return value
    output = getattr(interaction, "output", None)
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        for item in output:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                return text
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                return item["text"]
    return None


def _build_prompt(
    *,
    question_id: str,
    question_english: str,
    question_arabic: str,
    choices: tuple[Any, ...],
    sample: list[dict[str, object]],
    corrective_reasons: list[str],
) -> str:
    context = {
        "question_id": question_id,
        "question": {"english": question_english, "arabic": question_arabic},
        "existing_choices": [
            {
                "value": choice.value,
                "english": choice.label,
                "arabic": choice.label_arabic,
            }
            for choice in choices
        ],
        "cluster_members": sample,
    }
    instruction = (
        "Classify one fixed same-question survey answer cluster as existing_choice, "
        "new_category, or reject_cluster. Choose an existing choice only when it "
        "captures the common meaning of the entire cluster. Reject mixed, ambiguous, "
        "unsafe, or insufficiently coherent clusters. For new_category, provide one "
        "concise specific English label and one concise Arabic label, each 1-6 words. "
        "Do not use respondent keys, workbook locations, internal IDs, generic labels, "
        "or sensitive personal details. Preserve the answer language in your reasoning."
    )
    if corrective_reasons:
        instruction += "\nCorrect the previous invalid result: " + "; ".join(
            corrective_reasons
        )
    return (
        instruction
        + "\n\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


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


def _provider_error_summary(exc: Exception) -> str:
    """Return a concise, secret-free provider error description for progress logs."""

    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", None)
    if isinstance(status_code, int):
        return f"{type(exc).__name__}(status={status_code})"
    return type(exc).__name__


def _retry_delay(attempt: int, *, uniform: Callable[[float, float], float]) -> float:
    base_delay = min(
        INITIAL_RETRY_DELAY_SECONDS * (RETRY_MULTIPLIER ** (attempt - 1)),
        MAX_RETRY_DELAY_SECONDS,
    )
    return min(MAX_RETRY_DELAY_SECONDS, base_delay + uniform(0.0, base_delay))
