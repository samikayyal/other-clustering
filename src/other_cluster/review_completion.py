"""Read-only net-change and completion projections for V4 reviews."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .label_policy import normalize_label


def project_review_changes(document: dict[str, Any]) -> dict[str, Any]:
    """Project the continuously available review and completion summary."""

    blocking_failures: list[dict[str, Any]] = []
    cautions: list[dict[str, Any]] = []
    outstanding_groups: list[dict[str, Any]] = []
    outstanding_answers: list[dict[str, Any]] = []
    moved_answers: list[dict[str, Any]] = []
    reviewer_created_groups: list[dict[str, Any]] = []
    retired_original_groups: list[dict[str, Any]] = []
    excluded_answers: list[dict[str, Any]] = []
    invalidated_group_ids: set[tuple[str, str]] = set()

    for question in document.get("questions", []):
        if not isinstance(question, dict):
            continue
        question_id = question.get("question_id")
        workspace = question.get("workspace", {})
        if not isinstance(workspace, dict):
            continue
        answers_by_id = {
            answer.get("processing_id"): answer
            for answer in question.get("answers", [])
            if isinstance(answer, dict) and isinstance(answer.get("processing_id"), str)
        }
        active_groups = workspace.get("active_groups", [])
        needs_attention_ids = workspace.get("needs_attention", [])
        excluded_answer_ids = workspace.get("excluded_answers", [])

        _project_completion_failures(
            question,
            active_groups,
            needs_attention_ids,
            blocking_failures,
        )
        outstanding_groups.extend(
            {
                "question_id": question_id,
                "group_id": group.get("group_id"),
            }
            for group in active_groups
            if isinstance(group, dict) and group.get("review_state") == "needs_review"
        )
        outstanding_answers.extend(
            _answer_record(question_id, processing_id, answers_by_id)
            for processing_id in needs_attention_ids
            if isinstance(processing_id, str)
        )
        reviewer_created_groups.extend(
            _group_record(question_id, group, answers_by_id)
            for group in active_groups
            if isinstance(group, dict) and group.get("origin") == "reviewer"
        )
        retired_original_groups.extend(
            _group_record(question_id, group, answers_by_id)
            for group in workspace.get("retired_groups", [])
            if isinstance(group, dict) and group.get("origin") == "automatic"
        )
        excluded_answers.extend(
            _answer_record(question_id, processing_id, answers_by_id)
            for processing_id in excluded_answer_ids
            if isinstance(processing_id, str)
        )
        moved_answers.extend(
            _moved_answer_records(
                question,
                answers_by_id,
                active_groups,
                needs_attention_ids,
                excluded_answer_ids,
            )
        )
        _confirmation_invalidations(
            str(question_id), workspace.get("history", []), invalidated_group_ids
        )
        _label_cautions(question, cautions)
        if _has_provider_warning(question):
            cautions.append(
                {
                    "code": "provider_warning",
                    "question_id": question_id,
                    "message": "Provider warning provenance is present",
                }
            )

    invalidated_groups = [
        {"question_id": question_id, "group_id": group_id}
        for question_id, group_id in sorted(invalidated_group_ids)
    ]
    net_changes = {
        "moved_canonical_answer_count": len(moved_answers),
        "moved_response_count": sum(item["response_count"] for item in moved_answers),
        "reviewer_created_group_count": len(reviewer_created_groups),
        "retired_original_group_count": len(retired_original_groups),
        "excluded_answer_count": len(excluded_answers),
        "excluded_response_count": sum(
            item["response_count"] for item in excluded_answers
        ),
        "confirmation_invalidated_group_count": len(invalidated_groups),
        "moved_answers": moved_answers,
        "reviewer_created_groups": reviewer_created_groups,
        "retired_original_groups": retired_original_groups,
        "excluded_answers": excluded_answers,
        "confirmation_invalidated_groups": invalidated_groups,
    }
    return {
        "outstanding": {
            "needs_review_group_count": len(outstanding_groups),
            "needs_attention_answer_count": len(outstanding_answers),
            "groups": outstanding_groups,
            "needs_attention_answers": outstanding_answers,
        },
        "net_changes": net_changes,
        "blocking_failures": _deduplicate_failures(blocking_failures),
        "cautions": cautions,
        "can_complete": not blocking_failures,
    }


def _project_completion_failures(
    question: dict[str, Any],
    active_groups: list[Any],
    needs_attention_ids: list[Any],
    failures: list[dict[str, Any]],
) -> None:
    question_id = question.get("question_id")
    if needs_attention_ids:
        failures.append(
            _failure("needs_attention", question_id, "Needs attention is not empty")
        )
    for group in active_groups:
        if not isinstance(group, dict):
            continue
        group_id = group.get("group_id")
        if group.get("review_state") != "confirmed":
            failures.append(
                _failure(
                    "needs_review",
                    question_id,
                    "An active group still needs review",
                    group_id,
                )
            )


def _moved_answer_records(
    question: dict[str, Any],
    answers_by_id: dict[str, dict[str, Any]],
    active_groups: list[Any],
    needs_attention_ids: list[Any],
    excluded_answer_ids: list[Any],
) -> list[dict[str, Any]]:
    initial_answer_locations = {
        member: {"location": "active_group", "group_id": group.get("group_id")}
        for group in question.get("automatic_groups", [])
        if isinstance(group, dict)
        for member in group.get("member_processing_ids", [])
    }
    current_answer_locations = {
        member: {"location": "active_group", "group_id": group.get("group_id")}
        for group in active_groups
        if isinstance(group, dict)
        for member in group.get("member_processing_ids", [])
    }
    current_answer_locations.update(
        {member: {"location": "needs_attention"} for member in needs_attention_ids}
    )
    current_answer_locations.update(
        {member: {"location": "excluded"} for member in excluded_answer_ids}
    )
    records = []
    for processing_id in answers_by_id:
        initial_location = initial_answer_locations.get(
            processing_id, {"location": "needs_attention"}
        )
        current_location = current_answer_locations.get(processing_id)
        if (
            current_location is None
            or current_location.get("location") == "excluded"
            or current_location == initial_location
        ):
            continue
        records.append(
            {
                **_answer_record(
                    question.get("question_id"), processing_id, answers_by_id
                ),
                "from": initial_location,
                "to": current_location,
            }
        )
    return records


def _answer_record(
    question_id: object,
    processing_id: str,
    answers_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "processing_id": processing_id,
        "response_count": int(
            answers_by_id.get(processing_id, {}).get("occurrence_count", 0)
        ),
    }


def _group_record(
    question_id: object,
    group: dict[str, Any],
    answers_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    member_ids = group.get("member_processing_ids", [])
    return {
        "question_id": question_id,
        "group_id": group.get("group_id"),
        "canonical_answer_count": len(member_ids),
        "response_count": sum(
            int(answers_by_id.get(item, {}).get("occurrence_count", 0))
            for item in member_ids
        ),
    }


def _failure(
    code: str,
    question_id: object,
    message: str,
    group_id: object = None,
) -> dict[str, Any]:
    result = {"code": code, "question_id": question_id, "message": message}
    if group_id is not None:
        result["group_id"] = group_id
    return result


def _confirmation_invalidations(
    question_id: str,
    history: list[Any],
    result: set[tuple[str, str]],
) -> None:
    for entry in history:
        if not isinstance(entry, dict) or entry.get("operation") in {
            "confirm_group",
            "undo",
        }:
            continue
        before = entry.get("before")
        group_states = _history_group_states(before)
        if (
            isinstance(before, dict)
            and before.get("review_state") == "confirmed"
            and isinstance(entry.get("group_id"), str)
        ):
            group_states.append(
                {
                    "group_id": entry["group_id"],
                    "review_state": before["review_state"],
                }
            )
        for group_state in group_states:
            if group_state.get("review_state") == "confirmed" and isinstance(
                group_state.get("group_id"), str
            ):
                result.add((question_id, group_state["group_id"]))


def _history_group_states(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [state for item in value for state in _history_group_states(item)]
    if not isinstance(value, dict):
        return []
    states = [value] if {"group_id", "review_state"} <= set(value) else []
    return states + [
        state for item in value.values() for state in _history_group_states(item)
    ]


def _has_provider_warning(question: dict[str, Any]) -> bool:
    return any(
        group.get("provider_proposal", {}).get("provider_error")
        for group in question.get("automatic_groups", [])
        if isinstance(group, dict)
    )


def _label_cautions(question: dict[str, Any], cautions: list[dict[str, Any]]) -> None:
    candidates: list[tuple[str, str, str]] = []
    for choice in question.get("existing_choices", []):
        candidates.extend(
            (
                (
                    "english",
                    str(choice.get("english_label", "")),
                    f"existing:{choice.get('value')}",
                ),
                (
                    "arabic",
                    str(choice.get("arabic_label", "")),
                    f"existing:{choice.get('value')}",
                ),
            )
        )
    for group in question.get("workspace", {}).get("active_groups", []):
        decision = group.get("decision") if isinstance(group, dict) else None
        if isinstance(decision, dict) and decision.get("decision") == "new_category":
            candidates.extend(
                (
                    (
                        "english",
                        str(decision.get("english_label", "")),
                        str(group.get("group_id")),
                    ),
                    (
                        "arabic",
                        str(decision.get("arabic_label", "")),
                        str(group.get("group_id")),
                    ),
                )
            )
    for index, (language, label, owner) in enumerate(candidates):
        normalized = normalize_label(label)
        for other_language, other_label, other_owner in candidates[index + 1 :]:
            other_normalized = normalize_label(other_label)
            if (
                language != other_language
                or owner == other_owner
                or not normalized
                or normalized == other_normalized
            ):
                continue
            score = SequenceMatcher(None, normalized, other_normalized).ratio()
            if score >= 0.85:
                cautions.append(
                    {
                        "code": "similar_label",
                        "question_id": question.get("question_id"),
                        "language": language,
                        "labels": [label, other_label],
                        "similarity": round(score, 6),
                        "message": "Similar but non-identical category labels",
                    }
                )


def _deduplicate_failures(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for failure in failures:
        identity = (
            failure.get("code"),
            failure.get("question_id"),
            failure.get("group_id"),
        )
        if identity not in seen:
            seen.add(identity)
            result.append(failure)
    return result
