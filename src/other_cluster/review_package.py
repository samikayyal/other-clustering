"""Build and write the version-1 Feature 05 analyst review package."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .domain import (
    CategoryDiscoveryResult,
    CategoryLabelingResult,
    ExistingChoiceAssignmentResult,
    ProposedCategory,
    ReviewPackageResult,
    WorkbookDataset,
)
from .errors import ReviewPackageError
from .input_sources import canonical_google_sheets_url, is_google_sheets_url


def write_review_package(
    dataset: WorkbookDataset,
    assignments: ExistingChoiceAssignmentResult,
    discovery: CategoryDiscoveryResult,
    labeling: CategoryLabelingResult,
    *,
    input_source: str,
    source_path: Path,
    output_directory: Path,
    analysis_run_id: str | None = None,
    created_at_utc: datetime | None = None,
) -> ReviewPackageResult:
    """Validate a complete package and write it once as UTF-8 JSON."""

    run_id = analysis_run_id or str(uuid.uuid4())
    _validate_run_id(run_id)
    source = _source_identity(input_source=input_source, source_path=source_path)
    package = _build_package(
        dataset,
        assignments,
        discovery,
        labeling,
        analysis_run_id=run_id,
        created_at_utc=created_at_utc,
        source=source,
    )
    item_counts = _validate_package(package)
    destination = _package_path(output_directory, source["display_name"], run_id)
    _write_package(destination, package)
    return ReviewPackageResult(
        package_path=destination.resolve(),
        analysis_run_id=run_id,
        source_sha256=str(source["sha256"]),
        item_counts=dict(sorted(item_counts.items())),
    )


def _source_identity(*, input_source: str, source_path: Path) -> dict[str, object]:
    try:
        payload = source_path.read_bytes()
    except OSError as exc:
        raise ReviewPackageError(
            f"could not fingerprint analyzed source workbook '{source_path}': {exc}"
        ) from exc
    if source_path.suffix.casefold() != ".xlsx":
        raise ReviewPackageError("analyzed source workbook must have an .xlsx filename")
    if is_google_sheets_url(input_source):
        input_kind = "google_sheets"
        source_locator = canonical_google_sheets_url(input_source)
    else:
        input_kind = "local_xlsx"
        source_locator = str(source_path.resolve())
    return {
        "input_kind": input_kind,
        "source_locator": source_locator,
        "display_name": source_path.name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _build_package(
    dataset: WorkbookDataset,
    assignments: ExistingChoiceAssignmentResult,
    discovery: CategoryDiscoveryResult,
    labeling: CategoryLabelingResult,
    *,
    analysis_run_id: str,
    created_at_utc: datetime | None,
    source: dict[str, object],
) -> dict[str, object]:
    questions = sorted(dataset.questions, key=lambda item: item.question_id)
    processing_by_id = {item.processing_id: item for item in dataset.processing_answers}
    answers_by_id = {item.answer_id: item for item in dataset.answers}
    verifications = {item.processing_id: item for item in assignments.verifications}
    points_by_id = {item.processing_id: item for item in discovery.points}
    decisions_by_cluster = {item.cluster_id: item for item in labeling.decisions}
    if len(verifications) != len(assignments.verifications):
        raise ReviewPackageError(
            "existing-choice verifications contain duplicate processing IDs"
        )
    if len(points_by_id) != len(discovery.points):
        raise ReviewPackageError("discovery evidence contains duplicate processing IDs")
    if len(decisions_by_cluster) != len(labeling.decisions):
        raise ReviewPackageError("label decisions contain duplicate cluster IDs")
    _validate_evidence_identity(processing_by_id, verifications, points_by_id)
    categories_by_question: dict[str, list[ProposedCategory]] = {}
    for category in labeling.proposed_categories:
        categories_by_question.setdefault(category.question_id, []).append(category)
    _validate_labeling_handoff(labeling, categories_by_question)

    question_entries: list[dict[str, object]] = []
    for question in questions:
        question_processing = sorted(
            (
                item
                for item in dataset.processing_answers
                if item.question_id == question.question_id
            ),
            key=lambda item: item.processing_id,
        )
        answers = [
            _answer_entry(
                processing,
                answers_by_id=answers_by_id,
                point=points_by_id.get(processing.processing_id),
                verification=verifications.get(processing.processing_id),
            )
            for processing in question_processing
        ]
        existing_assignments = _existing_assignment_entries(
            question.question_id,
            verifications,
        )
        categories = [
            {
                "review_item_id": f"proposed_category:{category.cluster_id}",
                "cluster_id": category.cluster_id,
                "proposed_value": category.proposed_value,
                "english_label": category.english_label,
                "arabic_label": category.arabic_label,
                "member_processing_ids": list(category.member_processing_ids),
            }
            for category in sorted(
                categories_by_question.get(question.question_id, []),
                key=lambda item: item.cluster_id,
            )
        ]
        merge_suggestions = _merge_entries(discovery, question.question_id)
        unresolved = _unresolved_entries(
            question_processing,
            verifications=verifications,
            points_by_id=points_by_id,
            decisions_by_cluster=decisions_by_cluster,
        )
        question_entries.append(
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
                        question.choices,
                        key=lambda item: (item.value, item.code_row),
                    )
                ],
                "answers": answers,
                "existing_choice_assignments": existing_assignments,
                "proposed_categories": categories,
                "merge_suggestions": merge_suggestions,
                "unresolved_answers": unresolved,
            }
        )
    timestamp = created_at_utc or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ReviewPackageError("created_at_utc must include a timezone")
    created = (
        timestamp.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return {
        "schema_version": 1,
        "analysis_run_id": analysis_run_id,
        "created_at_utc": created,
        "source_workbook": source,
        "questions": question_entries,
        "warnings": _warning_entries(dataset),
    }


def _validate_evidence_identity(processing_by_id, verifications, points_by_id) -> None:
    for processing_id, verification in verifications.items():
        processing = processing_by_id.get(processing_id)
        if processing is None or processing.question_id != verification.question_id:
            raise ReviewPackageError(
                f"existing-choice verification has invalid processing ID '{processing_id}'"
            )
    for processing_id, point in points_by_id.items():
        processing = processing_by_id.get(processing_id)
        if processing is None or processing.question_id != point.question_id:
            raise ReviewPackageError(
                f"discovery evidence has invalid processing ID '{processing_id}'"
            )


def _validate_labeling_handoff(
    labeling: CategoryLabelingResult,
    categories_by_question: dict[str, list[ProposedCategory]],
) -> None:
    categories_by_cluster = {
        category.cluster_id
        for categories in categories_by_question.values()
        for category in categories
    }
    if len(categories_by_cluster) != sum(
        len(categories) for categories in categories_by_question.values()
    ):
        raise ReviewPackageError("proposed categories contain duplicate cluster IDs")
    for decision in labeling.decisions:
        has_category = decision.cluster_id in categories_by_cluster
        if decision.decision == "label" and not has_category:
            raise ReviewPackageError(
                f"labeled cluster '{decision.cluster_id}' is missing its proposed category"
            )
        if decision.decision == "reject" and has_category:
            raise ReviewPackageError(
                f"rejected cluster '{decision.cluster_id}' must not have a proposed category"
            )
        if decision.decision not in {"label", "reject"}:
            raise ReviewPackageError(
                f"cluster '{decision.cluster_id}' has an invalid label decision"
            )


def _answer_entry(
    processing, *, answers_by_id, point, verification
) -> dict[str, object]:
    row_mappings = []
    for answer_id in sorted(processing.answer_ids):
        answer = answers_by_id.get(answer_id)
        if answer is None:
            raise ReviewPackageError(
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
    discovery_evidence = {
        "raw_cluster_label": None,
        "membership_probability": None,
        "status": None,
        "cluster_id": None,
    }
    if point is not None:
        discovery_evidence = {
            "raw_cluster_label": point.raw_cluster_label,
            "membership_probability": point.membership_probability,
            "status": point.status,
            "cluster_id": point.cluster_id,
        }
    if verification is None and point is None:
        raise ReviewPackageError(
            f"processing answer '{processing.processing_id}' is missing assignment and discovery evidence"
        )
    return {
        "processing_id": processing.processing_id,
        "text": processing.text,
        "occurrence_count": processing.occurrence_count,
        "row_mappings": row_mappings,
        "discovery_evidence": discovery_evidence,
    }


def _existing_assignment_entries(
    question_id: str, verifications
) -> list[dict[str, object]]:
    entries = []
    for verification in sorted(
        verifications.values(), key=lambda item: item.processing_id
    ):
        if verification.question_id != question_id or verification.status != "assigned":
            continue
        if verification.selected_choice_value is None:
            raise ReviewPackageError(
                f"assigned processing answer '{verification.processing_id}' has no choice value"
            )
        entries.append(
            {
                "review_item_id": f"existing_assignment:{verification.processing_id}",
                "processing_id": verification.processing_id,
                "proposed_choice_value": verification.selected_choice_value,
                "provider_decision": "assign",
            }
        )
    return entries


def _merge_entries(
    discovery: CategoryDiscoveryResult, question_id: str
) -> list[dict[str, object]]:
    entries = []
    for suggestion in sorted(
        (
            item
            for item in discovery.merge_suggestions
            if item.question_id == question_id
        ),
        key=lambda item: (item.first_cluster_id, item.second_cluster_id),
    ):
        entries.append(
            {
                "review_item_id": (
                    f"merge:{suggestion.first_cluster_id}:{suggestion.second_cluster_id}"
                ),
                "first_cluster_id": suggestion.first_cluster_id,
                "second_cluster_id": suggestion.second_cluster_id,
                "cosine_similarity": suggestion.cosine_similarity,
                "combined_member_processing_ids": sorted(
                    set(suggestion.first_processing_ids)
                    | set(suggestion.second_processing_ids)
                ),
            }
        )
    return entries


def _unresolved_entries(
    processing_answers,
    *,
    verifications,
    points_by_id,
    decisions_by_cluster,
) -> list[dict[str, object]]:
    entries = []
    for processing in processing_answers:
        verification = verifications.get(processing.processing_id)
        if verification is not None and verification.status == "assigned":
            continue
        point = points_by_id.get(processing.processing_id)
        if point is None:
            raise ReviewPackageError(
                f"unassigned processing answer '{processing.processing_id}' is missing discovery evidence"
            )
        reason = point.status
        if point.status == "accepted_cluster":
            if point.cluster_id is None:
                raise ReviewPackageError(
                    f"accepted discovery answer '{processing.processing_id}' has no cluster ID"
                )
            decision = decisions_by_cluster.get(point.cluster_id)
            if decision is None:
                raise ReviewPackageError(
                    f"accepted cluster '{point.cluster_id}' is missing its label decision"
                )
            if decision.decision == "label":
                continue
            if decision.rejection_reason is None:
                raise ReviewPackageError(
                    f"rejected cluster '{point.cluster_id}' has no rejection reason"
                )
            reason = f"label_rejected_{decision.rejection_reason}"
        entries.append(
            {
                "review_item_id": f"unresolved:{processing.processing_id}",
                "processing_id": processing.processing_id,
                "reason": reason,
                "cluster_id": point.cluster_id,
            }
        )
    return entries


def _warning_entries(dataset: WorkbookDataset) -> list[dict[str, object]]:
    return [
        {"code": "workbook_warning", "message": warning, "source_cell": None}
        for warning in sorted(dataset.warnings)
    ]


def _validate_package(package: dict[str, object]) -> Counter[str]:
    if set(package) != {
        "schema_version",
        "analysis_run_id",
        "created_at_utc",
        "source_workbook",
        "questions",
        "warnings",
    }:
        raise ReviewPackageError("review package has an invalid top-level schema")
    review_item_ids: set[str] = set()
    category_values: set[int] = set()
    counts: Counter[str] = Counter()
    for question in package["questions"]:
        if not isinstance(question, dict):
            raise ReviewPackageError("review package questions must be objects")
        processing_ids = {item["processing_id"] for item in question["answers"]}
        answer_ids = {
            mapping["answer_id"]
            for answer in question["answers"]
            for mapping in answer["row_mappings"]
        }
        if sum(item["occurrence_count"] for item in question["answers"]) != len(
            answer_ids
        ):
            raise ReviewPackageError(
                f"question '{question['question_id']}' has inconsistent answer occurrence counts"
            )
        cluster_ids = {
            item["cluster_id"] for item in question["proposed_categories"]
        } | {
            evidence["cluster_id"]
            for answer in question["answers"]
            if (evidence := answer["discovery_evidence"])["cluster_id"] is not None
        }
        for category in question["proposed_categories"]:
            value = category["proposed_value"]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 100:
                raise ReviewPackageError(
                    "proposed category values must be integers greater than 100"
                )
            if value in category_values:
                raise ReviewPackageError(f"duplicate proposed category value {value}")
            category_values.add(value)
            if not set(category["member_processing_ids"]) <= processing_ids:
                raise ReviewPackageError(
                    "proposed category references a processing ID outside its question"
                )
        for collection_name in (
            "existing_choice_assignments",
            "proposed_categories",
            "merge_suggestions",
            "unresolved_answers",
        ):
            for item in question[collection_name]:
                review_item_id = item["review_item_id"]
                if review_item_id in review_item_ids:
                    raise ReviewPackageError(
                        f"duplicate review item ID '{review_item_id}'"
                    )
                review_item_ids.add(review_item_id)
                counts[collection_name] += 1
        for item in (
            question["existing_choice_assignments"] + question["unresolved_answers"]
        ):
            if item["processing_id"] not in processing_ids:
                raise ReviewPackageError(
                    "review item references a processing ID outside its question"
                )
        for item in question["merge_suggestions"]:
            if (
                item["first_cluster_id"] not in cluster_ids
                or item["second_cluster_id"] not in cluster_ids
            ):
                raise ReviewPackageError(
                    "merge suggestion references an unknown cluster"
                )
            if not set(item["combined_member_processing_ids"]) <= processing_ids:
                raise ReviewPackageError(
                    "merge suggestion references a processing ID outside its question"
                )
    counts["questions"] = len(package["questions"])
    counts["answers"] = sum(len(item["answers"]) for item in package["questions"])
    return counts


def _package_path(output_directory: Path, display_name: object, run_id: str) -> Path:
    if not isinstance(display_name, str):
        raise ReviewPackageError("source workbook display name must be a string")
    stem = (
        display_name[:-5] if display_name.casefold().endswith(".xlsx") else display_name
    )
    normalized_stem = re.sub(r"\s+", "_", stem.casefold())
    return output_directory / f"{normalized_stem}_{run_id}_review.json"


def _write_package(destination: Path, package: dict[str, object]) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReviewPackageError(
            f"could not create review package directory '{destination.parent}': {exc}"
        ) from exc
    content = json.dumps(package, ensure_ascii=False, indent=2) + "\n"
    created = False
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as package_file:
            created = True
            package_file.write(content)
            package_file.flush()
            os.fsync(package_file.fileno())
    except FileExistsError as exc:
        raise ReviewPackageError(
            f"review package filename collision: '{destination}'"
        ) from exc
    except OSError as exc:
        if created:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise ReviewPackageError(
            f"could not write review package '{destination}': {exc}"
        ) from exc


def _validate_run_id(value: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ReviewPackageError("analysis_run_id must be a UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ReviewPackageError("analysis_run_id must be a lowercase UUIDv4")
