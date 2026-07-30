"""Public review-file API: construction, bounded edits, completion, persistence."""

from __future__ import annotations

import json
import os
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain import (
    CategoryDiscoveryResult,
    ClusterClassificationResult,
    ReviewFileResult,
    WorkbookDataset,
)
from .errors import ReviewFileError
from .review_document import build_document, source_identity
from .review_validation import COMPLETE, validate_completion, validate_review_file


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
    """Create one validated, atomically written schema-version-3 document."""

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
            len(question["clusters"]) for question in document["questions"]
        ),
        "unresolved_canonical_answer_count": sum(
            len(question["unresolved_answers"]) for question in document["questions"]
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


def apply_review_edits(current: dict[str, Any], payload: object) -> dict[str, Any]:
    """Accept only analyst fields; immutable system evidence never crosses HTTP."""

    validate_review_file(current)
    if current["status"] == COMPLETE:
        raise ReviewFileError("completed review files are read-only")
    if not isinstance(payload, dict) or set(payload) - {"analyst_name", "questions"}:
        raise ReviewFileError(
            "review update may contain only analyst_name and questions"
        )
    updated = deepcopy(current)
    if "analyst_name" in payload:
        if payload["analyst_name"] is not None and not isinstance(
            payload["analyst_name"], str
        ):
            raise ReviewFileError("analyst_name must be a string or null")
        updated["analyst_name"] = payload["analyst_name"]
    if "questions" in payload:
        _apply_decisions(updated, payload["questions"])
    updated["updated_at_utc"] = _timestamp(datetime.now(UTC))
    validate_review_file(updated)
    return updated


def complete_review_document(document: dict[str, Any]) -> dict[str, Any]:
    """Allocate final category values and atomically-ready completion state."""

    validate_completion(document)
    completed = deepcopy(document)
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
            if decision["decision"] != "new_category":
                continue
            value = next(value for value in range(101, 2**31) if value not in used)
            decision["allocated_value"] = value
            used.add(value)
    now = _timestamp(datetime.now(UTC))
    completed.update(status=COMPLETE, completed_at_utc=now, updated_at_utc=now)
    validate_review_file(completed, require_complete=True)
    return completed


def save_review_file(path: str | Path, document: dict[str, Any]) -> Path:
    """Validate then replace an existing review file atomically."""

    validate_review_file(document)
    destination = Path(path).expanduser().resolve()
    if not destination.is_file():
        raise ReviewFileError(f"review file does not exist: '{destination}'")
    _atomic_write(destination, document, overwrite=True)
    return destination


def update_and_save_review_file(path: str | Path, payload: object) -> dict[str, Any]:
    destination = Path(path).expanduser().resolve()
    updated = apply_review_edits(load_review_file(destination), payload)
    save_review_file(destination, updated)
    return updated


def complete_and_save_review_file(path: str | Path, payload: object) -> dict[str, Any]:
    destination = Path(path).expanduser().resolve()
    completed = complete_review_document(
        apply_review_edits(load_review_file(destination), payload)
    )
    _atomic_write(destination, completed, overwrite=True)
    return completed


def _apply_decisions(document: dict[str, Any], incoming: object) -> None:
    if not isinstance(incoming, list):
        raise ReviewFileError("review questions update must be an array")
    current = {question["question_id"]: question for question in document["questions"]}
    seen: set[str] = set()
    for update in incoming:
        if not isinstance(update, dict) or set(update) != {
            "question_id",
            "clusters",
            "unresolved_answers",
        }:
            raise ReviewFileError("question update has an invalid schema")
        question_id = update["question_id"]
        if question_id not in current or question_id in seen:
            raise ReviewFileError(
                "question update references an unknown or duplicate question"
            )
        seen.add(question_id)
        _apply_collection(
            current[question_id]["clusters"], update["clusters"], "cluster_id"
        )
        _apply_collection(
            current[question_id]["unresolved_answers"],
            update["unresolved_answers"],
            "processing_id",
        )
    if seen != set(current):
        raise ReviewFileError("review update must include every question")


def _apply_collection(
    current: list[dict[str, Any]], incoming: object, key: str
) -> None:
    if not isinstance(incoming, list):
        raise ReviewFileError("decision update must be an array")
    targets = {item[key]: item for item in current}
    seen: set[str] = set()
    for update in incoming:
        if (
            not isinstance(update, dict)
            or set(update) != {key, "analyst_decision"}
            or update[key] not in targets
            or update[key] in seen
        ):
            raise ReviewFileError(
                "decision update references unknown or duplicate evidence"
            )
        targets[update[key]]["analyst_decision"] = update["analyst_decision"]
        seen.add(update[key])
    if seen != set(targets):
        raise ReviewFileError("decision update must include every evidence item")


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
