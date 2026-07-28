"""Gemini labeling and deterministic value allocation for Feature 05."""

from __future__ import annotations

import json
import random
import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import httpx

from .domain import (
    CategoryDiscoveryResult,
    CategoryLabelingResult,
    ClusterLabelDecision,
    DiscoveryPointResult,
    ProcessingAnswerRecord,
    ProposedCategory,
    WorkbookDataset,
)
from .errors import CategoryLabelingError
from .existing_choice_assignment import (
    API_VERSION,
    INITIAL_RETRY_DELAY_SECONDS,
    MAX_ATTEMPTS,
    MAX_RETRY_DELAY_SECONDS,
    MODEL,
    RETRY_MULTIPLIER,
    TIMEOUT_MILLISECONDS,
)

MAX_LABEL_GENERATIONS = 3
_MAX_MEMBER_SAMPLE_SIZE = 50
_SAMPLE_EDGE_SIZE = 25
_REJECTION_REASONS = {
    "mixed_meanings",
    "insufficient_common_meaning",
    "unsafe_to_label",
}
_LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["label", "reject"]},
        "english_label": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "arabic_label": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "rejection_reason": {
            "anyOf": [
                {"type": "string", "enum": sorted(_REJECTION_REASONS)},
                {"type": "null"},
            ]
        },
    },
    "required": ["decision", "english_label", "arabic_label", "rejection_reason"],
    "additionalProperties": False,
}
_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_ARABIC_LETTER = re.compile(r"[\u0621-\u063A\u0641-\u064A\u0671-\u06D3]")
_ARABIC_ALLOWED = re.compile(r"^[\u0621-\u063A\u0641-\u064A\u0671-\u06D3\s-]+$")
_ENGLISH_ALLOWED = re.compile(r"^[A-Za-z0-9\s'-]+$")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_PROHIBITED_ENGLISH = {"other", "miscellaneous", "various", "unknown", "unclear"}
_PROHIBITED_ARABIC = {"اخرى", "متنوع", "متنوعة", "متنوعات", "غير معروف", "غير واضحة"}
_SENSITIVE_TERMS = {
    "respondent",
    "enumerator",
    "identifier",
    "personal id",
    "phone number",
    "national id",
    "رقم الهوية",
    "رقم الهاتف",
    "اسم المبحوث",
}


def label_discovered_clusters(
    dataset: WorkbookDataset,
    discovery: CategoryDiscoveryResult,
    *,
    api_key: str | None,
    client: Any | None = None,
    sleep: Callable[[float], None] = time.sleep,
    uniform: Callable[[float, float], float] = random.uniform,
) -> CategoryLabelingResult:
    """Label proposal-eligible clusters and allocate unique values above 100."""

    _validate_discovery(dataset, discovery)
    existing_normalized = _existing_labels(dataset)
    decisions: list[ClusterLabelDecision] = []
    accepted: list[tuple[ClusterLabelDecision, tuple[str, ...]]] = []
    owned_client = client

    try:
        for cluster in sorted(
            discovery.proposed_clusters,
            key=lambda item: (item.question_id, item.cluster_id),
        ):
            question = _question_by_id(dataset, cluster.question_id)
            sample = _sample_members(
                cluster.processing_ids,
                discovery.points,
                dataset.processing_answers,
            )
            decision = _label_cluster(
                question_id=cluster.question_id,
                question_english=question.english_text,
                question_arabic=question.arabic_text,
                choices=question.choices,
                sample=sample,
                existing_normalized=existing_normalized[cluster.question_id],
                proposed_normalized={
                    _normalize_label(label)
                    for item, _ in accepted
                    if item.question_id == cluster.question_id
                    for label in (item.english_label, item.arabic_label)
                    if label is not None
                },
                api_key=api_key,
                client=owned_client,
                sleep=sleep,
                uniform=uniform,
            )
            if owned_client is None and decision[1] is not None:
                owned_client = decision[1]
            label_decision = decision[0]
            decisions.append(
                ClusterLabelDecision(
                    cluster_id=cluster.cluster_id,
                    question_id=cluster.question_id,
                    decision=label_decision["decision"],
                    english_label=label_decision["english_label"],
                    arabic_label=label_decision["arabic_label"],
                    rejection_reason=label_decision["rejection_reason"],
                )
            )
            if label_decision["decision"] == "label":
                accepted.append((decisions[-1], cluster.processing_ids))
    finally:
        if client is None and owned_client is not None:
            close = getattr(owned_client, "close", None)
            if callable(close):
                close()

    proposed_categories = _allocate_values(dataset, accepted)
    return CategoryLabelingResult(
        decisions=tuple(decisions),
        proposed_categories=proposed_categories,
    )


