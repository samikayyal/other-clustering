"""Read-only net-change and completion projections for V4 reviews."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .label_policy import normalize_label


def project_review_changes(document: dict[str, Any]) -> dict[str, Any]:
    """Project the continuously available review and completion summary."""

    failures: list[dict[str, Any]] = []
    cautions: list[dict[str, Any]] = []
    needs_review = 0
    needs_attention = 0
    moved_ids: list[tuple[dict[str, Any], str]] = []
    reviewer_groups = 0
    retired_original = 0
    excluded_ids: list[tuple[dict[str, Any], str]] = []
    invalidated: set[tuple[str, str]] = set()

    for question in document.get("questions", []):
        question_id = question.get("question_id")
        workspace = question.get("workspace", {})
        answers = {
            answer.get("processing_id"): answer
            for answer in question.get("answers", [])
            if isinstance(answer, dict)
        }
        active = workspace.get("active_groups", [])
        needs = workspace.get("needs_attention", [])
        excluded = workspace.get("excluded_answers", [])
        needs_review += sum(
            group.get("review_state") == "needs_review"
            for group in active
            if isinstance(group, dict)
        )
        needs_attention += len(needs)
        if needs:
            failures.append(
                _failure("needs_attention", question_id, "Needs attention is not empty")
            )
        for group in active:
            if not isinstance(group, dict):
                continue
            if group.get("review_state") == "needs_review":
                failures.append(
                    _failure(
                        "needs_review",
                        question_id,
                        "An active group still needs review",
                        group.get("group_id"),
                    )
                )
            if not group.get("member_processing_ids"):
                failures.append(
                    _failure(
                        "empty_group",
                        question_id,
                        "An active group is empty",
                        group.get("group_id"),
                    )
                )
            if group.get("origin") == "reviewer":
                reviewer_groups += 1
        retired_original += sum(
            group.get("origin") == "automatic"
            for group in workspace.get("retired_groups", [])
            if isinstance(group, dict)
        )
        excluded_ids.extend((answers.get(item, {}), item) for item in excluded)

        initial = {
            member: ("active_group", group.get("group_id"))
            for group in question.get("automatic_groups", [])
            if isinstance(group, dict)
            for member in group.get("member_processing_ids", [])
        }
        current = {
            member: ("active_group", group.get("group_id"))
            for group in active
            if isinstance(group, dict)
            for member in group.get("member_processing_ids", [])
        }
        current.update({member: ("needs_attention", None) for member in needs})
        current.update({member: ("excluded", None) for member in excluded})
        for processing_id, answer in answers.items():
            starting = initial.get(processing_id, ("needs_attention", None))
            if current.get(processing_id) != starting:
                moved_ids.append((answer, processing_id))

        _confirmation_invalidations(
            question_id, workspace.get("history", []), invalidated
        )
        _label_cautions(question, cautions)
        if any(
            group.get("provider_proposal", {}).get("provider_error")
            for group in question.get("automatic_groups", [])
            if isinstance(group, dict)
        ):
            cautions.append(
                {
                    "code": "provider_warning",
                    "question_id": question_id,
                    "message": "Provider warning provenance is present",
                }
            )

    return {
        "outstanding": {
            "needs_review_group_count": needs_review,
            "needs_attention_answer_count": needs_attention,
        },
        "net_changes": {
            "moved_canonical_answer_count": len(moved_ids),
            "moved_response_count": sum(
                int(answer.get("occurrence_count", 0)) for answer, _ in moved_ids
            ),
            "reviewer_created_group_count": reviewer_groups,
            "retired_original_group_count": retired_original,
            "excluded_answer_count": len(excluded_ids),
            "excluded_response_count": sum(
                int(answer.get("occurrence_count", 0)) for answer, _ in excluded_ids
            ),
            "confirmation_invalidated_group_count": len(invalidated),
        },
        "blocking_failures": failures,
        "cautions": cautions,
        "can_complete": not failures,
    }


def _failure(
    code: str, question_id: object, message: str, group_id: object = None
) -> dict[str, Any]:
    result = {"code": code, "question_id": question_id, "message": message}
    if group_id is not None:
        result["group_id"] = group_id
    return result


def _confirmation_invalidations(
    question_id: str, history: list[Any], result: set[tuple[str, str]]
) -> None:
    for entry in history:
        if not isinstance(entry, dict) or entry.get("operation") in {
            "confirm_group",
            "undo",
        }:
            continue
        before = entry.get("before", {})
        states = before.get("groups", []) if isinstance(before, dict) else []
        if isinstance(before, dict) and "review_state" in before:
            states = [
                {
                    "group_id": entry.get("group_id"),
                    "review_state": before.get("review_state"),
                }
            ]
        for state in states:
            if (
                isinstance(state, dict)
                and state.get("review_state") == "confirmed"
                and isinstance(state.get("group_id"), str)
            ):
                result.add((question_id, state["group_id"]))


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
