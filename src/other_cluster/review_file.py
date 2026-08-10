"""Public review-file API: construction, revisioned commands, and persistence."""

from __future__ import annotations

import json
import os
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from .domain import (
    CategoryDiscoveryResult,
    ClusterClassificationResult,
    ReviewFileResult,
    WorkbookDataset,
)
from .errors import ReviewConflictError, ReviewFileError
from .review_document import build_document, source_identity
from .review_validation import COMPLETE, validate_review_file

_COMMAND_LOCK = Lock()


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
    """Create one validated, atomically written schema-version-4 document."""

    run_id = analysis_run_id or str(uuid.uuid4())
    if not _is_uuid4(run_id):
        raise ReviewFileError("analysis_run_id must be a lowercase UUIDv4")
    timestamp = _timestamp(created_at_utc or datetime.now(UTC))
    source = source_identity(input_source=input_source, source_path=source_path)
    document = build_document(
        dataset,
        discovery,
        classification,
        analysis_run_id=run_id,
        timestamp=timestamp,
        source=source,
    )
    validate_review_file(document)
    destination = _review_path(output_directory, str(source["display_name"]), run_id)
    if destination.exists():
        raise ReviewFileError(
            f"review file already exists and will not be overwritten: '{destination}'"
        )
    _atomic_write(destination, document, overwrite=False)
    counts = {
        "question_count": len(document["questions"]),
        "canonical_answer_count": sum(
            len(question["answers"]) for question in document["questions"]
        ),
        "proposal_eligible_cluster_count": sum(
            len(question["automatic_groups"]) for question in document["questions"]
        ),
        "unresolved_canonical_answer_count": sum(
            len(question["workspace"]["needs_attention"])
            for question in document["questions"]
        ),
        "gemini_request_count": classification.request_count,
        "provider_error_cluster_count": classification.provider_error_count,
    }
    return ReviewFileResult(
        destination.resolve(), run_id, str(source["sha256"]), counts
    )