def _validate_discovery(
    dataset: WorkbookDataset, discovery: CategoryDiscoveryResult
) -> None:
    processing_by_id = {item.processing_id: item for item in dataset.processing_answers}
    question_ids = {item.question_id for item in dataset.questions}
    cluster_ids: set[str] = set()
    for cluster in discovery.proposed_clusters:
        if cluster.cluster_id in cluster_ids:
            raise CategoryLabelingError(
                f"duplicate discovered cluster ID '{cluster.cluster_id}'"
            )
        cluster_ids.add(cluster.cluster_id)
        if cluster.question_id not in question_ids:
            raise CategoryLabelingError(
                f"cluster '{cluster.cluster_id}' references unknown question '{cluster.question_id}'"
            )
        if not cluster.processing_ids:
            raise CategoryLabelingError(
                f"cluster '{cluster.cluster_id}' has no members"
            )
        for processing_id in cluster.processing_ids:
            processing = processing_by_id.get(processing_id)
            if processing is None or processing.question_id != cluster.question_id:
                raise CategoryLabelingError(
                    f"cluster '{cluster.cluster_id}' has an invalid member '{processing_id}'"
                )


def _existing_labels(dataset: WorkbookDataset) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = defaultdict(set)
    for question in dataset.questions:
        for choice in question.choices:
            labels[question.question_id].add(_normalize_label(choice.label))
            labels[question.question_id].add(_normalize_label(choice.label_arabic))
    return labels


def _question_by_id(dataset: WorkbookDataset, question_id: str):
    for question in dataset.questions:
        if question.question_id == question_id:
            return question
    raise AssertionError("validated question must exist")


def _sample_members(
    processing_ids: tuple[str, ...],
    points: tuple[DiscoveryPointResult, ...],
    processing_answers: tuple[ProcessingAnswerRecord, ...],
) -> list[dict[str, object]]:
    points_by_id = {point.processing_id: point for point in points}
    text_by_processing_id = {
        item.processing_id: item.text for item in processing_answers
    }
    members: list[DiscoveryPointResult] = []
    for processing_id in processing_ids:
        point = points_by_id.get(processing_id)
        if point is None or point.membership_probability is None:
            raise CategoryLabelingError(
                f"cluster member '{processing_id}' is missing membership evidence"
            )
        members.append(point)
    if len(members) <= _MAX_MEMBER_SAMPLE_SIZE:
        selected = sorted(members, key=lambda item: item.processing_id)
    else:
        highest = sorted(
            members,
            key=lambda item: (-float(item.membership_probability), item.processing_id),
        )[:_SAMPLE_EDGE_SIZE]
        high_ids = {item.processing_id for item in highest}
        lowest = [
            item
            for item in sorted(
                members,
                key=lambda item: (
                    float(item.membership_probability),
                    item.processing_id,
                ),
            )
            if item.processing_id not in high_ids
        ][:_SAMPLE_EDGE_SIZE]
        selected = highest + lowest
        if len(selected) != _MAX_MEMBER_SAMPLE_SIZE:
            raise CategoryLabelingError(
                "large cluster sampling did not produce 50 members"
            )
    return [
        {
            "processing_id": item.processing_id,
            "text": text_by_processing_id[item.processing_id],
            "occurrence_count": item.occurrence_count,
            "membership_probability": item.membership_probability,
        }
        for item in selected
    ]


def _label_cluster(
    *,
    question_id: str,
    question_english: str,
    question_arabic: str,
    choices: tuple[Any, ...],
    sample: list[dict[str, object]],
    existing_normalized: set[str],
    proposed_normalized: set[str],
    api_key: str | None,
    client: Any | None,
    sleep: Callable[[float], None],
    uniform: Callable[[float, float], float],
) -> tuple[dict[str, str | None], Any | None]:
    corrective_reasons: list[str] = []
    owned_client = client
    for generation in range(MAX_LABEL_GENERATIONS):
        if owned_client is None:
            owned_client = _build_gemini_client(api_key)
        payload = _request_label_generation(
            owned_client,
            question_id=question_id,
            question_english=question_english,
            question_arabic=question_arabic,
            choices=choices,
            sample=sample,
            corrective_reasons=corrective_reasons,
            sleep=sleep,
            uniform=uniform,
        )
        try:
            validated = _validate_label_response(
                payload,
                existing_normalized=existing_normalized,
                proposed_normalized=proposed_normalized,
            )
        except _InvalidLabel as exc:
            corrective_reasons = exc.reasons
            continue
        return validated, owned_client
    reasons = "; ".join(corrective_reasons) or "invalid label response"
    raise CategoryLabelingError(
        f"Gemini could not produce a valid label for cluster '{question_id}' after "
        f"{MAX_LABEL_GENERATIONS} generations: {reasons}"
    )


