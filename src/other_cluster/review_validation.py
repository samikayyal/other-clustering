"""Validation and completion policy for untrusted review JSON and HTTP input."""

from __future__ import annotations

import re
from typing import Any

from .errors import ReviewFileError
from .label_policy import normalize_label, validate_analyst_label_pair

SCHEMA_VERSION = 3
IN_REVIEW, COMPLETE = "in_review", "complete"
_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {
    "rare_insufficient_distinct_texts",
    "noise",
    "low_probability",
    "rejected_small_cluster",
    "accepted_cluster",
}
_UNRESOLVED = _STATUSES - {"accepted_cluster"}
_DECISIONS = {"existing_choice", "new_category", "unresolved"}


def validate_review_file(document: object, *, require_complete: bool = False) -> None:
    """Strictly validate JSON loaded from disk or supplied through HTTP."""

    if not isinstance(document, dict):
        _fail("review file must be one JSON object")
    if document.get("schema_version") == 4:
        from .review_validation_v4 import validate_v4_review_file

        validate_v4_review_file(document)
        if require_complete and document["status"] != COMPLETE:
            _fail("review is not complete")
        return
    _validate_v3_review_file(document, require_complete=require_complete)


def _validate_v3_review_file(
    document: dict[str, Any], *, require_complete: bool = False
) -> None:
    """Validate a legacy schema-version-3 artifact for read-only viewing."""

    if document.get("schema_version") in {1, 2}:
        _fail(
            "schema versions 1 and 2 review artifacts are unsupported; run a new analysis"
        )
    _exact(
        document,
        {
            "schema_version",
            "analysis_run_id",
            "status",
            "created_at_utc",
            "updated_at_utc",
            "completed_at_utc",
            "analyst_name",
            "source_workbook",
            "questions",
            "warnings",
        },
        "top-level",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        _fail(
            f"unsupported review schema version {document['schema_version']!r}; run a new analysis"
        )
    if not isinstance(document["analysis_run_id"], str) or not _UUID4.fullmatch(
        document["analysis_run_id"]
    ):
        _fail("analysis_run_id must be a lowercase UUIDv4")
    status = document["status"]
    if status not in {IN_REVIEW, COMPLETE}:
        _fail("review status must be in_review or complete")
    for field in ("created_at_utc", "updated_at_utc"):
        if not isinstance(document[field], str) or not document[field].endswith("Z"):
            _fail(f"{field} must be a UTC timestamp")
    if document["completed_at_utc"] is not None and (
        not isinstance(document["completed_at_utc"], str)
        or not document["completed_at_utc"].endswith("Z")
    ):
        _fail("completed_at_utc must be a UTC timestamp or null")
    if document["analyst_name"] is not None and not isinstance(
        document["analyst_name"], str
    ):
        _fail("analyst_name must be a string or null")
    _source(document["source_workbook"])
    if not isinstance(document["warnings"], list) or any(
        not isinstance(item, dict) or set(item) != {"code", "message", "source_cell"}
        for item in document["warnings"]
    ):
        _fail("warnings must be warning objects")
    if not isinstance(document["questions"], list):
        _fail("questions must be an array")
    seen: set[str] = set()
    for question in document["questions"]:
        _question(question, seen, complete=status == COMPLETE)
    if status == COMPLETE:
        if (
            not isinstance(document["analyst_name"], str)
            or not document["analyst_name"].strip()
        ):
            _fail("complete review requires a nonblank analyst_name")
        if document["completed_at_utc"] is None:
            _fail("complete review requires completed_at_utc")
        _coverage(document, require_decisions=True)
    else:
        if document["completed_at_utc"] is not None:
            _fail("in_review file must have completed_at_utc set to null")
        _coverage(document, require_decisions=False)
    if require_complete and status != COMPLETE:
        _fail("review is not complete")


def validate_completion(document: dict[str, Any]) -> None:
    """Require every editable item to have a valid analyst decision."""

    validate_review_file(document)
    if (
        not isinstance(document["analyst_name"], str)
        or not document["analyst_name"].strip()
    ):
        _fail("completion requires a nonblank analyst name")
    _coverage(document, require_decisions=True)


def _source(value: object) -> None:
    if not isinstance(value, dict):
        _fail("source_workbook must be an object")
    _exact(
        value,
        {"input_kind", "source_locator", "display_name", "size_bytes", "sha256"},
        "source_workbook",
    )
    if value["input_kind"] not in {"local_xlsx", "google_sheets"} or not all(
        isinstance(value[field], str) and value[field]
        for field in ("source_locator", "display_name")
    ):
        _fail("source_workbook has invalid identity fields")
    if (
        isinstance(value["size_bytes"], bool)
        or not isinstance(value["size_bytes"], int)
        or value["size_bytes"] < 0
        or not isinstance(value["sha256"], str)
        or not _SHA256.fullmatch(value["sha256"])
    ):
        _fail("source_workbook has invalid size or sha256")


def _question(question: object, seen: set[str], *, complete: bool) -> None:
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
            "clusters",
            "unresolved_answers",
        },
        "question entry",
    )
    question_id = question["question_id"]
    if not isinstance(question_id, str) or not question_id or question_id in seen:
        _fail("question IDs must be unique nonblank strings")
    seen.add(question_id)
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
    choices = question["existing_choices"]
    if not isinstance(choices, list):
        _fail(f"question '{question_id}' existing_choices must be an array")
    values: set[int] = set()
    existing_labels: set[str] = set()
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
        ):
            _fail(
                f"question '{question_id}' existing choice values must be unique integers"
            )
        values.add(choice["value"])
        if (
            any(
                not isinstance(choice[field], str)
                for field in ("english_label", "arabic_label")
            )
            or isinstance(choice["code_row"], bool)
            or not isinstance(choice["code_row"], int)
        ):
            _fail(f"question '{question_id}' has invalid choice labels")
        existing_labels.update({choice["english_label"], choice["arabic_label"]})
    if (
        not isinstance(question["answers"], list)
        or not isinstance(question["clusters"], list)
        or not isinstance(question["unresolved_answers"], list)
    ):
        _fail(f"question '{question_id}' evidence collections must be arrays")
    answers = _answers(question["answers"], question_id)
    clustered: set[str] = set()
    cluster_ids: set[str] = set()
    category_labels: set[str] = set()
    for cluster in question["clusters"]:
        _cluster(
            cluster,
            question_id,
            answers,
            values,
            cluster_ids,
            clustered,
            existing_labels,
            category_labels,
            complete,
        )
    unresolved: set[str] = set()
    for item in question["unresolved_answers"]:
        _unresolved(
            item, question_id, answers, values, unresolved, existing_labels, complete
        )
    if clustered & unresolved or clustered | unresolved != set(answers):
        _fail(
            f"question '{question_id}' must represent every canonical answer exactly once"
        )


