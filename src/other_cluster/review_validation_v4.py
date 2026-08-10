"""Strict validation for identity-free schema-version-4 review workspaces."""

from __future__ import annotations

from typing import Any

from .cluster_classification import REJECTION_REASONS
from .errors import ReviewFileError
from .label_policy import normalize_label, validate_analyst_label_pair


def validate_v4_review_file(document: dict[str, Any]) -> None:
    from .review_validation import _UUID4, _exact, _fail, _source

    _exact(
        document,
        {
            "schema_version",
            "revision",
            "analysis_run_id",
            "status",
            "created_at_utc",
            "updated_at_utc",
            "completed_at_utc",
            "source_workbook",
            "questions",
            "warnings",
        },
        "top-level",
    )
    if document["schema_version"] != 4:
        _fail("review schema version must be 4")
    if not isinstance(document["analysis_run_id"], str) or not _UUID4.fullmatch(
        document["analysis_run_id"]
    ):
        _fail("analysis_run_id must be a lowercase UUIDv4")
    if (
        isinstance(document["revision"], bool)
        or not isinstance(document["revision"], int)
        or document["revision"] < 0
    ):
        _fail("revision must be a nonnegative integer")
    if document["status"] not in {"in_review", "complete"}:
        _fail("review status must be in_review or complete")
    if document["status"] == "in_review" and document["completed_at_utc"] is not None:
        _fail("in_review file must have completed_at_utc set to null")
    for field in ("created_at_utc", "updated_at_utc"):
        if not isinstance(document[field], str) or not document[field].endswith("Z"):
            _fail(f"{field} must be a UTC timestamp")
    _source(document["source_workbook"])
    if not isinstance(document["warnings"], list) or any(
        not isinstance(item, dict) or set(item) != {"code", "message", "source_cell"}
        for item in document["warnings"]
    ):
        _fail("warnings must be warning objects")
    if not isinstance(document["questions"], list):
        _fail("questions must be an array")
    question_ids: set[str] = set()
    for question in document["questions"]:
        _validate_question(question, question_ids, document["revision"])


def _validate_question(
    question: object, question_ids: set[str], review_revision: int
) -> None:
    from .review_validation import _answers, _exact, _fail

    if not isinstance(question, dict):
        _fail("questions must contain objects")
    _exact(
        question,
        {
            "question_id",
            "question_text",
            "source_column",
            "existing_choices",
            "answers",
            "automatic_groups",
            "workspace",
        },
        "question entry",
    )
    question_id = question["question_id"]
    if (
        not isinstance(question_id, str)
        or not question_id
        or question_id in question_ids
    ):
        _fail("question IDs must be unique nonblank strings")
    question_ids.add(question_id)
    text = question["question_text"]
    if (
        not isinstance(text, dict)
        or set(text) != {"english", "arabic"}
        or any(
            not isinstance(value, str) or not value.strip() for value in text.values()
        )
    ):
        _fail(f"question '{question_id}' has invalid bilingual metadata")
    if not isinstance(question["source_column"], str) or not question["source_column"]:
        _fail(f"question '{question_id}' has invalid source_column")
    choice_values, existing_labels = _validate_choices(
        question["existing_choices"], question_id
    )
    if not isinstance(question["answers"], list):
        _fail(f"question '{question_id}' answers must be an array")
    answers = _answers(question["answers"], question_id)
    automatic_ids = _validate_automatic_groups(
        question["automatic_groups"],
        answers,
        choice_values,
        existing_labels,
        question_id,
    )
    _validate_workspace(
        question["workspace"],
        answers,
        automatic_ids,
        choice_values,
        existing_labels,
        question_id,
        review_revision,
    )


