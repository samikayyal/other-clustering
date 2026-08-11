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

    for question in document["questions"]:
        question_id = question["question_id"]
        workspace = question["workspace"]
        answers_by_id = {
            answer["processing_id"]: answer for answer in question["answers"]
        }
        active_groups = workspace["active_groups"]
        needs_attention_ids = workspace["needs_attention"]
        excluded_answer_ids = workspace["excluded_answers"]

        _project_completion_failures(
            question,
            active_groups,
            needs_attention_ids,
            blocking_failures,
        )
        outstanding_groups.extend(
            {
                "question_id": question_id,
                "group_id": group["group_id"],
            }
            for group in active_groups
            if group["review_state"] == "needs_review"
        )
        outstanding_answers.extend(
            _answer_record(question_id, processing_id, answers_by_id)
            for processing_id in needs_attention_ids
        )
        reviewer_created_groups.extend(
            _group_record(question_id, group, answers_by_id)
            for group in active_groups
            if group["origin"] == "reviewer"
        )
        retired_original_groups.extend(
            _group_record(question_id, group, answers_by_id)
            for group in workspace["retired_groups"]
            if group["origin"] == "automatic"
        )
        excluded_answers.extend(
            _answer_record(question_id, processing_id, answers_by_id)
            for processing_id in excluded_answer_ids
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
            question_id, workspace["history"], invalidated_group_ids
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
    question_id = question["question_id"]
    if needs_attention_ids:
        failures.append(
            _failure("needs_attention", question_id, "Needs attention is not empty")
        )
    for group in active_groups:
        group_id = group["group_id"]
        if group["review_state"] != "confirmed":
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
        member: {"location": "active_group", "group_id": group["group_id"]}
        for group in question["automatic_groups"]
        for member in group["member_processing_ids"]
    }
    current_answer_locations = {
        member: {"location": "active_group", "group_id": group["group_id"]}
        for group in active_groups
        for member in group["member_processing_ids"]
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
        current_location = current_answer_locations[processing_id]
        if (
            current_location["location"] == "excluded"
            or current_location == initial_location
        ):
            continue
        records.append(
            {
                **_answer_record(question["question_id"], processing_id, answers_by_id),
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
        "response_count": int(answers_by_id[processing_id]["occurrence_count"]),
    }


def _group_record(
    question_id: object,
    group: dict[str, Any],
    answers_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    member_ids = group["member_processing_ids"]
    return {
        "question_id": question_id,
        "group_id": group["group_id"],
        "canonical_answer_count": len(member_ids),
        "response_count": sum(
            int(answers_by_id[item]["occurrence_count"]) for item in member_ids
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
        operation = entry["operation"]
        if operation in {"confirm_group", "undo"}:
            continue
        before = entry["before"]
        if operation == "apply_decision":
            group_states = [
                {
                    "group_id": entry["group_id"],
                    "review_state": before["review_state"],
                }
            ]
        elif operation == "merge_groups":
            group_states = [before["source_group"], before["destination_group"]]
        else:
            group_states = before["groups"]
        for group_state in group_states:
            if group_state["review_state"] == "confirmed":
                result.add((question_id, group_state["group_id"]))


def _has_provider_warning(question: dict[str, Any]) -> bool:
    return any(
        group["provider_proposal"]["provider_error"]
        for group in question["automatic_groups"]
    )


def _label_cautions(question: dict[str, Any], cautions: list[dict[str, Any]]) -> None:
    candidates: list[tuple[str, str, str]] = []
    for choice in question["existing_choices"]:
        candidates.extend(
            (
                (
                    "english",
                    choice["english_label"],
                    f"existing:{choice['value']}",
                ),
                (
                    "arabic",
                    choice["arabic_label"],
                    f"existing:{choice['value']}",
                ),
            )
        )
    for group in question["workspace"]["active_groups"]:
        decision = group["decision"]
        if decision is not None and decision["decision"] == "new_category":
            candidates.extend(
                (
                    (
                        "english",
                        decision["english_label"],
                        group["group_id"],
                    ),
                    (
                        "arabic",
                        decision["arabic_label"],
                        group["group_id"],
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
                        "question_id": question["question_id"],
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