def _build_gemini_client(api_key: str | None) -> Any:
    if api_key is None or not api_key.strip():
        raise CategoryLabelingError(
            "GEMINI_API_KEY is required to label proposed clusters"
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - dependency is installed normally.
        raise CategoryLabelingError(
            "google-genai is required for category labeling"
        ) from exc
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version=API_VERSION,
            timeout=TIMEOUT_MILLISECONDS,
        ),
    )


def _request_label_generation(
    client: Any,
    *,
    question_id: str,
    question_english: str,
    question_arabic: str,
    choices: tuple[Any, ...],
    sample: list[dict[str, object]],
    corrective_reasons: list[str],
    sleep: Callable[[float], None],
    uniform: Callable[[float, float], float],
) -> object:
    prompt = _build_prompt(
        question_id=question_id,
        question_english=question_english,
        question_arabic=question_arabic,
        choices=choices,
        sample=sample,
        corrective_reasons=corrective_reasons,
    )
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            interaction = client.interactions.create(
                model=MODEL,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": _LABEL_SCHEMA,
                },
                timeout=TIMEOUT_MILLISECONDS / 1000,
            )
            output_text = getattr(interaction, "output_text", None)
            if not isinstance(output_text, str):
                return None
            try:
                return json.loads(output_text)
            except json.JSONDecodeError:
                return None
        except Exception as exc:
            if not _is_transient_provider_error(exc) or attempt == MAX_ATTEMPTS:
                raise CategoryLabelingError(
                    "Gemini category-label request failed"
                ) from exc
            sleep(_retry_delay(attempt, uniform=uniform))
    raise AssertionError("unreachable")


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
        "accepted_cluster_members": sample,
    }
    instruction = (
        "You are labeling one proposed survey category. First decide whether the "
        "selected original-language answers have one coherent, safe common meaning. "
        "Return reject for mixed meanings, insufficient evidence, or unsafe labeling. "
        "For label, return concise 1-6 word English and Arabic labels that describe "
        "the shared meaning. Do not translate, alter, or expose respondent text, IDs, "
        "or sensitive personal details. Do not use generic categories, cluster IDs, "
        "or labels that duplicate an existing choice. English uses title capitalization; "
        "Arabic has no diacritics."
    )
    if corrective_reasons:
        instruction += (
            "\n\nThe prior result was invalid. Correct these issues: "
            + "; ".join(corrective_reasons)
        )
    return (
        instruction
        + "\n\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


class _InvalidLabel(Exception):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def _validate_label_response(
    payload: object,
    *,
    existing_normalized: set[str],
    proposed_normalized: set[str],
) -> dict[str, str | None]:
    if not isinstance(payload, dict):
        raise _InvalidLabel(["response must be a JSON object with exactly four fields"])
    expected = {"decision", "english_label", "arabic_label", "rejection_reason"}
    if set(payload) != expected:
        raise _InvalidLabel(["response must contain only the required label fields"])
    decision = payload["decision"]
    english = payload["english_label"]
    arabic = payload["arabic_label"]
    rejection = payload["rejection_reason"]
    if decision == "reject":
        if english is None and arabic is None and rejection in _REJECTION_REASONS:
            return {
                "decision": "reject",
                "english_label": None,
                "arabic_label": None,
                "rejection_reason": rejection,
            }
        raise _InvalidLabel(
            ["reject requires null labels and one allowed rejection reason"]
        )
    if decision != "label":
        raise _InvalidLabel(["decision must be label or reject"])
    if (
        not isinstance(english, str)
        or not isinstance(arabic, str)
        or rejection is not None
    ):
        raise _InvalidLabel(["label requires two strings and a null rejection reason"])
    errors = _validate_label_pair(
        english,
        arabic,
        existing_normalized=existing_normalized,
        proposed_normalized=proposed_normalized,
    )
    if errors:
        raise _InvalidLabel(errors)
    return {
        "decision": "label",
        "english_label": _collapse_whitespace(english),
        "arabic_label": _collapse_whitespace(arabic),
        "rejection_reason": None,
    }


def _validate_label_pair(
    english: str,
    arabic: str,
    *,
    existing_normalized: set[str],
    proposed_normalized: set[str],
) -> list[str]:
    errors: list[str] = []
    for language, label in (("English", english), ("Arabic", arabic)):
        collapsed = _collapse_whitespace(label)
        word_count = len(collapsed.split())
        if not 1 <= word_count <= 6:
            errors.append(f"{language} label must contain 1 to 6 words")
        if not collapsed:
            errors.append(f"{language} label must not be empty")
    normalized_english = _normalize_label(english)
    normalized_arabic = _normalize_label(arabic)
    if not _ENGLISH_ALLOWED.fullmatch(_collapse_whitespace(english)) or not re.search(
        r"[A-Za-z]", english
    ):
        errors.append(
            "English label must use Latin letters and supported punctuation only"
        )
    if (
        _ARABIC_DIACRITICS.search(arabic)
        or not _ARABIC_ALLOWED.fullmatch(_collapse_whitespace(arabic))
        or not _ARABIC_LETTER.search(arabic)
    ):
        errors.append("Arabic label must use Arabic script without diacritics")
    if (
        normalized_english in _PROHIBITED_ENGLISH
        or normalized_arabic in _PROHIBITED_ARABIC
    ):
        errors.append("labels must not use a prohibited generic category")
    if (
        normalized_english in existing_normalized
        or normalized_arabic in existing_normalized
    ):
        errors.append("labels must not duplicate an existing choice")
    if (
        normalized_english in proposed_normalized
        or normalized_arabic in proposed_normalized
    ):
        errors.append("labels must not duplicate another proposed category")
    combined = f"{normalized_english} {normalized_arabic}"
    if any(term in combined for term in _SENSITIVE_TERMS):
        errors.append("labels must not contain personal or sensitive details")
    return errors


def validate_analyst_label_pair(
    english: str,
    arabic: str,
    *,
    existing_labels: set[str],
    other_category_labels: set[str],
) -> tuple[str, str]:
    """Validate and normalize one analyst-supplied bilingual category label."""

    errors = _validate_label_pair(
        english,
        arabic,
        existing_normalized={_normalize_label(item) for item in existing_labels},
        proposed_normalized={_normalize_label(item) for item in other_category_labels},
    )
    if errors:
        raise CategoryLabelingError("; ".join(errors))
    return _collapse_whitespace(english), _collapse_whitespace(arabic)


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _ARABIC_DIACRITICS.sub("", normalized)
    normalized = _PUNCTUATION.sub(" ", normalized)
    return _collapse_whitespace(normalized)


def _allocate_values(
    dataset: WorkbookDataset,
    accepted: list[tuple[ClusterLabelDecision, tuple[str, ...]]],
) -> tuple[ProposedCategory, ...]:
    existing_locations: dict[int, list[str]] = defaultdict(list)
    for question in dataset.questions:
        for choice in question.choices:
            if choice.value > 100:
                existing_locations[choice.value].append(
                    f"{question.question_id} Code row {choice.code_row}"
                )
    duplicates = {
        value: locations
        for value, locations in existing_locations.items()
        if len(locations) > 1
    }
    if duplicates:
        details = "; ".join(
            f"{value}: {', '.join(locations)}"
            for value, locations in sorted(duplicates.items())
        )
        raise CategoryLabelingError(
            f"duplicate generated workbook value(s) already exist: {details}"
        )
    used = set(existing_locations)
    categories: list[ProposedCategory] = []
    next_value = 101
    for decision, processing_ids in accepted:
        while next_value in used:
            next_value += 1
        if decision.english_label is None or decision.arabic_label is None:
            raise AssertionError("accepted label decision must contain both labels")
        categories.append(
            ProposedCategory(
                cluster_id=decision.cluster_id,
                question_id=decision.question_id,
                proposed_value=next_value,
                english_label=decision.english_label,
                arabic_label=decision.arabic_label,
                member_processing_ids=tuple(sorted(processing_ids)),
            )
        )
        used.add(next_value)
        next_value += 1
    return tuple(categories)


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