def _validate_choices(choices: object, question_id: str) -> tuple[set[int], set[str]]:
    from .review_validation import _exact, _fail

    if not isinstance(choices, list):
        _fail(f"question '{question_id}' existing_choices must be an array")
    values: set[int] = set()
    labels: set[str] = set()
    for choice in choices:
        if not isinstance(choice, dict):
            _fail(f"question '{question_id}' has invalid choice entry")
        _exact(
            choice,
            {"value", "english_label", "arabic_label", "code_row"},
            "choice entry",
        )
        if (
            isinstance(choice["value"], bool)
            or not isinstance(choice["value"], int)
            or choice["value"] in values
            or not isinstance(choice["english_label"], str)
            or not isinstance(choice["arabic_label"], str)
            or isinstance(choice["code_row"], bool)
            or not isinstance(choice["code_row"], int)
        ):
            _fail(f"question '{question_id}' has invalid existing choices")
        values.add(choice["value"])
        labels.update({choice["english_label"], choice["arabic_label"]})
    return values, labels


def _validate_automatic_groups(
    automatic_groups: object,
    answers: dict[str, dict[str, Any]],
    choices: set[int],
    existing_labels: set[str],
    question_id: str,
) -> dict[str, list[str]]:
    from .review_validation import _exact, _fail

    if not isinstance(automatic_groups, list):
        _fail(f"question '{question_id}' automatic_groups must be an array")
    result: dict[str, list[str]] = {}
    seen_members: set[str] = set()
    for group in automatic_groups:
        if not isinstance(group, dict):
            _fail(f"question '{question_id}' has invalid automatic group")
        _exact(
            group,
            {
                "group_id",
                "raw_cluster_label",
                "member_processing_ids",
                "provider_proposal",
            },
            "automatic group",
        )
        group_id = group["group_id"]
        members = group["member_processing_ids"]
        if (
            not isinstance(group_id, str)
            or not group_id
            or group_id in result
            or isinstance(group["raw_cluster_label"], bool)
            or not isinstance(group["raw_cluster_label"], int)
            or not isinstance(members, list)
            or len(members) < 2
            or members != sorted(members)
            or len(set(members)) != len(members)
            or any(
                member not in answers or member in seen_members for member in members
            )
        ):
            _fail(f"automatic group '{group_id}' has invalid membership")
        _validate_provider_proposal(
            group["provider_proposal"], group_id, choices, existing_labels
        )
        result[group_id] = members
        seen_members.update(members)
    return result


def _validate_provider_proposal(
    proposal: object,
    group_id: str,
    choices: set[int],
    existing_labels: set[str],
) -> None:
    from .review_validation import _exact, _fail

    if not isinstance(proposal, dict):
        _fail(f"automatic group '{group_id}' has an invalid provider proposal")
    _exact(
        proposal,
        {
            "decision",
            "selected_choice_value",
            "english_label",
            "arabic_label",
            "rejection_reason",
            "provider_error",
        },
        "provider proposal",
    )
    decision = proposal["decision"]
    if decision == "existing_choice":
        valid = (
            not isinstance(proposal["selected_choice_value"], bool)
            and proposal["selected_choice_value"] in choices
            and all(
                proposal[field] is None
                for field in (
                    "english_label",
                    "arabic_label",
                    "rejection_reason",
                    "provider_error",
                )
            )
        )
    elif decision == "new_category":
        valid = (
            proposal["selected_choice_value"] is None
            and isinstance(proposal["english_label"], str)
            and isinstance(proposal["arabic_label"], str)
            and proposal["rejection_reason"] is None
            and proposal["provider_error"] is None
        )
        if valid:
            try:
                validate_analyst_label_pair(
                    proposal["english_label"],
                    proposal["arabic_label"],
                    existing_labels=existing_labels,
                    other_category_labels=set(),
                )
            except Exception as exc:
                raise ReviewFileError(str(exc)) from exc
    elif decision == "reject_cluster":
        valid = (
            proposal["selected_choice_value"] is None
            and proposal["english_label"] is None
            and proposal["arabic_label"] is None
            and isinstance(proposal["rejection_reason"], str)
            and proposal["rejection_reason"] in REJECTION_REASONS
            and proposal["provider_error"] is None
        )
    elif decision == "provider_error":
        valid = (
            proposal["selected_choice_value"] is None
            and proposal["english_label"] is None
            and proposal["arabic_label"] is None
            and proposal["rejection_reason"] is None
            and isinstance(proposal["provider_error"], str)
            and bool(proposal["provider_error"].strip())
        )
    else:
        valid = False
    if not valid:
        _fail(f"automatic group '{group_id}' has an invalid provider proposal")