def _answers(items: list[object], question_id: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    ids: set[str] = set()
    for answer in items:
        if not isinstance(answer, dict):
            _fail(f"question '{question_id}' has invalid answer entry")
        _exact(
            answer,
            {
                "processing_id",
                "text",
                "occurrence_count",
                "row_mappings",
                "discovery_evidence",
            },
            "answer entry",
        )
        processing_id = answer["processing_id"]
        if (
            not isinstance(processing_id, str)
            or not processing_id
            or processing_id in result
            or not isinstance(answer["text"], str)
            or not answer["text"].strip()
        ):
            _fail(f"question '{question_id}' has duplicate/invalid processing IDs")
        rows = answer["row_mappings"]
        if (
            isinstance(answer["occurrence_count"], bool)
            or not isinstance(answer["occurrence_count"], int)
            or answer["occurrence_count"] < 1
            or not isinstance(rows, list)
            or len(rows) != answer["occurrence_count"]
        ):
            _fail(f"answer '{processing_id}' has invalid occurrence mappings")
        for row in rows:
            if not isinstance(row, dict):
                _fail(f"answer '{processing_id}' has invalid row mapping")
            _exact(
                row,
                {"answer_id", "respondent_key", "sheet", "row", "column", "coordinate"},
                "row mapping",
            )
            if (
                not isinstance(row["answer_id"], str)
                or not row["answer_id"]
                or row["answer_id"] in ids
                or row["sheet"] != "Data"
                or not isinstance(row["respondent_key"], str)
                or not row["respondent_key"]
                or any(
                    isinstance(row[field], bool)
                    or not isinstance(row[field], int)
                    or row[field] < 1
                    for field in ("row", "column")
                )
                or not isinstance(row["coordinate"], str)
                or not row["coordinate"]
            ):
                _fail(f"answer '{processing_id}' has invalid row mapping")
            ids.add(row["answer_id"])
        evidence = answer["discovery_evidence"]
        if not isinstance(evidence, dict):
            _fail(f"answer '{processing_id}' has invalid discovery evidence")
        _exact(
            evidence,
            {"raw_cluster_label", "membership_probability", "status", "cluster_id"},
            "discovery evidence",
        )
        if (
            evidence["status"] not in _STATUSES
            or evidence["raw_cluster_label"] is not None
            and (
                isinstance(evidence["raw_cluster_label"], bool)
                or not isinstance(evidence["raw_cluster_label"], int)
            )
            or evidence["membership_probability"] is not None
            and (
                isinstance(evidence["membership_probability"], bool)
                or not isinstance(evidence["membership_probability"], (int, float))
                or not 0 <= evidence["membership_probability"] <= 1
            )
        ):
            _fail(f"answer '{processing_id}' has invalid discovery evidence")
        if (
            evidence["status"] == "accepted_cluster"
            and not isinstance(evidence["cluster_id"], str)
            or evidence["status"] != "accepted_cluster"
            and evidence["cluster_id"] is not None
        ):
            _fail(f"answer '{processing_id}' has invalid cluster reference")
        result[processing_id] = answer
    return result


def _cluster(
    cluster: object,
    question_id: str,
    answers: dict[str, dict[str, Any]],
    values: set[int],
    cluster_ids: set[str],
    members: set[str],
    existing_labels: set[str],
    category_labels: set[str],
    complete: bool,
) -> None:
    if not isinstance(cluster, dict):
        _fail(f"question '{question_id}' has invalid cluster entry")
    _exact(
        cluster,
        {
            "cluster_id",
            "raw_cluster_label",
            "member_processing_ids",
            "gemini_proposal",
            "analyst_decision",
        },
        "cluster entry",
    )
    cluster_id = cluster["cluster_id"]
    ids = cluster["member_processing_ids"]
    if (
        not isinstance(cluster_id, str)
        or not cluster_id
        or cluster_id in cluster_ids
        or isinstance(cluster["raw_cluster_label"], bool)
        or not isinstance(cluster["raw_cluster_label"], int)
        or not isinstance(ids, list)
        or len(ids) < 2
        or ids != sorted(ids)
        or len(set(ids)) != len(ids)
        or any(
            not isinstance(item, str)
            or item not in answers
            or item in members
            or answers[item]["discovery_evidence"]["status"] != "accepted_cluster"
            or answers[item]["discovery_evidence"]["cluster_id"] != cluster_id
            for item in ids
        )
    ):
        _fail(f"cluster '{cluster_id}' has invalid fixed membership")
    cluster_ids.add(cluster_id)
    members.update(ids)
    _proposal(cluster["gemini_proposal"], cluster_id, values)
    _decision(
        cluster["analyst_decision"],
        values,
        allow_new=True,
        complete=complete,
        existing_labels=existing_labels,
        category_labels=category_labels,
    )


def _proposal(value: object, cluster_id: str, choices: set[int]) -> None:
    if not isinstance(value, dict):
        _fail(f"cluster '{cluster_id}' has invalid Gemini proposal")
    _exact(
        value,
        {
            "decision",
            "selected_choice_value",
            "english_label",
            "arabic_label",
            "rejection_reason",
            "provider_error",
        },
        "Gemini proposal",
    )
    if value["decision"] not in {
        "existing_choice",
        "new_category",
        "reject_cluster",
        "provider_error",
    }:
        _fail(f"cluster '{cluster_id}' has invalid Gemini proposal")
    if (
        value["decision"] == "existing_choice"
        and value["selected_choice_value"] not in choices
    ):
        _fail(f"cluster '{cluster_id}' references an unknown existing choice")


def _unresolved(
    item: object,
    question_id: str,
    answers: dict[str, dict[str, Any]],
    values: set[int],
    seen: set[str],
    existing_labels: set[str],
    complete: bool,
) -> None:
    if not isinstance(item, dict):
        _fail(f"question '{question_id}' has invalid unresolved entry")
    _exact(item, {"processing_id", "reason", "analyst_decision"}, "unresolved entry")
    processing_id = item["processing_id"]
    if (
        not isinstance(processing_id, str)
        or processing_id in seen
        or processing_id not in answers
        or item["reason"] not in _UNRESOLVED
        or answers[processing_id]["discovery_evidence"]["status"] != item["reason"]
    ):
        _fail(f"question '{question_id}' has invalid unresolved entry")
    seen.add(processing_id)
    _decision(
        item["analyst_decision"],
        values,
        allow_new=False,
        complete=complete,
        existing_labels=existing_labels,
        category_labels=set(),
    )


def _decision(
    value: object,
    choices: set[int],
    *,
    allow_new: bool,
    complete: bool,
    existing_labels: set[str],
    category_labels: set[str],
) -> None:
    if value is None:
        if complete:
            _fail("complete review requires every analyst decision")
        return
    if not isinstance(value, dict):
        _fail("invalid analyst decision")
    _exact(
        value,
        {
            "decision",
            "selected_choice_value",
            "english_label",
            "arabic_label",
            "allocated_value",
        },
        "analyst decision",
    )
    decision = value["decision"]
    if decision not in _DECISIONS or decision == "new_category" and not allow_new:
        _fail("invalid analyst decision")
    if decision == "existing_choice":
        valid = value["selected_choice_value"] in choices and all(
            value[field] is None
            for field in ("english_label", "arabic_label", "allocated_value")
        )
    elif decision == "unresolved":
        valid = all(
            value[field] is None
            for field in (
                "selected_choice_value",
                "english_label",
                "arabic_label",
                "allocated_value",
            )
        )
    else:
        valid = (
            value["selected_choice_value"] is None
            and isinstance(value["english_label"], str)
            and isinstance(value["arabic_label"], str)
            and (
                value["allocated_value"] is None
                or isinstance(value["allocated_value"], int)
            )
        )
        if valid:
            try:
                english, arabic = validate_analyst_label_pair(
                    value["english_label"],
                    value["arabic_label"],
                    existing_labels=existing_labels,
                    other_category_labels=category_labels,
                )
            except Exception as exc:
                raise ReviewFileError(str(exc)) from exc
            category_labels.update({normalize_label(english), normalize_label(arabic)})
    if not valid:
        _fail("invalid analyst decision")


def _coverage(document: dict[str, Any], *, require_decisions: bool) -> None:
    for question in document["questions"]:
        for collection in (question["clusters"], question["unresolved_answers"]):
            for item in collection:
                if require_decisions and item["analyst_decision"] is None:
                    _fail("complete review requires every analyst decision")


def _exact(value: dict[str, Any], fields: set[str], context: str) -> None:
    if set(value) != fields:
        _fail(f"{context} has an invalid schema")


def _fail(message: str) -> None:
    raise ReviewFileError(message)
