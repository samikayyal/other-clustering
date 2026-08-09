"""Construction of immutable analysis evidence and the V4 review workspace."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from .domain import (
    CategoryDiscoveryResult,
    ClusterClassificationResult,
    WorkbookDataset,
)
from .errors import ReviewFileError
from .input_sources import canonical_google_sheets_url, is_google_sheets_url


def build_document(
    dataset: WorkbookDataset,
    discovery: CategoryDiscoveryResult,
    classification: ClusterClassificationResult,
    *,
    analysis_run_id: str,
    timestamp: str,
    source: dict[str, object],
) -> dict[str, Any]:
    """Project trusted stage results into the one canonical review representation."""

    answers_by_id = {answer.answer_id: answer for answer in dataset.answers}
    points_by_id = {point.processing_id: point for point in discovery.points}
    proposals_by_id = {
        proposal.cluster_id: proposal for proposal in classification.proposals
    }
    clusters_by_question: dict[str, list[Any]] = defaultdict(list)
    for cluster in discovery.proposed_clusters:
        clusters_by_question[cluster.question_id].append(cluster)

    questions: list[dict[str, Any]] = []
    for question in sorted(dataset.questions, key=lambda item: item.question_id):
        processing = sorted(
            (
                item
                for item in dataset.processing_answers
                if item.question_id == question.question_id
            ),
            key=lambda item: item.processing_id,
        )
        automatic_groups = [
            _automatic_group_entry(cluster, proposals_by_id[cluster.cluster_id])
            for cluster in sorted(
                clusters_by_question[question.question_id],
                key=lambda item: item.cluster_id,
            )
        ]
        clustered_ids = {
            member_id
            for group in automatic_groups
            for member_id in group["member_processing_ids"]
        }
        needs_attention = [
            item.processing_id
            for item in processing
            if item.processing_id not in clustered_ids
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
                "answers": [
                    _answer_entry(item, answers_by_id, points_by_id[item.processing_id])
                    for item in processing
                ],
                "automatic_groups": automatic_groups,
                "workspace": {
                    "active_groups": [
                        _active_group_entry(group, creation_order=index)
                        for index, group in enumerate(automatic_groups)
                    ],
                    "needs_attention": needs_attention,
                    "excluded_answers": [],
                    "retired_groups": [],
                    "history": [],
                    "undo": None,
                },
            }
        )
    warnings = [_dataset_warning(item) for item in sorted(dataset.warnings)]
    warnings.extend(
        sorted(
            classification.warnings, key=lambda item: (item["code"], item["message"])
        )
    )
    return {
        "schema_version": 4,
        "revision": 0,
        "analysis_run_id": analysis_run_id,
        "status": "in_review",
        "created_at_utc": timestamp,
        "updated_at_utc": timestamp,
        "completed_at_utc": None,
        "source_workbook": source,
        "questions": questions,
        "warnings": warnings,
    }


def source_identity(*, input_source: str, source_path: Path) -> dict[str, object]:
    """Fingerprint the exact workbook used by this analysis run."""

    try:
        payload = source_path.read_bytes()
    except OSError as exc:
        raise ReviewFileError(
            f"could not fingerprint analyzed source workbook '{source_path}': {exc}"
        ) from exc
    if source_path.suffix.casefold() != ".xlsx":
        raise ReviewFileError("analyzed source workbook must have an .xlsx filename")
    return {
        "input_kind": "google_sheets"
        if is_google_sheets_url(input_source)
        else "local_xlsx",
        "source_locator": canonical_google_sheets_url(input_source)
        if is_google_sheets_url(input_source)
        else str(source_path.resolve()),
        "display_name": source_path.name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _answer_entry(
    processing: Any, answers_by_id: dict[str, Any], point: Any
) -> dict[str, Any]:
    rows = []
    for answer_id in sorted(processing.answer_ids):
        answer = answers_by_id[answer_id]
        cell = answer.source_cell
        rows.append(
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
        "row_mappings": rows,
        "discovery_evidence": {
            "raw_cluster_label": point.raw_cluster_label,
            "membership_probability": point.membership_probability,
            "status": point.status,
            "cluster_id": point.cluster_id,
        },
    }


def _automatic_group_entry(cluster: Any, proposal: Any) -> dict[str, Any]:
    return {
        "group_id": cluster.cluster_id,
        "raw_cluster_label": cluster.raw_cluster_label,
        "member_processing_ids": sorted(cluster.processing_ids),
        "provider_proposal": {
            "decision": proposal.decision,
            "selected_choice_value": proposal.selected_choice_value,
            "english_label": proposal.english_label,
            "arabic_label": proposal.arabic_label,
            "rejection_reason": proposal.rejection_reason,
            "provider_error": proposal.provider_error,
        },
    }


def _active_group_entry(
    automatic_group: dict[str, Any], *, creation_order: int
) -> dict[str, Any]:
    proposal = automatic_group["provider_proposal"]
    decision = None
    if proposal["decision"] in {"existing_choice", "new_category"}:
        decision = {
            "decision": proposal["decision"],
            "selected_choice_value": proposal["selected_choice_value"],
            "english_label": proposal["english_label"],
            "arabic_label": proposal["arabic_label"],
        }
    return {
        "group_id": automatic_group["group_id"],
        "origin": "automatic",
        "creation_order": creation_order,
        "member_processing_ids": list(automatic_group["member_processing_ids"]),
        "decision": decision,
        "review_state": "needs_review",
    }


def _dataset_warning(message: str) -> dict[str, str | None]:
    return {"code": "workbook_warning", "message": message, "source_cell": None}