def _validate_workspace(
    workspace: object,
    answers: dict[str, dict[str, Any]],
    automatic_ids: dict[str, list[str]],
    choices: set[int],
    existing_labels: set[str],
    question_id: str,
    review_revision: int,
) -> None:
    from .review_validation import _exact, _fail

    if not isinstance(workspace, dict):
        _fail(f"question '{question_id}' workspace must be an object")
    _exact(
        workspace,
        {
            "active_groups",
            "needs_attention",
            "excluded_answers",
            "retired_groups",
            "history",
            "undo",
        },
        "workspace",
    )
    if not isinstance(workspace["active_groups"], list):
        _fail("active_groups must be an array")
    answer_order = {processing_id: index for index, processing_id in enumerate(answers)}
    current: set[str] = set()
    group_ids: set[str] = set()
    creation_orders: set[int] = set()
    category_labels: set[str] = set()
    for group in workspace["active_groups"]:
        if not isinstance(group, dict):
            _fail("active_groups must contain objects")
        _exact(
            group,
            {
                "group_id",
                "origin",
                "creation_order",
                "member_processing_ids",
                "decision",
                "review_state",
            },
            "active group",
        )
        group_id = group["group_id"]
        members = group["member_processing_ids"]
        order = group["creation_order"]
        if (
            not isinstance(group_id, str)
            or not group_id
            or group_id in group_ids
            or group["origin"] not in {"automatic", "reviewer"}
            or isinstance(order, bool)
            or not isinstance(order, int)
            or order < 0
            or order in creation_orders
            or not isinstance(members, list)
            or not members
            or any(
                not isinstance(member, str)
                or member not in answers
                or member in current
                for member in members
            )
            or len(set(members)) != len(members)
            or members != sorted(members, key=answer_order.__getitem__)
            or group["review_state"] not in {"needs_review", "confirmed"}
        ):
            _fail(f"active group '{group_id}' is invalid")
        if (group["origin"] == "automatic") != (group_id in automatic_ids):
            _fail(f"active group '{group_id}' has invalid origin")
        _validate_decision(
            group["decision"],
            choices,
            existing_labels,
            required=group["review_state"] == "confirmed",
            other_category_labels=category_labels,
        )
        group_ids.add(group_id)
        creation_orders.add(order)
        current.update(members)
    if [group["creation_order"] for group in workspace["active_groups"]] != sorted(
        group["creation_order"] for group in workspace["active_groups"]
    ):
        _fail("active group order must remain stable")
    for field in ("needs_attention", "excluded_answers"):
        items = workspace[field]
        if (
            not isinstance(items, list)
            or any(
                not isinstance(item, str) or item not in answers or item in current
                for item in items
            )
            or len(set(items)) != len(items)
            or items != sorted(items, key=answer_order.__getitem__)
        ):
            _fail(f"{field} has invalid answer membership")
        current.update(items)
    if current != set(answers):
        _fail(
            f"question '{question_id}' must locate every canonical answer exactly once"
        )
    retired_groups = workspace["retired_groups"]
    if not isinstance(retired_groups, list):
        _fail("retired_groups must be an array")
    for group in retired_groups:
        if not isinstance(group, dict):
            _fail("retired_groups must contain objects")
        _exact(
            group,
            {
                "group_id",
                "origin",
                "creation_order",
                "member_processing_ids",
                "decision",
                "review_state",
            },
            "retired group",
        )
        group_id = group["group_id"]
        order = group["creation_order"]
        if (
            not isinstance(group_id, str)
            or not group_id
            or group_id in group_ids
            or group["origin"] not in {"automatic", "reviewer"}
            or (group["origin"] == "automatic") != (group_id in automatic_ids)
            or isinstance(order, bool)
            or not isinstance(order, int)
            or order < 0
            or order in creation_orders
            or group["member_processing_ids"] != []
            or group["review_state"] != "needs_review"
        ):
            _fail(f"retired group '{group_id}' is invalid")
        _validate_decision(
            group["decision"],
            choices,
            existing_labels,
            required=False,
            other_category_labels=category_labels,
        )
        group_ids.add(group_id)
        creation_orders.add(order)
    if [group["creation_order"] for group in retired_groups] != sorted(
        group["creation_order"] for group in retired_groups
    ):
        _fail("retired group order must remain stable")
    if workspace["undo"] is not None:
        _fail("undo must be null before structural editing is available")
    _validate_history(
        workspace["history"],
        group_ids,
        answers,
        choices,
        existing_labels,
        review_revision,
    )