def load_review_file(path: str | Path) -> dict[str, Any]:
    """Load and validate untrusted persisted review JSON."""

    review_path = Path(path).expanduser().resolve()
    if not review_path.is_file():
        raise ReviewFileError(
            f"review file does not exist or is not a file: '{review_path}'"
        )
    try:
        with review_path.open(encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewFileError(
            f"could not read review file '{review_path}': {exc}"
        ) from exc
    validate_review_file(document)
    return document


def apply_and_save_review_command(path: str | Path, payload: object) -> dict[str, Any]:
    """Apply one command against the current revision and persist it atomically."""

    destination = Path(path).expanduser().resolve()
    with _COMMAND_LOCK:
        updated = apply_review_command(load_review_file(destination), payload)
        _atomic_write(destination, updated, overwrite=True)
    return updated


def apply_review_command(current: dict[str, Any], payload: object) -> dict[str, Any]:
    """Validate and apply one narrow V4 group command in memory."""

    validate_review_file(current)
    if current["schema_version"] != 4:
        raise ReviewFileError("schema-version-3 review artifacts are read-only")
    if current["status"] == COMPLETE:
        raise ReviewFileError("completed review files are read-only")
    if not isinstance(payload, dict) or set(payload) != {
        "expected_revision",
        "command",
    }:
        raise ReviewFileError(
            "command request must contain expected_revision and command"
        )
    expected = payload["expected_revision"]
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ReviewFileError("expected_revision must be a nonnegative integer")
    if expected != current["revision"]:
        raise ReviewConflictError(
            f"stale review revision {expected}; current revision is {current['revision']}"
        )
    command = payload["command"]
    if not isinstance(command, dict) or not isinstance(command.get("type"), str):
        raise ReviewFileError("command must be an object with a type")

    updated = deepcopy(current)
    question = _command_question(updated, command)
    now = _timestamp(datetime.now(UTC))
    next_revision = current["revision"] + 1
    answers = {answer["processing_id"]: answer for answer in question["answers"]}
    if command["type"] == "move_answers":
        group_id, members, before, after = _apply_move_command(
            question, command, answers
        )
    else:
        group = _command_group(question, command)
        members = list(group["member_processing_ids"])
        before, after = _apply_group_command(group, command)
        group_id = group["group_id"]
    question["workspace"]["history"].append(
        _command_history_entry(
            command_type=command["type"],
            revision=next_revision,
            timestamp=now,
            group_id=group_id,
            members=members,
            answers=answers,
            before=before,
            after=after,
        )
    )
    updated["revision"] = next_revision
    updated["updated_at_utc"] = now
    validate_review_file(updated)
    return updated


def _apply_group_command(
    group: dict[str, Any], command: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one supported command and return its compact before/after state."""

    if command["type"] == "apply_decision":
        if set(command) != {"type", "question_id", "group_id", "decision"}:
            raise ReviewFileError("apply_decision command has an invalid schema")
        before = {
            "decision": deepcopy(group["decision"]),
            "review_state": group["review_state"],
        }
        group["decision"] = deepcopy(command["decision"])
        group["review_state"] = "needs_review"
        after = {
            "decision": deepcopy(group["decision"]),
            "review_state": "needs_review",
        }
    elif command["type"] == "confirm_group":
        if set(command) != {"type", "question_id", "group_id"}:
            raise ReviewFileError("confirm_group command has an invalid schema")
        if group["review_state"] == "confirmed":
            raise ReviewFileError("group is already confirmed")
        before = {"review_state": "needs_review"}
        group["review_state"] = "confirmed"
        after = {"review_state": "confirmed"}
    else:
        raise ReviewFileError(f"unsupported review command {command['type']!r}")
    return before, after


def _apply_move_command(
    question: dict[str, Any],
    command: dict[str, Any],
    answers: dict[str, dict[str, Any]],
) -> tuple[str | None, list[str], dict[str, Any], dict[str, Any]]:
    """Move whole canonical answers between current locations in one question."""

    if set(command) != {
        "type",
        "question_id",
        "processing_ids",
        "source_locations",
        "destination",
    }:
        raise ReviewFileError("move_answers command has an invalid schema")
    processing_ids = command["processing_ids"]
    if (
        not isinstance(processing_ids, list)
        or not processing_ids
        or any(
            not isinstance(processing_id, str) or processing_id not in answers
            for processing_id in processing_ids
        )
        or len(set(processing_ids)) != len(processing_ids)
    ):
        raise ReviewFileError("move_answers processing_ids are invalid")

    workspace = question["workspace"]
    active_groups = workspace["active_groups"]
    group_by_id = {group["group_id"]: group for group in active_groups}
    current_locations = {
        processing_id: {
            "location": "active_group",
            "group_id": group["group_id"],
        }
        for group in active_groups
        for processing_id in group["member_processing_ids"]
    }
    current_locations.update(
        {
            processing_id: {"location": "needs_attention"}
            for processing_id in workspace["needs_attention"]
        }
    )
    current_locations.update(
        {
            processing_id: {"location": "excluded"}
            for processing_id in workspace["excluded_answers"]
        }
    )
    selected = set(processing_ids)
    source_locations = command["source_locations"]
    if not isinstance(source_locations, list) or len(source_locations) != len(selected):
        raise ReviewFileError("move_answers source_locations are invalid")
    declared_sources: dict[str, dict[str, Any]] = {}
    for source in source_locations:
        processing_id, location = _answer_location(source)
        if processing_id is None or processing_id in declared_sources:
            raise ReviewFileError("move_answers source_locations are invalid")
        declared_sources[processing_id] = location
    if set(declared_sources) != selected or any(
        declared_sources[processing_id] != current_locations[processing_id]
        for processing_id in selected
    ):
        raise ReviewFileError(
            "move_answers source location does not match current state"
        )

    _, destination = _answer_location(command["destination"], allow_processing_id=False)
    destination_group_id = destination.get("group_id")
    if (
        destination["location"] == "active_group"
        and destination_group_id not in group_by_id
    ):
        raise ReviewFileError("move_answers destination group is not active")
    if all(
        current_locations[processing_id] == destination for processing_id in selected
    ):
        raise ReviewFileError("move_answers must change at least one answer location")

    answer_order = {
        answer["processing_id"]: index
        for index, answer in enumerate(question["answers"])
    }
    members = sorted(selected, key=answer_order.__getitem__)
    affected_group_ids = {
        location["group_id"]
        for location in declared_sources.values()
        if location["location"] == "active_group"
    }
    if destination_group_id is not None:
        affected_group_ids.add(destination_group_id)
    affected_before = [
        _history_group_state(group)
        for group in active_groups
        if group["group_id"] in affected_group_ids
    ]
    before = {
        "locations": [
            {
                "processing_id": processing_id,
                **current_locations[processing_id],
            }
            for processing_id in members
        ],
        "groups": affected_before,
    }

    for group in active_groups:
        group["member_processing_ids"] = [
            processing_id
            for processing_id in group["member_processing_ids"]
            if processing_id not in selected
        ]
    workspace["needs_attention"] = [
        processing_id
        for processing_id in workspace["needs_attention"]
        if processing_id not in selected
    ]
    if destination["location"] == "active_group":
        group_by_id[destination_group_id]["member_processing_ids"].extend(members)
    else:
        workspace["needs_attention"].extend(members)

    retired = []
    remaining = []
    for group in active_groups:
        group["member_processing_ids"] = sorted(
            group["member_processing_ids"], key=answer_order.__getitem__
        )
        if group["group_id"] in affected_group_ids:
            group["review_state"] = "needs_review"
        if group["member_processing_ids"]:
            remaining.append(group)
        else:
            retired.append(group)
    workspace["active_groups"] = remaining
    workspace["retired_groups"].extend(retired)
    workspace["retired_groups"].sort(key=lambda group: group["creation_order"])
    workspace["needs_attention"].sort(key=answer_order.__getitem__)

    current_group_by_id = {
        group["group_id"]: (group, False)
        for group in workspace["active_groups"]
        if group["group_id"] in affected_group_ids
    }
    current_group_by_id.update(
        {
            group["group_id"]: (group, True)
            for group in workspace["retired_groups"]
            if group["group_id"] in affected_group_ids
        }
    )
    after = {
        "destination": destination,
        "groups": [
            {
                **_history_group_state(current_group_by_id[group_id][0]),
                "retired": current_group_by_id[group_id][1],
            }
            for group_id in sorted(
                current_group_by_id,
                key=lambda group_id: current_group_by_id[group_id][0]["creation_order"],
            )
        ],
    }
    return destination_group_id, members, before, after


def _answer_location(
    value: object,
    *,
    allow_processing_id: bool = True,
) -> tuple[str | None, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ReviewFileError("answer location must be an object")
    processing_id = value.get("processing_id") if allow_processing_id else None
    prefix = {"processing_id"} if allow_processing_id else set()
    if allow_processing_id and not isinstance(processing_id, str):
        raise ReviewFileError("answer location processing_id must be a string")
    location = value.get("location")
    if location == "active_group" and set(value) == prefix | {"location", "group_id"}:
        if not isinstance(value["group_id"], str) or not value["group_id"]:
            raise ReviewFileError("answer location group_id must be a nonblank string")
        return processing_id, {"location": location, "group_id": value["group_id"]}
    if location == "needs_attention" and set(value) == prefix | {"location"}:
        return processing_id, {"location": location}
    raise ReviewFileError("answer location has an invalid schema")


def _history_group_state(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "group_id": group["group_id"],
        "decision": deepcopy(group["decision"]),
        "review_state": group["review_state"],
    }


def _command_history_entry(
    *,
    command_type: str,
    revision: int,
    timestamp: str,
    group_id: str | None,
    members: list[str],
    answers: dict[str, dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    """Build one compact history record from the validated command result."""

    return {
        "operation": command_type,
        "revision": revision,
        "timestamp_utc": timestamp,
        "group_id": group_id,
        "affected_processing_ids": members,
        "affected_answer_count": len(members),
        "affected_response_count": sum(
            answers[processing_id]["occurrence_count"] for processing_id in members
        ),
        "before": before,
        "after": after,
    }


def _command_question(
    document: dict[str, Any], command: dict[str, Any]
) -> dict[str, Any]:
    question_id = command.get("question_id")
    if not isinstance(question_id, str):
        raise ReviewFileError("command question_id must be a string")
    question = next(
        (
            candidate
            for candidate in document["questions"]
            if candidate["question_id"] == question_id
        ),
        None,
    )
    if question is None:
        raise ReviewFileError("command references an unknown question")
    return question


def _command_group(question: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
    group_id = command.get("group_id")
    if not isinstance(group_id, str):
        raise ReviewFileError("command group_id must be a string")
    group = next(
        (
            candidate
            for candidate in question["workspace"]["active_groups"]
            if candidate["group_id"] == group_id
        ),
        None,
    )
    if group is None:
        raise ReviewFileError("command references an unknown active group")
    return group


def _review_path(directory: Path, display_name: str, run_id: str) -> Path:
    stem = (
        display_name[:-5] if display_name.casefold().endswith(".xlsx") else display_name
    )
    normalized = re.sub(r"\s+", "_", stem.casefold())
    if not normalized:
        raise ReviewFileError(
            "source workbook display name must contain a filename stem"
        )
    return Path(directory).expanduser().resolve() / f"{normalized}_{run_id}.json"


def _atomic_write(
    destination: Path, document: dict[str, Any], *, overwrite: bool
) -> None:
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if not overwrite and destination.exists():
            raise ReviewFileError(
                f"review file already exists and will not be overwritten: '{destination}'"
            )
        os.replace(temporary, destination)
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, ReviewFileError):
            raise
        raise ReviewFileError(
            f"could not atomically write review file '{destination}': {exc}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _is_uuid4(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            value,
        )
    )
