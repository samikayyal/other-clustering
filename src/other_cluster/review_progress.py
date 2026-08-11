"""Current-state progress projections for schema-version-4 review workspaces."""

from __future__ import annotations

from typing import Any


def project_review_progress(document: dict[str, Any]) -> dict[str, Any]:
    """Return the derived Issue 18 progress data for every review question.

    Callers supply a review document that has already passed its persistence
    validation.  This projection deliberately has no side effects and does not
    depend on transient browser state.
    """

    questions = [_project_question(question) for question in document["questions"]]
    return {
        "complete_question_count": sum(
            question["status"] == "complete" for question in questions
        ),
        "total_question_count": len(questions),
        "questions": questions,
    }


def _project_question(question: dict[str, Any]) -> dict[str, Any]:
    workspace = question["workspace"]
    active_groups = workspace["active_groups"]
    counts_by_id = {
        answer["processing_id"]: answer["occurrence_count"]
        for answer in question["answers"]
    }
    needs_attention = _answer_counts(workspace["needs_attention"], counts_by_id)
    excluded = _answer_counts(workspace["excluded_answers"], counts_by_id)
    confirmed_group_count = sum(
        group["review_state"] == "confirmed" for group in active_groups
    )
    needs_review_group_count = len(active_groups) - confirmed_group_count
    warning_ids = _provider_warning_ids(question["automatic_groups"])
    complete = not workspace["needs_attention"] and all(
        group["review_state"] == "confirmed" for group in active_groups
    )
    return {
        "question_id": question["question_id"],
        "resolved_item_count": (
            confirmed_group_count + excluded["unique_answer_count"]
        ),
        "remaining_item_count": needs_review_group_count
        + needs_attention["unique_answer_count"],
        "total_unique_answer_count": len(question["answers"]),
        "total_response_count": sum(counts_by_id.values()),
        "confirmed_group_count": confirmed_group_count,
        "active_group_count": len(active_groups),
        "needs_review_group_count": needs_review_group_count,
        "needs_attention": needs_attention,
        "excluded": excluded,
        "status": _question_status(complete, workspace["history"]),
        "modified": _is_modified(question),
        "has_exclusions": bool(workspace["excluded_answers"]),
        "has_provider_warning": bool(warning_ids),
        "provider_warning_processing_ids": warning_ids,
    }


def _answer_counts(
    processing_ids: list[str], counts_by_id: dict[str, int]
) -> dict[str, int]:
    return {
        "unique_answer_count": len(processing_ids),
        "response_count": sum(counts_by_id[processing_id] for processing_id in processing_ids),
    }


def _provider_warning_ids(automatic_groups: list[dict[str, Any]]) -> list[str]:
    return [
        processing_id
        for group in automatic_groups
        if group["provider_proposal"]["provider_error"] is not None
        for processing_id in group["member_processing_ids"]
    ]


def _question_status(complete: bool, history: list[dict[str, Any]]) -> str:
    if complete:
        return "complete"
    if not history:
        return "not_started"
    return "in_progress"


def _is_modified(question: dict[str, Any]) -> bool:
    """Compare current coding meaning with immutable analysis provenance."""

    workspace = question["workspace"]
    if workspace["excluded_answers"] or workspace["retired_groups"]:
        return True

    automatic_groups = question["automatic_groups"]
    active_groups = workspace["active_groups"]
    automatic_by_id = {
        group["group_id"]: group for group in automatic_groups
    }
    active_by_id = {group["group_id"]: group for group in active_groups}
    if set(active_by_id) != set(automatic_by_id):
        return True

    for group_id, automatic_group in automatic_by_id.items():
        active_group = active_by_id[group_id]
        if (
            active_group["origin"] != "automatic"
            or set(active_group["member_processing_ids"])
            != set(automatic_group["member_processing_ids"])
            or active_group["decision"]
            != _proposal_decision(automatic_group["provider_proposal"])
        ):
            return True
    return False


def _proposal_decision(proposal: dict[str, Any]) -> dict[str, Any] | None:
    if proposal["decision"] not in {"existing_choice", "new_category"}:
        return None
    return {
        "decision": proposal["decision"],
        "selected_choice_value": proposal["selected_choice_value"],
        "english_label": proposal["english_label"],
        "arabic_label": proposal["arabic_label"],
    }
