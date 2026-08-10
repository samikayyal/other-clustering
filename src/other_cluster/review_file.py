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
    question, group = _command_group(updated, command)
    now = _timestamp(datetime.now(UTC))
    next_revision = current["revision"] + 1
    members = list(group["member_processing_ids"])
    answers = {item["processing_id"]: item for item in question["answers"]}
    before, after = _apply_group_command(group, command)
    question["workspace"]["history"].append(
        _command_history_entry(
            command_type=command["type"],
            revision=next_revision,
            timestamp=now,
            group=group,
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


def _command_history_entry(
    *,
    command_type: str,
    revision: int,
    timestamp: str,
    group: dict[str, Any],
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
        "group_id": group["group_id"],
        "affected_processing_ids": members,
        "affected_answer_count": len(members),
        "affected_response_count": sum(
            answers[item]["occurrence_count"] for item in members
        ),
        "before": before,
        "after": after,
    }


def _command_group(
    document: dict[str, Any], command: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    question_id = command.get("question_id")
    group_id = command.get("group_id")
    if not isinstance(question_id, str) or not isinstance(group_id, str):
        raise ReviewFileError("command question_id and group_id must be strings")
    question = next(
        (item for item in document["questions"] if item["question_id"] == question_id),
        None,
    )
    if question is None:
        raise ReviewFileError("command references an unknown question")
    group = next(
        (
            item
            for item in question["workspace"]["active_groups"]
            if item["group_id"] == group_id
        ),
        None,
    )
    if group is None:
        raise ReviewFileError("command references an unknown active group")
    return question, group


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