def _validate_decision(
    decision: object,
    choices: set[int],
    existing_labels: set[str],
    *,
    required: bool,
    other_category_labels: set[str] | None = None,
) -> None:
    from .review_validation import _exact, _fail

    if decision is None:
        if required:
            _fail("confirmed group requires a valid decision")
        return
    if not isinstance(decision, dict):
        _fail("invalid group decision")
    _exact(
        decision,
        {"decision", "selected_choice_value", "english_label", "arabic_label"},
        "group decision",
    )
    if decision["decision"] == "existing_choice":
        valid = (
            not isinstance(decision["selected_choice_value"], bool)
            and decision["selected_choice_value"] in choices
            and decision["english_label"] is None
            and decision["arabic_label"] is None
        )
    elif decision["decision"] == "new_category":
        valid = (
            decision["selected_choice_value"] is None
            and isinstance(decision["english_label"], str)
            and isinstance(decision["arabic_label"], str)
        )
        if valid:
            try:
                english, arabic = validate_analyst_label_pair(
                    decision["english_label"],
                    decision["arabic_label"],
                    existing_labels=existing_labels,
                    other_category_labels=other_category_labels or set(),
                )
            except Exception as exc:
                raise ReviewFileError(str(exc)) from exc
            if other_category_labels is not None:
                other_category_labels.update(
                    {normalize_label(english), normalize_label(arabic)}
                )
    else:
        valid = False
    if not valid:
        _fail("invalid group decision")


def _validate_history(
    history: object,
    group_ids: set[str],
    answers: dict[str, dict[str, Any]],
    choices: set[int],
    existing_labels: set[str],
    review_revision: int,
) -> None:
    from .review_validation import _exact, _fail

    if not isinstance(history, list):
        _fail("history must be an array")
    answer_order = {processing_id: index for index, processing_id in enumerate(answers)}
    previous = 0
    for entry in history:
        if not isinstance(entry, dict):
            _fail("history must contain objects")
        _exact(
            entry,
            {
                "operation",
                "revision",
                "timestamp_utc",
                "group_id",
                "affected_processing_ids",
                "affected_answer_count",
                "affected_response_count",
                "before",
                "after",
            },
            "history entry",
        )
        ids = entry["affected_processing_ids"]
        if (
            entry["operation"]
            not in {"apply_decision", "confirm_group", "move_answers"}
            or not isinstance(entry["revision"], int)
            or entry["revision"] <= previous
            or entry["revision"] > review_revision
            or not isinstance(entry["timestamp_utc"], str)
            or not entry["timestamp_utc"].endswith("Z")
            or (entry["group_id"] is not None and entry["group_id"] not in group_ids)
            or (
                entry["operation"] != "move_answers"
                and entry["group_id"] not in group_ids
            )
            or not isinstance(ids, list)
            or not ids
            or any(not isinstance(item, str) or item not in answers for item in ids)
            or len(set(ids)) != len(ids)
            or ids != sorted(ids, key=answer_order.__getitem__)
            or entry["affected_answer_count"] != len(ids)
            or entry["affected_response_count"]
            != sum(answers[item]["occurrence_count"] for item in ids)
        ):
            _fail("history entry is invalid")
        if entry["operation"] == "apply_decision":
            if (
                not isinstance(entry["before"], dict)
                or set(entry["before"]) != {"decision", "review_state"}
                or not isinstance(entry["after"], dict)
                or set(entry["after"]) != {"decision", "review_state"}
                or entry["before"]["review_state"] not in {"needs_review", "confirmed"}
                or entry["after"]["review_state"] != "needs_review"
            ):
                _fail("apply-decision history entry is invalid")
            _validate_decision(
                entry["before"]["decision"], choices, existing_labels, required=False
            )
            _validate_decision(
                entry["after"]["decision"], choices, existing_labels, required=True
            )
        elif entry["operation"] == "confirm_group":
            if entry["before"] != {"review_state": "needs_review"} or entry[
                "after"
            ] != {"review_state": "confirmed"}:
                _fail("confirm-group history entry is invalid")
        else:
            _validate_move_history(
                entry,
                ids,
                group_ids,
                choices,
                existing_labels,
            )
        previous = entry["revision"]


