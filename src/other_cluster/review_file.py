"""Schema-version-2 authoritative review file and completion rules."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cluster_classification import normalize_label, validate_analyst_label_pair
from .domain import (
    CategoryDiscoveryResult,
    ClusterClassificationResult,
    ClusterProposal,
    ReviewFileResult,
    WorkbookDataset,
)
from .errors import ReviewFileError
from .input_sources import canonical_google_sheets_url, is_google_sheets_url

SCHEMA_VERSION = 2
IN_REVIEW = "in_review"
COMPLETE = "complete"
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DISCOVERY_STATUSES = {
    "rare_insufficient_distinct_texts",
    "noise",
    "low_probability",
    "rejected_small_cluster",
    "accepted_cluster",
}
_UNRESOLVED_REASONS = _DISCOVERY_STATUSES - {"accepted_cluster"}
_ANALYST_DECISIONS = {"existing_choice", "new_category", "unresolved"}


def write_review_file(
    dataset: WorkbookDataset,
    discovery: CategoryDiscoveryResult,
    classification: ClusterClassificationResult,
    *,
    input_source: str,
    source_path: Path,
    output_directory: Path = Path("reviews"),
    analysis_run_id: str | None = None,
    created_at_utc: datetime | None = None,
) -> ReviewFileResult:
    """Build, validate, and atomically create one in-review JSON file."""

    run_id = analysis_run_id or str(uuid.uuid4())
    _require_uuid4(run_id, "analysis_run_id")
    source = _source_identity(input_source=input_source, source_path=source_path)
    timestamp = _timestamp(created_at_utc or datetime.now(UTC), "created_at_utc")
    document = _build_document(
        dataset,
        discovery,
        classification,
        analysis_run_id=run_id,
        timestamp=timestamp,
        source=source,
    )
    validate_review_file(document)
    destination = _review_file_path(
        output_directory, str(source["display_name"]), run_id
    )
    if destination.exists():
        raise ReviewFileError(
            f"review file already exists and will not be overwritten: '{destination}'"
        )
    _atomic_json_write(destination, document, allow_overwrite=False)
    counts = {
        "question_count": len(document["questions"]),
        "canonical_answer_count": sum(
            len(question["answers"]) for question in document["questions"]
        ),
        "proposal_eligible_cluster_count": sum(
            len(question["clusters"]) for question in document["questions"]
        ),
        "unresolved_canonical_answer_count": sum(
            len(question["unresolved_answers"]) for question in document["questions"]
        ),
        "gemini_request_count": classification.request_count,
        "provider_error_cluster_count": classification.provider_error_count,
    }
    return ReviewFileResult(
        review_file_path=destination.resolve(),
        analysis_run_id=run_id,
        source_sha256=str(source["sha256"]),
        counts=counts,
    )


def load_review_file(path: str | Path) -> dict[str, Any]:
    """Read and validate a schema-version-2 review file."""

    review_path = Path(path).expanduser().resolve()
    if not review_path.exists() or not review_path.is_file():
        raise ReviewFileError(
            f"review file does not exist or is not a file: '{review_path}'"
        )
    try:
        with review_path.open("r", encoding="utf-8") as input_file:
            document = json.load(input_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewFileError(
            f"could not read review file '{review_path}': {exc}"
        ) from exc
    validate_review_file(document)
    return document


def read_review_file(path: str | Path) -> dict[str, Any]:
    """Alias used by callers that prefer an explicit read verb."""

    return load_review_file(path)


def validate_review_file(document: object, *, require_complete: bool = False) -> None:
    """Validate concrete schema, cross-references, fixed membership, and decisions."""

    if not isinstance(document, dict):
        raise ReviewFileError("review file must be one JSON object")
    if document.get("schema_version") == 1:
        raise ReviewFileError(
            "schema version 1 review artifacts are unsupported; run a new analysis"
        )
    expected_top = {
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
    }
    if set(document) != expected_top:
        raise ReviewFileError("review file has an invalid top-level schema")
    if document["schema_version"] != SCHEMA_VERSION:
        raise ReviewFileError(
            f"unsupported review schema version {document['schema_version']!r}; run a new analysis"
        )
    _require_uuid4(document["analysis_run_id"], "analysis_run_id")
    status = document["status"]
    if status not in {IN_REVIEW, COMPLETE}:
        raise ReviewFileError("review status must be in_review or complete")
    _require_timestamp(document["created_at_utc"], "created_at_utc")
    _require_timestamp(document["updated_at_utc"], "updated_at_utc")
    completed_at = document["completed_at_utc"]
    if completed_at is not None:
        _require_timestamp(completed_at, "completed_at_utc")
    if document["analyst_name"] is not None and not isinstance(
        document["analyst_name"], str
    ):
        raise ReviewFileError("analyst_name must be a string or null")
    _validate_source_identity(document["source_workbook"])
    if not isinstance(document["questions"], list):
        raise ReviewFileError("questions must be an array")
    if not isinstance(document["warnings"], list):
        raise ReviewFileError("warnings must be an array")
    for warning in document["warnings"]:
        _validate_warning(warning)

    question_ids: set[str] = set()
    for question in document["questions"]:
        _validate_question(question, question_ids, complete=status == COMPLETE)
    if require_complete and status != COMPLETE:
        raise ReviewFileError("review is not complete")
    if status == COMPLETE:
        if (
            not isinstance(document["analyst_name"], str)
            or not document["analyst_name"].strip()
        ):
            raise ReviewFileError("complete review requires a nonblank analyst_name")
        if completed_at is None:
            raise ReviewFileError("complete review requires completed_at_utc")
        _validate_complete_coverage(document)
    else:
        if completed_at is not None:
            raise ReviewFileError(
                "in_review file must have completed_at_utc set to null"
            )
        _validate_in_review_allocations(document)


def apply_review_edits(current: dict[str, Any], payload: object) -> dict[str, Any]:
    """Apply only analyst-editable fields, preserving all system evidence."""

    validate_review_file(current)
    if current["status"] == COMPLETE:
        raise ReviewFileError("completed review files are read-only")
    if not isinstance(payload, dict):
        raise ReviewFileError("review update must be one JSON object")
    if set(payload) == {
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
    }:
        payload = _full_document_edit_payload(current, payload)
    elif set(payload) - {"analyst_name", "questions"}:
        raise ReviewFileError(
            "review update may contain only analyst_name and questions"
        )
    updated = json.loads(json.dumps(current, ensure_ascii=False))
    if "analyst_name" in payload:
        name = payload["analyst_name"]
        if name is not None and not isinstance(name, str):
            raise ReviewFileError("analyst_name must be a string or null")
        updated["analyst_name"] = name
    if "questions" in payload:
        _apply_question_decisions(updated, payload["questions"])
    updated["updated_at_utc"] = _timestamp(datetime.now(UTC), "updated_at_utc")
    validate_review_file(updated)
    return updated


def _full_document_edit_payload(
    current: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Accept a full browser document only when its system evidence is unchanged."""

    if incoming.get("status") != current["status"]:
        raise ReviewFileError("review update cannot change review status")
    try:
        current_projection = _system_projection(current)
        incoming_projection = _system_projection(incoming)
    except (AttributeError, KeyError, TypeError) as exc:
        raise ReviewFileError(
            "review update full document has an invalid schema"
        ) from exc
    if current_projection != incoming_projection:
        raise ReviewFileError("review update cannot change immutable review evidence")
    return {
        "analyst_name": incoming.get("analyst_name"),
        "questions": [
            {
                "question_id": question["question_id"],
                "clusters": [
                    {
                        "cluster_id": cluster["cluster_id"],
                        "analyst_decision": cluster["analyst_decision"],
                    }
                    for cluster in question["clusters"]
                ],
                "unresolved_answers": [
                    {
                        "processing_id": item["processing_id"],
                        "analyst_decision": item["analyst_decision"],
                    }
                    for item in question["unresolved_answers"]
                ],
            }
            for question in incoming["questions"]
        ],
    }