def _validate_move_history(
    entry: dict[str, Any],
    affected_ids: list[str],
    group_ids: set[str],
    choices: set[int],
    existing_labels: set[str],
) -> None:
    from .review_validation import _exact, _fail

    before = entry["before"]
    after = entry["after"]
    if not isinstance(before, dict) or not isinstance(after, dict):
        _fail("move-answers history entry is invalid")
    _exact(before, {"locations", "groups"}, "move-answers history before")
    _exact(after, {"destination", "groups"}, "move-answers history after")
    locations = before["locations"]
    if not isinstance(locations, list) or len(locations) != len(affected_ids):
        _fail("move-answers history source locations are invalid")
    location_ids = []
    for location in locations:
        if (
            isinstance(location, dict)
            and location.get("location") == "active_group"
            and location.get("group_id") not in group_ids
        ):
            _fail("move-answers history source group is invalid")
        location_ids.append(
            _validate_history_location(location, require_processing_id=True)
        )
    if location_ids != affected_ids:
        _fail("move-answers history source locations are invalid")
    destination_group_id = _validate_history_location(
        after["destination"], require_processing_id=False
    )
    if entry["group_id"] != destination_group_id:
        _fail("move-answers history destination is inconsistent")

    before_ids = _validate_history_groups(
        before["groups"],
        group_ids,
        choices,
        existing_labels,
        include_retired=False,
    )
    after_ids = _validate_history_groups(
        after["groups"],
        group_ids,
        choices,
        existing_labels,
        include_retired=True,
    )
    if not before_ids or before_ids != after_ids:
        _fail("move-answers history group states are inconsistent")


def _validate_history_location(
    location: object, *, require_processing_id: bool
) -> str | None:
    from .review_validation import _exact, _fail

    if not isinstance(location, dict):
        _fail("move-answers history location must be an object")
    prefix = {"processing_id"} if require_processing_id else set()
    processing_id = location.get("processing_id")
    if require_processing_id and not isinstance(processing_id, str):
        _fail("move-answers history processing ID is invalid")
    if location.get("location") == "active_group":
        _exact(location, prefix | {"location", "group_id"}, "history location")
        if not isinstance(location["group_id"], str):
            _fail("move-answers history group ID is invalid")
        return processing_id if require_processing_id else location["group_id"]
    _exact(location, prefix | {"location"}, "history location")
    if location.get("location") != "needs_attention":
        _fail("move-answers history location is invalid")
    return processing_id if require_processing_id else None


def _validate_history_groups(
    groups: object,
    known_group_ids: set[str],
    choices: set[int],
    existing_labels: set[str],
    *,
    include_retired: bool,
) -> set[str]:
    from .review_validation import _exact, _fail

    if not isinstance(groups, list):
        _fail("move-answers history groups must be an array")
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            _fail("move-answers history group state must be an object")
        fields = {"group_id", "decision", "review_state"}
        if include_retired:
            fields.add("retired")
        _exact(group, fields, "move-answers history group state")
        group_id = group["group_id"]
        if (
            not isinstance(group_id, str)
            or group_id not in known_group_ids
            or group_id in seen
            or group["review_state"] not in {"needs_review", "confirmed"}
            or (include_retired and not isinstance(group["retired"], bool))
        ):
            _fail("move-answers history group state is invalid")
        _validate_decision(group["decision"], choices, existing_labels, required=False)
        seen.add(group_id)
    return seen