def _system_projection(document: dict[str, Any]) -> dict[str, Any]:
    """Remove only editable analyst fields before comparing full update payloads."""

    projection = json.loads(json.dumps(document, ensure_ascii=False))
    projection["analyst_name"] = None
    projection["updated_at_utc"] = None
    for question in projection.get("questions", []):
        for cluster in question.get("clusters", []):
            cluster["analyst_decision"] = None
        for item in question.get("unresolved_answers", []):
            item["analyst_decision"] = None
    return projection


def complete_review_document(document: dict[str, Any]) -> dict[str, Any]:
    """Validate all decisions, allocate per-question values, and mark complete."""

    validate_review_file(document)
    if document["status"] == COMPLETE:
        raise ReviewFileError("completed review files are read-only")
    analyst_name = document["analyst_name"]
    if not isinstance(analyst_name, str) or not analyst_name.strip():
        raise ReviewFileError("completion requires a nonblank analyst name")
    _validate_complete_coverage(document, require_decisions=True)
    completed = json.loads(json.dumps(document, ensure_ascii=False))
    for question in completed["questions"]:
        used = {
            choice["value"]
            for choice in question["existing_choices"]
            if choice["value"] > 100
        }
        for cluster in sorted(
            question["clusters"], key=lambda item: item["cluster_id"]
        ):
            decision = cluster["analyst_decision"]
            if decision["decision"] == "new_category":
                value = 101
                while value in used:
                    value += 1
                decision["allocated_value"] = value
                used.add(value)
            else:
                decision["allocated_value"] = None
    now = _timestamp(datetime.now(UTC), "updated_at_utc")
    completed["status"] = COMPLETE
    completed["completed_at_utc"] = now
    completed["updated_at_utc"] = now
    validate_review_file(completed, require_complete=True)
    return completed


def save_review_file(path: str | Path, document: dict[str, Any]) -> Path:
    """Atomically replace an existing in-review or completed review file."""

    validate_review_file(document)
    destination = Path(path).expanduser().resolve()
    if not destination.exists() or not destination.is_file():
        raise ReviewFileError(f"review file does not exist: '{destination}'")
    _atomic_json_write(destination, document, allow_overwrite=True)
    return destination


def update_and_save_review_file(path: str | Path, payload: object) -> dict[str, Any]:
    """Load one file, apply editable decisions, and atomically save it."""

    destination = Path(path).expanduser().resolve()
    current = load_review_file(destination)
    updated = apply_review_edits(current, payload)
    save_review_file(destination, updated)
    return updated


def complete_and_save_review_file(path: str | Path, payload: object) -> dict[str, Any]:
    """Apply editable fields, complete the file, and atomically replace it."""

    destination = Path(path).expanduser().resolve()
    current = load_review_file(destination)
    updated = apply_review_edits(current, payload)
    completed = complete_review_document(updated)
    _atomic_json_write(destination, completed, allow_overwrite=True)
    return completed


def _build_document(
    dataset: WorkbookDataset,
    discovery: CategoryDiscoveryResult,
    classification: ClusterClassificationResult,
    *,
    analysis_run_id: str,
    timestamp: str,
    source: dict[str, object],
) -> dict[str, Any]:
    processing_by_id = {item.processing_id: item for item in dataset.processing_answers}
    answer_by_id = {item.answer_id: item for item in dataset.answers}
    point_by_id = {item.processing_id: item for item in discovery.points}
    proposal_by_cluster = {item.cluster_id: item for item in classification.proposals}
    if len(point_by_id) != len(discovery.points):
        raise ReviewFileError("discovery contains duplicate processing IDs")
    expected_cluster_ids = {item.cluster_id for item in discovery.proposed_clusters}
    if (
        len(proposal_by_cluster) != len(classification.proposals)
        or set(proposal_by_cluster) != expected_cluster_ids
    ):
        raise ReviewFileError(
            "classification must contain exactly one proposal per eligible cluster"
        )

    clusters_by_question: dict[str, list[Any]] = defaultdict(list)
    for cluster in discovery.proposed_clusters:
        clusters_by_question[cluster.question_id].append(cluster)
    questions: list[dict[str, Any]] = []
    for question in sorted(dataset.questions, key=lambda item: item.question_id):
        processing_items = sorted(
            (
                item
                for item in dataset.processing_answers
                if item.question_id == question.question_id
            ),
            key=lambda item: item.processing_id,
        )
        answers = [
            _answer_entry(item, answer_by_id, point_by_id[item.processing_id])
            for item in processing_items
        ]
        cluster_entries = [
            _cluster_entry(
                cluster,
                processing_by_id=processing_by_id,
                points_by_id=point_by_id,
                proposal=proposal_by_cluster[cluster.cluster_id],
            )
            for cluster in sorted(
                clusters_by_question.get(question.question_id, []),
                key=lambda item: item.cluster_id,
            )
        ]
        cluster_member_ids = {
            member_id
            for cluster in cluster_entries
            for member_id in cluster["member_processing_ids"]
        }
        unresolved_entries = [
            {
                "processing_id": item.processing_id,
                "reason": point_by_id[item.processing_id].status,
                "cluster_id": point_by_id[item.processing_id].cluster_id,
                "analyst_decision": None,
            }
            for item in processing_items
            if item.processing_id not in cluster_member_ids
        ]
        questions.append(
            {
                "question_id": question.question_id,
                "question_text": {
                    "english": question.english_text,
                    "arabic": question.arabic_text,
                },
                "source_column": question.source_column,
                "existing_choices": [
                    {
                        "value": choice.value,
                        "english_label": choice.label,
                        "arabic_label": choice.label_arabic,
                        "code_row": choice.code_row,
                    }
                    for choice in sorted(
                        question.choices, key=lambda item: (item.value, item.code_row)
                    )
                ],
                "answers": answers,
                "clusters": cluster_entries,
                "unresolved_answers": unresolved_entries,
            }
        )
    warnings = [_dataset_warning(warning) for warning in sorted(dataset.warnings)]
    warnings.extend(
        sorted(
            classification.warnings, key=lambda item: (item["code"], item["message"])
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_run_id": analysis_run_id,
        "status": IN_REVIEW,
        "created_at_utc": timestamp,
        "updated_at_utc": timestamp,
        "completed_at_utc": None,
        "analyst_name": None,
        "source_workbook": source,
        "questions": questions,
        "warnings": warnings,
    }


def _answer_entry(
    processing: Any, answer_by_id: dict[str, Any], point: Any
) -> dict[str, Any]:
    row_mappings: list[dict[str, Any]] = []
    for answer_id in sorted(processing.answer_ids):
        answer = answer_by_id.get(answer_id)
        if answer is None:
            raise ReviewFileError(
                f"processing answer '{processing.processing_id}' references unknown answer '{answer_id}'"
            )
        cell = answer.source_cell
        row_mappings.append(
            {
                "answer_id": answer.answer_id,
                "respondent_key": answer.respondent_key,
                "sheet": cell.sheet,
                "row": cell.row,
                "column": cell.column,
                "coordinate": cell.coordinate,
            }
        )
    return {
        "processing_id": processing.processing_id,
        "text": processing.text,
        "occurrence_count": processing.occurrence_count,
        "row_mappings": row_mappings,
        "discovery_evidence": {
            "raw_cluster_label": point.raw_cluster_label,
            "membership_probability": point.membership_probability,
            "status": point.status,
            "cluster_id": point.cluster_id,
        },
    }


def _cluster_entry(
    cluster: Any,
    *,
    processing_by_id: dict[str, Any],
    points_by_id: dict[str, Any],
    proposal: ClusterProposal,
) -> dict[str, Any]:
    members = [
        {
            "processing_id": processing_id,
            "text": processing_by_id[processing_id].text,
            "occurrence_count": processing_by_id[processing_id].occurrence_count,
            "membership_probability": points_by_id[
                processing_id
            ].membership_probability,
        }
        for processing_id in sorted(cluster.processing_ids)
    ]
    return {
        "cluster_id": cluster.cluster_id,
        "raw_cluster_label": cluster.raw_cluster_label,
        "member_processing_ids": sorted(cluster.processing_ids),
        "members": members,
        "gemini_proposal": {
            "decision": proposal.decision,
            "selected_choice_value": proposal.selected_choice_value,
            "english_label": proposal.english_label,
            "arabic_label": proposal.arabic_label,
            "rejection_reason": proposal.rejection_reason,
            "provider_error": proposal.provider_error,
        },
        "analyst_decision": None,
    }


def _source_identity(*, input_source: str, source_path: Path) -> dict[str, object]:
    try:
        payload = source_path.read_bytes()
    except OSError as exc:
        raise ReviewFileError(
            f"could not fingerprint analyzed source workbook '{source_path}': {exc}"
        ) from exc
    if source_path.suffix.casefold() != ".xlsx":
        raise ReviewFileError("analyzed source workbook must have an .xlsx filename")
    if is_google_sheets_url(input_source):
        kind = "google_sheets"
        locator = canonical_google_sheets_url(input_source)
    else:
        kind = "local_xlsx"
        locator = str(source_path.resolve())
    return {
        "input_kind": kind,
        "source_locator": locator,
        "display_name": source_path.name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _review_file_path(output_directory: Path, display_name: str, run_id: str) -> Path:
    stem = (
        display_name[:-5] if display_name.casefold().endswith(".xlsx") else display_name
    )
    normalized_stem = re.sub(r"\s+", "_", stem.casefold())
    if not normalized_stem:
        raise ReviewFileError(
            "source workbook display name must contain a filename stem"
        )
    return (
        Path(output_directory).expanduser().resolve()
        / f"{normalized_stem}_{run_id}.json"
    )


def _validate_question(
    question: object, question_ids: set[str], *, complete: bool
) -> None:
    if not isinstance(question, dict):
        raise ReviewFileError("questions must contain objects")
    expected = {
        "question_id",
        "question_text",
        "source_column",
        "existing_choices",
        "answers",
        "clusters",
        "unresolved_answers",
    }
    if set(question) != expected:
        raise ReviewFileError("question entry has an invalid schema")
    question_id = question["question_id"]
    if (
        not isinstance(question_id, str)
        or not question_id
        or question_id in question_ids
    ):
        raise ReviewFileError("question IDs must be unique nonblank strings")
    question_ids.add(question_id)
    question_text = question["question_text"]
    if (
        not isinstance(question_text, dict)
        or set(question_text) != {"english", "arabic"}
        or not all(
            isinstance(question_text[key], str) and question_text[key].strip()
            for key in question_text
        )
    ):
        raise ReviewFileError(
            f"question '{question_id}' has invalid bilingual metadata"
        )
    if not isinstance(question["source_column"], str) or not question["source_column"]:
        raise ReviewFileError(f"question '{question_id}' has an invalid source_column")
    choices = question["existing_choices"]
    if not isinstance(choices, list):
        raise ReviewFileError(
            f"question '{question_id}' existing_choices must be an array"
        )
    choice_values: set[int] = set()
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {
            "value",
            "english_label",
            "arabic_label",
            "code_row",
        }:
            raise ReviewFileError(
                f"question '{question_id}' has an invalid choice entry"
            )
        value = choice["value"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value in choice_values
        ):
            raise ReviewFileError(
                f"question '{question_id}' existing choice values must be unique integers"
            )
        choice_values.add(value)
        if not isinstance(choice["english_label"], str) or not isinstance(
            choice["arabic_label"], str
        ):
            raise ReviewFileError(f"question '{question_id}' has invalid choice labels")
        if isinstance(choice["code_row"], bool) or not isinstance(
            choice["code_row"], int
        ):
            raise ReviewFileError(f"question '{question_id}' has an invalid Code row")
    answers = question["answers"]
    if not isinstance(answers, list):
        raise ReviewFileError(f"question '{question_id}' answers must be an array")
    answer_ids: set[str] = set()
    processing_ids: set[str] = set()
    for answer in answers:
        _validate_answer(answer, question_id, processing_ids, answer_ids)
    clusters = question["clusters"]
    unresolved = question["unresolved_answers"]
    if not isinstance(clusters, list) or not isinstance(unresolved, list):
        raise ReviewFileError(
            f"question '{question_id}' clusters/unresolved_answers must be arrays"
        )
    cluster_ids: set[str] = set()
    member_ids: set[str] = set()
    answers_by_processing_id = {answer["processing_id"]: answer for answer in answers}
    for cluster in clusters:
        _validate_cluster(
            cluster,
            question_id,
            choice_values,
            processing_ids,
            cluster_ids,
            member_ids,
            answers_by_processing_id=answers_by_processing_id,
            existing_labels={
                label
                for choice in choices
                for label in (choice["english_label"], choice["arabic_label"])
            },
            complete=complete,
        )
    unresolved_ids: set[str] = set()
    for item in unresolved:
        _validate_unresolved(
            item,
            question_id,
            choice_values,
            processing_ids,
            unresolved_ids,
            answers_by_processing_id=answers_by_processing_id,
            complete=complete,
        )
    if member_ids & unresolved_ids or member_ids | unresolved_ids != processing_ids:
        raise ReviewFileError(
            f"question '{question_id}' must represent every canonical answer exactly once"
        )
    _validate_question_label_duplicates(question, choice_values)


def _validate_answer(
    answer: object,
    question_id: str,
    processing_ids: set[str],
    answer_ids: set[str],
) -> None:
    if not isinstance(answer, dict) or set(answer) != {
        "processing_id",
        "text",
        "occurrence_count",
        "row_mappings",
        "discovery_evidence",
    }:
        raise ReviewFileError(f"question '{question_id}' has an invalid answer entry")
    processing_id = answer["processing_id"]
    if (
        not isinstance(processing_id, str)
        or not processing_id
        or processing_id in processing_ids
    ):
        raise ReviewFileError(
            f"question '{question_id}' has duplicate/invalid processing IDs"
        )
    processing_ids.add(processing_id)
    if not isinstance(answer["text"], str) or not answer["text"].strip():
        raise ReviewFileError(f"answer '{processing_id}' text must be nonblank")
    occurrence = answer["occurrence_count"]
    mappings = answer["row_mappings"]
    if (
        isinstance(occurrence, bool)
        or not isinstance(occurrence, int)
        or not isinstance(mappings, list)
    ):
        raise ReviewFileError(
            f"answer '{processing_id}' has invalid occurrence mappings"
        )
    if occurrence != len(mappings) or occurrence < 1:
        raise ReviewFileError(
            f"answer '{processing_id}' occurrence_count does not match row_mappings"
        )
    for mapping in mappings:
        if not isinstance(mapping, dict) or set(mapping) != {
            "answer_id",
            "respondent_key",
            "sheet",
            "row",
            "column",
            "coordinate",
        }:
            raise ReviewFileError(
                f"answer '{processing_id}' has an invalid row mapping"
            )
        answer_id = mapping["answer_id"]
        if not isinstance(answer_id, str) or not answer_id or answer_id in answer_ids:
            raise ReviewFileError(
                f"answer '{processing_id}' has duplicate/invalid answer IDs"
            )
        answer_ids.add(answer_id)
        if mapping["sheet"] != "Data":
            raise ReviewFileError("row mappings must refer to the Data sheet")
        if (
            not isinstance(mapping["respondent_key"], str)
            or not mapping["respondent_key"]
        ):
            raise ReviewFileError(
                f"answer '{processing_id}' has an invalid respondent key"
            )
        for field in ("row", "column"):
            if (
                isinstance(mapping[field], bool)
                or not isinstance(mapping[field], int)
                or mapping[field] < 1
            ):
                raise ReviewFileError(
                    f"answer '{processing_id}' has an invalid source {field}"
                )
        if not isinstance(mapping["coordinate"], str) or not mapping["coordinate"]:
            raise ReviewFileError(f"answer '{processing_id}' has an invalid coordinate")
    _validate_discovery_evidence(answer["discovery_evidence"], processing_id)


def _validate_discovery_evidence(evidence: object, processing_id: str) -> None:
    if not isinstance(evidence, dict) or set(evidence) != {
        "raw_cluster_label",
        "membership_probability",
        "status",
        "cluster_id",
    }:
        raise ReviewFileError(
            f"answer '{processing_id}' has invalid discovery evidence"
        )
    status = evidence["status"]
    if status not in _DISCOVERY_STATUSES:
        raise ReviewFileError(f"answer '{processing_id}' has invalid discovery status")
    raw = evidence["raw_cluster_label"]
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        raise ReviewFileError(
            f"answer '{processing_id}' has an invalid raw cluster label"
        )
    probability = evidence["membership_probability"]
    if probability is not None and (
        isinstance(probability, bool)
        or not isinstance(probability, (int, float))
        or not 0 <= probability <= 1
    ):
        raise ReviewFileError(
            f"answer '{processing_id}' has an invalid membership probability"
        )
    cluster_id = evidence["cluster_id"]
    if cluster_id is not None and not isinstance(cluster_id, str):
        raise ReviewFileError(
            f"answer '{processing_id}' has an invalid cluster reference"
        )
    if status == "accepted_cluster" and not isinstance(cluster_id, str):
        raise ReviewFileError(
            f"accepted answer '{processing_id}' must reference a cluster"
        )
    if status != "accepted_cluster" and cluster_id is not None:
        raise ReviewFileError(
            f"unresolved answer '{processing_id}' cannot reference a cluster"
        )


def _validate_cluster(
    cluster: object,
    question_id: str,
    choice_values: set[int],
    processing_ids: set[str],
    cluster_ids: set[str],
    member_ids: set[str],
    *,
    answers_by_processing_id: dict[str, Any],
    existing_labels: set[str],
    complete: bool,
) -> None:
    if not isinstance(cluster, dict) or set(cluster) != {
        "cluster_id",
        "raw_cluster_label",
        "member_processing_ids",
        "members",
        "gemini_proposal",
        "analyst_decision",
    }:
        raise ReviewFileError(f"question '{question_id}' has an invalid cluster entry")
    cluster_id = cluster["cluster_id"]
    if not isinstance(cluster_id, str) or not cluster_id or cluster_id in cluster_ids:
        raise ReviewFileError(
            f"question '{question_id}' has duplicate/invalid cluster IDs"
        )
    cluster_ids.add(cluster_id)
    raw = cluster["raw_cluster_label"]
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ReviewFileError(f"cluster '{cluster_id}' has an invalid raw label")
    ids = cluster["member_processing_ids"]
    members = cluster["members"]
    if (
        not isinstance(ids, list)
        or not isinstance(members, list)
        or len(ids) != len(members)
        or len(ids) < 3
    ):
        raise ReviewFileError(f"cluster '{cluster_id}' has invalid fixed membership")
    if (
        any(not isinstance(item, str) for item in ids)
        or ids != sorted(ids)
        or len(set(ids)) != len(ids)
    ):
        raise ReviewFileError(
            f"cluster '{cluster_id}' member IDs must be sorted and unique"
        )
    for processing_id, member in zip(ids, members, strict=True):
        if processing_id not in processing_ids or processing_id in member_ids:
            raise ReviewFileError(
                f"cluster '{cluster_id}' references an invalid/repeated processing ID"
            )
        member_ids.add(processing_id)
        if (
            not isinstance(member, dict)
            or set(member)
            != {"processing_id", "text", "occurrence_count", "membership_probability"}
            or member["processing_id"] != processing_id
        ):
            raise ReviewFileError(f"cluster '{cluster_id}' has invalid member evidence")
        if not isinstance(member["text"], str) or not member["text"].strip():
            raise ReviewFileError(f"cluster '{cluster_id}' has blank member text")
        if (
            isinstance(member["occurrence_count"], bool)
            or not isinstance(member["occurrence_count"], int)
            or member["occurrence_count"] < 1
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' has invalid member occurrence count"
            )
        probability = member["membership_probability"]
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not 0 <= probability <= 1
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' has invalid member probability"
            )
        answer = answers_by_processing_id[processing_id]
        evidence = answer["discovery_evidence"]
        if (
            evidence["status"] != "accepted_cluster"
            or evidence["cluster_id"] != cluster_id
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' does not match answer '{processing_id}' discovery evidence"
            )
        if (
            member["text"] != answer["text"]
            or member["occurrence_count"] != answer["occurrence_count"]
            or member["membership_probability"] != evidence["membership_probability"]
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' member evidence does not match answer '{processing_id}'"
            )
    if any(
        answers_by_processing_id[processing_id]["discovery_evidence"][
            "raw_cluster_label"
        ]
        != raw
        for processing_id in ids
    ):
        raise ReviewFileError(
            f"cluster '{cluster_id}' raw label does not match answer evidence"
        )
    _validate_gemini_proposal(
        cluster["gemini_proposal"],
        question_id,
        choice_values,
        cluster_id,
        existing_labels=existing_labels,
    )
    _validate_analyst_decision(
        cluster["analyst_decision"],
        question_id,
        choice_values,
        cluster_id,
        allow_null=True,
        complete=complete,
    )


def _validate_gemini_proposal(
    proposal: object,
    question_id: str,
    choice_values: set[int],
    cluster_id: str,
    *,
    existing_labels: set[str],
) -> None:
    if not isinstance(proposal, dict) or set(proposal) != {
        "decision",
        "selected_choice_value",
        "english_label",
        "arabic_label",
        "rejection_reason",
        "provider_error",
    }:
        raise ReviewFileError(f"cluster '{cluster_id}' has an invalid Gemini proposal")
    decision = proposal["decision"]
    selected = proposal["selected_choice_value"]
    english = proposal["english_label"]
    arabic = proposal["arabic_label"]
    reason = proposal["rejection_reason"]
    provider_error = proposal["provider_error"]
    if provider_error is not None:
        if (
            decision != "provider_error"
            or any(value is not None for value in (selected, english, arabic, reason))
            or not isinstance(provider_error, str)
            or not provider_error
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' has invalid provider-error proposal"
            )
        return
    if decision == "existing_choice":
        if (
            isinstance(selected, bool)
            or not isinstance(selected, int)
            or selected not in choice_values
            or english is not None
            or arabic is not None
            or reason is not None
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' has invalid existing-choice proposal"
            )
    elif decision == "new_category":
        if (
            selected is not None
            or not isinstance(english, str)
            or not isinstance(arabic, str)
            or reason is not None
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' has invalid new-category proposal"
            )
        try:
            validate_analyst_label_pair(
                english,
                arabic,
                existing_labels=existing_labels,
                other_category_labels=set(),
            )
        except ReviewFileError:
            raise
        except Exception as exc:
            raise ReviewFileError(
                f"cluster '{cluster_id}' has invalid bilingual proposal labels: {exc}"
            ) from exc
    elif decision == "reject_cluster":
        if (
            selected is not None
            or english is not None
            or arabic is not None
            or not isinstance(reason, str)
            or reason
            not in {"mixed_meanings", "insufficient_common_meaning", "unsafe_to_label"}
        ):
            raise ReviewFileError(
                f"cluster '{cluster_id}' has invalid rejection proposal"
            )
    else:
        raise ReviewFileError(f"cluster '{cluster_id}' has an invalid Gemini decision")


def _validate_unresolved(
    item: object,
    question_id: str,
    choice_values: set[int],
    processing_ids: set[str],
    unresolved_ids: set[str],
    *,
    answers_by_processing_id: dict[str, Any],
    complete: bool,
) -> None:
    if not isinstance(item, dict) or set(item) != {
        "processing_id",
        "reason",
        "cluster_id",
        "analyst_decision",
    }:
        raise ReviewFileError(
            f"question '{question_id}' has an invalid unresolved entry"
        )
    processing_id = item["processing_id"]
    if (
        not isinstance(processing_id, str)
        or processing_id not in processing_ids
        or processing_id in unresolved_ids
    ):
        raise ReviewFileError(
            f"question '{question_id}' has an invalid/repeated unresolved processing ID"
        )
    unresolved_ids.add(processing_id)
    if item["reason"] not in _UNRESOLVED_REASONS:
        raise ReviewFileError(
            f"unresolved answer '{processing_id}' has an invalid reason"
        )
    if item["cluster_id"] is not None:
        raise ReviewFileError(
            f"unresolved answer '{processing_id}' cannot have a cluster ID"
        )
    evidence = answers_by_processing_id[processing_id]["discovery_evidence"]
    if evidence["status"] != item["reason"] or evidence["cluster_id"] is not None:
        raise ReviewFileError(
            f"unresolved answer '{processing_id}' does not match its discovery evidence"
        )
    _validate_analyst_decision(
        item["analyst_decision"],
        question_id,
        choice_values,
        processing_id,
        allow_null=True,
        complete=complete,
        noise=True,
    )


def _validate_analyst_decision(
    decision: object,
    question_id: str,
    choice_values: set[int],
    identifier: str,
    *,
    allow_null: bool,
    complete: bool,
    noise: bool = False,
) -> None:
    if decision is None:
        if allow_null:
            return
        raise ReviewFileError(f"'{identifier}' is missing an analyst decision")
    if not isinstance(decision, dict) or set(decision) != {
        "decision",
        "selected_choice_value",
        "english_label",
        "arabic_label",
        "allocated_value",
    }:
        raise ReviewFileError(f"'{identifier}' has an invalid analyst decision schema")
    kind = decision["decision"]
    selected = decision["selected_choice_value"]
    english = decision["english_label"]
    arabic = decision["arabic_label"]
    allocated = decision["allocated_value"]
    allowed = {"existing_choice", "unresolved"} if noise else _ANALYST_DECISIONS
    if kind not in allowed:
        raise ReviewFileError(f"'{identifier}' has an invalid analyst decision")
    if kind == "existing_choice":
        if (
            isinstance(selected, bool)
            or not isinstance(selected, int)
            or selected not in choice_values
            or english is not None
            or arabic is not None
            or allocated is not None
        ):
            raise ReviewFileError(
                f"'{identifier}' existing_choice decision is invalid or cross-question"
            )
    elif kind == "unresolved":
        if any(value is not None for value in (selected, english, arabic, allocated)):
            raise ReviewFileError(
                f"'{identifier}' unresolved decision cannot contain a value or labels"
            )
    elif kind == "new_category":
        if (
            selected is not None
            or not isinstance(english, str)
            or not isinstance(arabic, str)
        ):
            raise ReviewFileError(
                f"'{identifier}' new_category decision requires bilingual labels"
            )
        if allocated is not None and (
            isinstance(allocated, bool)
            or not isinstance(allocated, int)
            or allocated <= 100
        ):
            raise ReviewFileError(f"'{identifier}' has an invalid allocated value")
        if not complete and allocated is not None:
            raise ReviewFileError(
                f"'{identifier}' cannot allocate a value before completion"
            )
        if complete and (
            isinstance(allocated, bool)
            or not isinstance(allocated, int)
            or allocated <= 100
        ):
            raise ReviewFileError(
                f"'{identifier}' must have an allocated value greater than 100"
            )


def _validate_question_label_duplicates(
    question: dict[str, Any], choice_values: set[int]
) -> None:
    existing = {
        normalize_label(choice["english_label"])
        for choice in question["existing_choices"]
    } | {
        normalize_label(choice["arabic_label"])
        for choice in question["existing_choices"]
    }
    seen: set[str] = set()
    for cluster in question["clusters"]:
        decision = cluster["analyst_decision"]
        if not isinstance(decision, dict) or decision["decision"] != "new_category":
            continue
        try:
            english, arabic = validate_analyst_label_pair(
                decision["english_label"],
                decision["arabic_label"],
                existing_labels=existing,
                other_category_labels=seen,
            )
        except Exception as exc:
            raise ReviewFileError(
                f"cluster '{cluster['cluster_id']}' has invalid bilingual labels: {exc}"
            ) from exc
        decision["english_label"] = english
        decision["arabic_label"] = arabic
        seen.update({normalize_label(english), normalize_label(arabic)})


def _validate_in_review_allocations(document: dict[str, Any]) -> None:
    for question in document["questions"]:
        for cluster in question["clusters"]:
            decision = cluster["analyst_decision"]
            if isinstance(decision, dict) and decision["allocated_value"] is not None:
                raise ReviewFileError(
                    "allocated values are hidden until review completion"
                )


def _validate_complete_coverage(
    document: dict[str, Any], *, require_decisions: bool = False
) -> None:
    for question in document["questions"]:
        for collection in (question["clusters"], question["unresolved_answers"]):
            for item in collection:
                _validate_analyst_decision(
                    item["analyst_decision"],
                    question["question_id"],
                    {choice["value"] for choice in question["existing_choices"]},
                    item.get("cluster_id", item.get("processing_id", "item")),
                    allow_null=not require_decisions,
                    complete=document["status"] == COMPLETE,
                    noise=collection is question["unresolved_answers"],
                )


def _apply_question_decisions(document: dict[str, Any], questions: object) -> None:
    if not isinstance(questions, list):
        raise ReviewFileError("review update questions must be an array")
    current_by_id = {
        question["question_id"]: question for question in document["questions"]
    }
    if {item.get("question_id") for item in questions if isinstance(item, dict)} != set(
        current_by_id
    ):
        raise ReviewFileError(
            "review update must include exactly the existing questions"
        )
    for update in questions:
        if not isinstance(update, dict) or set(update) != {
            "question_id",
            "clusters",
            "unresolved_answers",
        }:
            raise ReviewFileError("review update question has an invalid schema")
        question_id = update["question_id"]
        if question_id not in current_by_id:
            raise ReviewFileError(f"unknown question '{question_id}' in review update")
        current = current_by_id[question_id]
        _copy_decisions(current["clusters"], update["clusters"], key="cluster_id")
        _copy_decisions(
            current["unresolved_answers"],
            update["unresolved_answers"],
            key="processing_id",
        )


def _copy_decisions(current: list[Any], incoming: object, *, key: str) -> None:
    if not isinstance(incoming, list):
        raise ReviewFileError("review update decision collections must be arrays")
    current_by_key = {item[key]: item for item in current}
    incoming_by_key: dict[str, Any] = {}
    for item in incoming:
        if not isinstance(item, dict) or set(item) != {key, "analyst_decision"}:
            raise ReviewFileError(
                "review update may change only analyst_decision fields"
            )
        identifier = item[key]
        if identifier in incoming_by_key or identifier not in current_by_key:
            raise ReviewFileError(
                "review update references an unknown or repeated evidence item"
            )
        incoming_by_key[identifier] = item["analyst_decision"]
    if set(incoming_by_key) != set(current_by_key):
        raise ReviewFileError(
            "review update must include every cluster and unresolved answer"
        )
    for identifier, decision in incoming_by_key.items():
        current_by_key[identifier]["analyst_decision"] = decision


def _validate_source_identity(source: object) -> None:
    if not isinstance(source, dict) or set(source) != {
        "input_kind",
        "source_locator",
        "display_name",
        "size_bytes",
        "sha256",
    }:
        raise ReviewFileError("source_workbook has an invalid schema")
    if source["input_kind"] not in {"local_xlsx", "google_sheets"}:
        raise ReviewFileError("source_workbook.input_kind is invalid")
    if not isinstance(source["source_locator"], str) or not source["source_locator"]:
        raise ReviewFileError("source_workbook.source_locator must be nonblank")
    if not isinstance(source["display_name"], str) or not source[
        "display_name"
    ].casefold().endswith(".xlsx"):
        raise ReviewFileError("source_workbook.display_name must be an .xlsx filename")
    if (
        isinstance(source["size_bytes"], bool)
        or not isinstance(source["size_bytes"], int)
        or source["size_bytes"] < 0
    ):
        raise ReviewFileError(
            "source_workbook.size_bytes must be a nonnegative integer"
        )
    if not isinstance(source["sha256"], str) or not _SHA256_PATTERN.fullmatch(
        source["sha256"]
    ):
        raise ReviewFileError(
            "source_workbook.sha256 must be lowercase hexadecimal SHA-256"
        )


def _validate_warning(warning: object) -> None:
    if not isinstance(warning, dict) or set(warning) != {
        "code",
        "message",
        "source_cell",
    }:
        raise ReviewFileError("warnings must contain code, message, and source_cell")
    if (
        not isinstance(warning["code"], str)
        or not warning["code"]
        or not isinstance(warning["message"], str)
    ):
        raise ReviewFileError("warning code/message must be strings")
    if warning["source_cell"] is not None and not isinstance(
        warning["source_cell"], str
    ):
        raise ReviewFileError("warning source_cell must be a string or null")


def _dataset_warning(message: str) -> dict[str, str | None]:
    source_cell = None
    match = re.match(r"(Data![A-Z]+\d+)", message)
    if match:
        source_cell = match.group(1)
    return {"code": "workbook_warning", "message": message, "source_cell": source_cell}


def _require_uuid4(value: object, field: str) -> None:
    if not isinstance(value, str) or not _UUID_PATTERN.fullmatch(value):
        raise ReviewFileError(f"{field} must be a lowercase UUIDv4")


def _require_timestamp(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReviewFileError(f"{field} must be an RFC 3339 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReviewFileError(f"{field} must be an RFC 3339 UTC timestamp") from exc


def _timestamp(value: datetime, field: str) -> str:
    if value.tzinfo is None:
        raise ReviewFileError(f"{field} must include a timezone")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _atomic_json_write(
    destination: Path, value: dict[str, Any], *, allow_overwrite: bool
) -> None:
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not allow_overwrite and destination.exists():
            raise FileExistsError(destination)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("xb") as output:
            output.write(
                (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except FileExistsError as exc:
        raise ReviewFileError(
            f"review file already exists and will not be overwritten: '{destination}'"
        ) from exc
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise ReviewFileError(
            f"could not atomically save review file '{destination}': {exc}"
        ) from exc
