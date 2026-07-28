"""Feature 06 draft persistence, approval validation, and approval generation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .category_labeling import validate_analyst_label_pair
from .errors import AnalystReviewError, CategoryLabelingError, ReviewPackageError
from .review_package import _validate_package

_DISPOSITIONS = {
    "existing_assignment": {"approved", "rejected", "overridden"},
    "proposed_category": {"approved", "rejected", "modified", "merged", "split"},
    "merge": {"approved", "rejected"},
    "unresolved": {"acknowledged", "assigned"},
}
_CATEGORY_ORIGINS = {"proposed", "modified", "merged", "split", "manual"}
_ANSWER_DECISIONS = {"existing_choice", "new_category", "unresolved"}
_DRAFT_FIELDS = {
    "schema_version",
    "analysis_run_id",
    "review_package_sha256",
    "analyst_name",
    "saved_at_utc",
    "next_category_sequence",
    "review_item_dispositions",
    "questions",
}
_DRAFT_QUESTION_FIELDS = {
    "question_id",
    "categories",
    "answer_dispositions",
}
_DRAFT_CATEGORY_FIELDS = {
    "final_category_id",
    "origin",
    "english_label",
    "arabic_label",
    "component_cluster_ids",
    "member_processing_ids",
    "creation_sequence",
}
_ANSWER_FIELDS = {
    "processing_id",
    "decision",
    "choice_value",
    "final_category_id",
    "unresolved_reason",
}
_ITEM_FIELDS = {"review_item_id", "disposition", "note"}


@dataclass(frozen=True, slots=True)
class LoadedReviewPackage:
    """An immutable review package plus the identity derived from its bytes."""

    path: Path
    package: dict[str, Any]
    sha256: str
    normalized_source_stem: str


def load_review_package(path: Path) -> LoadedReviewPackage:
    """Load and validate an immutable Feature 05 review package."""

    resolved = path.resolve()
    if not resolved.is_file():
        raise AnalystReviewError(
            f"review package must be an existing regular file: '{resolved}'"
        )
    try:
        raw = resolved.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise AnalystReviewError("review package must not contain a UTF-8 BOM")
        package = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise AnalystReviewError("review package must be valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise AnalystReviewError(f"review package is not valid JSON: {exc}") from exc
    if not isinstance(package, dict):
        raise AnalystReviewError("review package must contain one JSON object")
    if raw != _json_bytes(package):
        raise AnalystReviewError(
            "review package does not match the required UTF-8 JSON serialization"
        )
    try:
        _validate_review_package_shape(package)
        _validate_package(package)
    except (KeyError, TypeError, ReviewPackageError) as exc:
        raise AnalystReviewError(f"invalid review package: {exc}") from exc
    display_name = package["source_workbook"]["display_name"]
    source_stem = display_name[:-5]
    normalized = re.sub(r"\s+", "_", source_stem.casefold())
    return LoadedReviewPackage(
        path=resolved,
        package=package,
        sha256=hashlib.sha256(raw).hexdigest(),
        normalized_source_stem=normalized,
    )


def create_initial_draft(loaded: LoadedReviewPackage) -> dict[str, Any]:
    """Create a complete final-state starting point with undecided review items."""

    package = loaded.package
    question_states: list[dict[str, Any]] = []
    for question in package["questions"]:
        categories = [
            {
                "final_category_id": f"proposed:{item['cluster_id']}",
                "origin": "proposed",
                "english_label": item["english_label"],
                "arabic_label": item["arabic_label"],
                "component_cluster_ids": [item["cluster_id"]],
                "member_processing_ids": list(item["member_processing_ids"]),
                "creation_sequence": None,
            }
            for item in question["proposed_categories"]
        ]
        category_by_processing = {
            processing_id: category["final_category_id"]
            for category in categories
            for processing_id in category["member_processing_ids"]
        }
        existing_by_processing = {
            item["processing_id"]: item["proposed_choice_value"]
            for item in question["existing_choice_assignments"]
        }
        unresolved_by_processing = {
            item["processing_id"]: item["reason"]
            for item in question["unresolved_answers"]
        }
        answer_dispositions = []
        for answer in question["answers"]:
            processing_id = answer["processing_id"]
            if processing_id in existing_by_processing:
                decision = {
                    "processing_id": processing_id,
                    "decision": "existing_choice",
                    "choice_value": existing_by_processing[processing_id],
                    "final_category_id": None,
                    "unresolved_reason": None,
                }
            elif processing_id in category_by_processing:
                decision = {
                    "processing_id": processing_id,
                    "decision": "new_category",
                    "choice_value": None,
                    "final_category_id": category_by_processing[processing_id],
                    "unresolved_reason": None,
                }
            else:
                decision = {
                    "processing_id": processing_id,
                    "decision": "unresolved",
                    "choice_value": None,
                    "final_category_id": None,
                    "unresolved_reason": unresolved_by_processing[processing_id],
                }
            answer_dispositions.append(decision)
        question_states.append(
            {
                "question_id": question["question_id"],
                "categories": categories,
                "answer_dispositions": answer_dispositions,
            }
        )
    return {
        "schema_version": 1,
        "analysis_run_id": package["analysis_run_id"],
        "review_package_sha256": loaded.sha256,
        "analyst_name": "",
        "saved_at_utc": None,
        "next_category_sequence": 1,
        "review_item_dispositions": [
            {
                "review_item_id": review_item_id,
                "disposition": None,
                "note": None,
            }
            for review_item_id, _ in _review_items(package)
        ],
        "questions": question_states,
    }


def draft_path(loaded: LoadedReviewPackage, state_directory: Path) -> Path:
    """Return the package-bound draft path."""

    return state_directory / (
        f"{loaded.normalized_source_stem}_{loaded.package['analysis_run_id']}_draft.json"
    )


def approval_path(loaded: LoadedReviewPackage, approval_directory: Path) -> Path:
    """Return the immutable approval path."""

    return approval_directory / (
        f"{loaded.normalized_source_stem}_{loaded.package['analysis_run_id']}"
        "_approval.json"
    )


def load_or_create_draft(
    loaded: LoadedReviewPackage, state_directory: Path
) -> dict[str, Any]:
    """Resume the exact package-bound draft, or create its initial state."""

    destination = draft_path(loaded, state_directory)
    if not destination.exists():
        return create_initial_draft(loaded)
    try:
        draft = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalystReviewError(
            f"could not load review draft '{destination}': {exc}"
        ) from exc
    validate_draft(loaded, draft, require_complete=False)
    return draft


def save_draft(
    loaded: LoadedReviewPackage,
    draft: dict[str, Any],
    state_directory: Path,
    *,
    saved_at_utc: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    """Validate and atomically persist the latest accepted analyst state."""

    candidate = deepcopy(draft)
    timestamp = saved_at_utc or datetime.now(UTC)
    candidate["saved_at_utc"] = _utc_timestamp(timestamp)
    validate_draft(loaded, candidate, require_complete=False)
    destination = draft_path(loaded, state_directory)
    _atomic_json_write(destination, candidate)
    return candidate, destination.resolve()


def add_analyst_category(
    loaded: LoadedReviewPackage,
    draft: dict[str, Any],
    *,
    question_id: str,
    english_label: str,
    arabic_label: str,
    origin: str = "manual",
    component_cluster_ids: list[str] | None = None,
    member_processing_ids: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Add a complete, valid analyst category to an in-progress draft."""

    candidate = deepcopy(draft)
    if origin not in {"manual", "split", "merged"}:
        raise AnalystReviewError("analyst-created category origin is invalid")
    question = _draft_question(candidate, question_id)
    members = list(member_processing_ids or ())
    if (
        not members
        or len(members) != len(set(members))
        or not all(isinstance(item, str) and item for item in members)
    ):
        raise AnalystReviewError(
            "analyst category must contain unique processing answer IDs"
        )
    answers_by_id = {
        item["processing_id"]: item for item in question["answer_dispositions"]
    }
    if not set(members) <= set(answers_by_id):
        raise AnalystReviewError(
            "analyst category references a processing answer outside its question"
        )
    sequence = candidate["next_category_sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise AnalystReviewError("next_category_sequence must be a positive integer")
    category_id = f"analyst-category:{sequence:04d}"
    candidate["next_category_sequence"] = sequence + 1
    question["categories"].append(
        {
            "final_category_id": category_id,
            "origin": origin,
            "english_label": english_label,
            "arabic_label": arabic_label,
            "component_cluster_ids": list(component_cluster_ids or ()),
            "member_processing_ids": sorted(members),
            "creation_sequence": sequence,
        }
    )
    for category in question["categories"]:
        if category["final_category_id"] != category_id:
            category["member_processing_ids"] = [
                item
                for item in category["member_processing_ids"]
                if item not in members
            ]
    question["categories"] = [
        item for item in question["categories"] if item["member_processing_ids"]
    ]
    for processing_id in members:
        answers_by_id[processing_id].update(
            decision="new_category",
            choice_value=None,
            final_category_id=category_id,
            unresolved_reason=None,
        )
    _normalize_category_origins(loaded.package, question)
    validate_draft(loaded, candidate, require_complete=False)
    return candidate, category_id


def validate_draft(
    loaded: LoadedReviewPackage,
    draft: object,
    *,
    require_complete: bool,
) -> None:
    """Validate package binding, current final state, and optional completeness."""

    if not isinstance(draft, dict) or set(draft) != _DRAFT_FIELDS:
        raise AnalystReviewError("draft has an invalid top-level schema")
    if draft["schema_version"] != 1:
        raise AnalystReviewError("draft schema_version must be 1")
    if draft["analysis_run_id"] != loaded.package["analysis_run_id"]:
        raise AnalystReviewError("draft belongs to a different analysis run")
    if draft["review_package_sha256"] != loaded.sha256:
        raise AnalystReviewError("draft review-package SHA-256 does not match")
    if not isinstance(draft["analyst_name"], str):
        raise AnalystReviewError("draft analyst_name must be a string")
    if draft["saved_at_utc"] is not None:
        _require_utc_timestamp(draft["saved_at_utc"], "saved_at_utc")
    next_sequence = draft["next_category_sequence"]
    if (
        not isinstance(next_sequence, int)
        or isinstance(next_sequence, bool)
        or next_sequence < 1
    ):
        raise AnalystReviewError("next_category_sequence must be a positive integer")
    _validate_review_item_dispositions(
        loaded.package,
        draft["review_item_dispositions"],
        require_complete=require_complete,
    )
    if not isinstance(draft["questions"], list):
        raise AnalystReviewError("draft questions must be an array")
    package_questions = {
        item["question_id"]: item for item in loaded.package["questions"]
    }
    draft_question_ids = [
        item.get("question_id") if isinstance(item, dict) else None
        for item in draft["questions"]
    ]
    if draft_question_ids != list(package_questions):
        raise AnalystReviewError(
            "draft questions must match review-package order and identity"
        )
    category_ids: set[str] = set()
    creation_sequences: set[int] = set()
    for state in draft["questions"]:
        if set(state) != _DRAFT_QUESTION_FIELDS:
            raise AnalystReviewError("draft question has an invalid schema")
        _validate_question_state(
            package_questions[state["question_id"]],
            state,
            category_ids=category_ids,
            creation_sequences=creation_sequences,
        )
    if creation_sequences and next_sequence <= max(creation_sequences):
        raise AnalystReviewError(
            "next_category_sequence must exceed every created category sequence"
        )
    if require_complete:
        if not draft["analyst_name"].strip():
            raise AnalystReviewError("analyst name is required to complete review")
        _validate_completed_dispositions(loaded.package, draft)


def complete_review(
    loaded: LoadedReviewPackage,
    draft: dict[str, Any],
    approval_directory: Path,
    *,
    approval_id: str | None = None,
    approved_at_utc: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    """Validate the complete draft and write one immutable approval artifact."""

    validate_draft(loaded, draft, require_complete=True)
    final_values = _allocate_final_values(loaded.package, draft)
    questions = []
    for package_question, state in zip(
        loaded.package["questions"], draft["questions"], strict=True
    ):
        categories = []
        for category in _ordered_categories(state["categories"], final_values):
            categories.append(
                {
                    "final_category_id": category["final_category_id"],
                    "origin": category["origin"],
                    "value": final_values[category["final_category_id"]],
                    "english_label": " ".join(category["english_label"].split()),
                    "arabic_label": " ".join(category["arabic_label"].split()),
                    "component_cluster_ids": sorted(category["component_cluster_ids"]),
                    "member_processing_ids": sorted(category["member_processing_ids"]),
                }
            )
        answers = sorted(
            deepcopy(state["answer_dispositions"]),
            key=lambda item: item["processing_id"],
        )
        questions.append(
            {
                "question_id": state["question_id"],
                "final_categories": categories,
                "answer_dispositions": answers,
                "analyst_overrides": _derive_overrides(
                    package_question, categories, answers
                ),
            }
        )
    generated_id = approval_id or str(uuid.uuid4())
    _require_uuid4(generated_id, "approval_id")
    approval = {
        "schema_version": 1,
        "approval_id": generated_id,
        "analysis_run_id": loaded.package["analysis_run_id"],
        "review_package_sha256": loaded.sha256,
        "source_workbook": deepcopy(loaded.package["source_workbook"]),
        "analyst": {"name": draft["analyst_name"].strip()},
        "approved_at_utc": _utc_timestamp(approved_at_utc or datetime.now(UTC)),
        "review_item_dispositions": deepcopy(draft["review_item_dispositions"]),
        "questions": questions,
        "complete_review_confirmed": True,
        "authorize_finalization": True,
    }
    destination = approval_path(loaded, approval_directory)
    _exclusive_json_write(destination, approval)
    return approval, destination.resolve()


def _validate_review_package_shape(package: dict[str, Any]) -> None:
    if set(package) != {
        "schema_version",
        "analysis_run_id",
        "created_at_utc",
        "source_workbook",
        "questions",
        "warnings",
    }:
        raise ReviewPackageError("review package has an invalid top-level schema")
    if package["schema_version"] != 1:
        raise ReviewPackageError("review package schema_version must be 1")
    _require_uuid4(package["analysis_run_id"], "analysis_run_id")
    _require_utc_timestamp(package["created_at_utc"], "created_at_utc")
    source = package["source_workbook"]
    if not isinstance(source, dict) or set(source) != {
        "input_kind",
        "source_locator",
        "display_name",
        "size_bytes",
        "sha256",
    }:
        raise ReviewPackageError("source_workbook has an invalid schema")
    if source["input_kind"] not in {"local_xlsx", "google_sheets"}:
        raise ReviewPackageError("source_workbook input_kind is invalid")
    if (
        not isinstance(source["source_locator"], str)
        or not isinstance(source["display_name"], str)
        or not source["display_name"].casefold().endswith(".xlsx")
    ):
        raise ReviewPackageError("source_workbook locator or display name is invalid")
    if (
        source["input_kind"] == "local_xlsx"
        and not Path(source["source_locator"]).is_absolute()
    ):
        raise ReviewPackageError("local source_workbook locator must be absolute")
    if source["input_kind"] == "google_sheets" and not re.fullmatch(
        r"https://docs\.google\.com/spreadsheets/d/[^/?#]+",
        source["source_locator"],
    ):
        raise ReviewPackageError(
            "Google Sheets source_workbook locator must be canonical"
        )
    if (
        not isinstance(source["size_bytes"], int)
        or isinstance(source["size_bytes"], bool)
        or source["size_bytes"] < 0
    ):
        raise ReviewPackageError("source_workbook size_bytes is invalid")
    if not isinstance(source["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", source["sha256"]
    ):
        raise ReviewPackageError("source_workbook sha256 is invalid")
    if not isinstance(package["questions"], list) or not isinstance(
        package["warnings"], list
    ):
        raise ReviewPackageError("review package arrays are invalid")
    question_ids = []
    for question in package["questions"]:
        _validate_review_question_shape(question)
        question_ids.append(question["question_id"])
    if question_ids != sorted(question_ids) or len(question_ids) != len(
        set(question_ids)
    ):
        raise ReviewPackageError(
            "review package questions must have unique sorted question IDs"
        )
    warning_keys = []
    for warning in package["warnings"]:
        if not isinstance(warning, dict) or set(warning) != {
            "code",
            "message",
            "source_cell",
        }:
            raise ReviewPackageError("review warning has an invalid schema")
        if (
            not isinstance(warning["code"], str)
            or not warning["code"]
            or not isinstance(warning["message"], str)
            or not warning["message"]
            or (
                warning["source_cell"] is not None
                and not isinstance(warning["source_cell"], str)
            )
        ):
            raise ReviewPackageError("review warning has invalid field values")
        warning_keys.append(
            (warning["code"], warning["source_cell"] or "", warning["message"])
        )
    if warning_keys != sorted(warning_keys):
        raise ReviewPackageError("review warnings must use deterministic order")


def _validate_review_question_shape(question: object) -> None:
    if not isinstance(question, dict) or set(question) != {
        "question_id",
        "question_text",
        "source_column",
        "existing_choices",
        "answers",
        "existing_choice_assignments",
        "proposed_categories",
        "merge_suggestions",
        "unresolved_answers",
    }:
        raise ReviewPackageError("review question has an invalid schema")
    if (
        not isinstance(question["question_id"], str)
        or not question["question_id"]
        or not isinstance(question["source_column"], str)
        or not question["source_column"]
    ):
        raise ReviewPackageError("review question identity is invalid")
    text = question["question_text"]
    if (
        not isinstance(text, dict)
        or set(text) != {"english", "arabic"}
        or not all(isinstance(text[item], str) and text[item] for item in text)
    ):
        raise ReviewPackageError("review question text is invalid")
    collections = (
        "existing_choices",
        "answers",
        "existing_choice_assignments",
        "proposed_categories",
        "merge_suggestions",
        "unresolved_answers",
    )
    if any(not isinstance(question[item], list) for item in collections):
        raise ReviewPackageError("review question collections must be arrays")
    for choice in question["existing_choices"]:
        if not isinstance(choice, dict) or set(choice) != {
            "value",
            "english_label",
            "arabic_label",
            "code_row",
        }:
            raise ReviewPackageError("existing choice has an invalid schema")
        if (
            not _is_integer(choice["value"])
            or not _is_integer(choice["code_row"])
            or choice["code_row"] < 1
            or not isinstance(choice["english_label"], str)
            or not choice["english_label"]
            or not isinstance(choice["arabic_label"], str)
            or not choice["arabic_label"]
        ):
            raise ReviewPackageError("existing choice has invalid field values")
    if [
        (item["value"], item["code_row"]) for item in question["existing_choices"]
    ] != sorted(
        (item["value"], item["code_row"]) for item in question["existing_choices"]
    ):
        raise ReviewPackageError("existing choices must use deterministic order")
    processing_ids = []
    answer_ids: set[str] = set()
    for answer in question["answers"]:
        if not isinstance(answer, dict) or set(answer) != {
            "processing_id",
            "text",
            "occurrence_count",
            "row_mappings",
            "discovery_evidence",
        }:
            raise ReviewPackageError("review answer has an invalid schema")
        if (
            not isinstance(answer["processing_id"], str)
            or not answer["processing_id"]
            or not isinstance(answer["text"], str)
            or not answer["text"]
            or not _is_integer(answer["occurrence_count"])
            or answer["occurrence_count"] < 1
            or not isinstance(answer["row_mappings"], list)
        ):
            raise ReviewPackageError("review answer has invalid field values")
        processing_ids.append(answer["processing_id"])
        row_ids = []
        for mapping in answer["row_mappings"]:
            if not isinstance(mapping, dict) or set(mapping) != {
                "answer_id",
                "respondent_key",
                "sheet",
                "row",
                "column",
                "coordinate",
            }:
                raise ReviewPackageError("row mapping has an invalid schema")
            if (
                not all(
                    isinstance(mapping[item], str) and mapping[item]
                    for item in ("answer_id", "respondent_key", "sheet", "coordinate")
                )
                or not _is_integer(mapping["row"])
                or mapping["row"] < 1
                or not _is_integer(mapping["column"])
                or mapping["column"] < 1
                or mapping["answer_id"] in answer_ids
            ):
                raise ReviewPackageError("row mapping has invalid field values")
            answer_ids.add(mapping["answer_id"])
            row_ids.append(mapping["answer_id"])
        if row_ids != sorted(row_ids) or len(row_ids) != answer["occurrence_count"]:
            raise ReviewPackageError(
                "row mappings must be sorted and match occurrence_count"
            )
        evidence = answer["discovery_evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {
            "raw_cluster_label",
            "membership_probability",
            "status",
            "cluster_id",
        }:
            raise ReviewPackageError("discovery evidence has an invalid schema")
        status = evidence["status"]
        if status is None:
            if any(value is not None for value in evidence.values()):
                raise ReviewPackageError(
                    "pre-discovery assignment evidence must be entirely null"
                )
        else:
            if status not in {
                "rare_insufficient_distinct_texts",
                "noise",
                "low_probability",
                "rejected_cluster",
                "accepted_cluster",
            }:
                raise ReviewPackageError("discovery evidence status is invalid")
            probability = evidence["membership_probability"]
            if probability is not None and (
                not _is_number(probability) or not 0 <= probability <= 1
            ):
                raise ReviewPackageError("discovery membership_probability is invalid")
            if evidence["raw_cluster_label"] is not None and not _is_integer(
                evidence["raw_cluster_label"]
            ):
                raise ReviewPackageError("raw cluster label is invalid")
            if evidence["cluster_id"] is not None and (
                not isinstance(evidence["cluster_id"], str)
                or not evidence["cluster_id"]
            ):
                raise ReviewPackageError("discovery cluster_id is invalid")
    if processing_ids != sorted(processing_ids) or len(processing_ids) != len(
        set(processing_ids)
    ):
        raise ReviewPackageError(
            "review answers must have unique sorted processing IDs"
        )
    _validate_review_item_shapes(question)
    choice_values = [item["value"] for item in question["existing_choices"]]
    if len(choice_values) != len(set(choice_values)):
        raise ReviewPackageError(
            "existing choice values must be unique within one question"
        )
    allowed_choices = set(choice_values)
    ownership: dict[str, int] = {processing_id: 0 for processing_id in processing_ids}
    for item in question["existing_choice_assignments"]:
        if item["proposed_choice_value"] not in allowed_choices:
            raise ReviewPackageError(
                "existing assignment references an unknown same-question choice"
            )
        ownership[item["processing_id"]] = ownership.get(item["processing_id"], 0) + 1
    for category in question["proposed_categories"]:
        for processing_id in category["member_processing_ids"]:
            ownership[processing_id] = ownership.get(processing_id, 0) + 1
    for item in question["unresolved_answers"]:
        ownership[item["processing_id"]] = ownership.get(item["processing_id"], 0) + 1
    if set(ownership) != set(processing_ids) or any(
        count != 1 for count in ownership.values()
    ):
        raise ReviewPackageError(
            "every processing answer must belong to exactly one original review outcome"
        )


def _validate_review_item_shapes(question: dict[str, Any]) -> None:
    existing_ids = []
    for item in question["existing_choice_assignments"]:
        if not isinstance(item, dict) or set(item) != {
            "review_item_id",
            "processing_id",
            "proposed_choice_value",
            "provider_decision",
        }:
            raise ReviewPackageError("existing assignment has an invalid schema")
        if (
            item["review_item_id"] != f"existing_assignment:{item['processing_id']}"
            or not _is_integer(item["proposed_choice_value"])
            or item["provider_decision"] != "assign"
        ):
            raise ReviewPackageError("existing assignment has invalid field values")
        existing_ids.append(item["processing_id"])
    category_ids = []
    for item in question["proposed_categories"]:
        if not isinstance(item, dict) or set(item) != {
            "review_item_id",
            "cluster_id",
            "proposed_value",
            "english_label",
            "arabic_label",
            "member_processing_ids",
        }:
            raise ReviewPackageError("proposed category has an invalid schema")
        if (
            item["review_item_id"] != f"proposed_category:{item['cluster_id']}"
            or not _is_integer(item["proposed_value"])
            or item["proposed_value"] <= 100
            or not isinstance(item["english_label"], str)
            or not item["english_label"]
            or not isinstance(item["arabic_label"], str)
            or not item["arabic_label"]
            or not isinstance(item["member_processing_ids"], list)
            or not item["member_processing_ids"]
            or item["member_processing_ids"]
            != sorted(set(item["member_processing_ids"]))
        ):
            raise ReviewPackageError("proposed category has invalid field values")
        category_ids.append(item["cluster_id"])
    merge_keys = []
    for item in question["merge_suggestions"]:
        if not isinstance(item, dict) or set(item) != {
            "review_item_id",
            "first_cluster_id",
            "second_cluster_id",
            "cosine_similarity",
            "combined_member_processing_ids",
        }:
            raise ReviewPackageError("merge suggestion has an invalid schema")
        first = item["first_cluster_id"]
        second = item["second_cluster_id"]
        if (
            not isinstance(first, str)
            or not isinstance(second, str)
            or first >= second
            or item["review_item_id"] != f"merge:{first}:{second}"
            or not _is_number(item["cosine_similarity"])
            or not 0 <= item["cosine_similarity"] <= 1
            or not isinstance(item["combined_member_processing_ids"], list)
            or item["combined_member_processing_ids"]
            != sorted(set(item["combined_member_processing_ids"]))
        ):
            raise ReviewPackageError("merge suggestion has invalid field values")
        merge_keys.append((first, second))
    unresolved_ids = []
    allowed_reasons = {
        "noise",
        "rare_insufficient_distinct_texts",
        "low_probability",
        "rejected_cluster",
        "label_rejected_mixed_meanings",
        "label_rejected_insufficient_common_meaning",
        "label_rejected_unsafe_to_label",
    }
    for item in question["unresolved_answers"]:
        if not isinstance(item, dict) or set(item) != {
            "review_item_id",
            "processing_id",
            "reason",
            "cluster_id",
        }:
            raise ReviewPackageError("unresolved answer has an invalid schema")
        if (
            item["review_item_id"] != f"unresolved:{item['processing_id']}"
            or item["reason"] not in allowed_reasons
            or (
                item["cluster_id"] is not None
                and (not isinstance(item["cluster_id"], str) or not item["cluster_id"])
            )
        ):
            raise ReviewPackageError("unresolved answer has invalid field values")
        unresolved_ids.append(item["processing_id"])
    if existing_ids != sorted(existing_ids):
        raise ReviewPackageError("existing assignments must use deterministic order")
    if category_ids != sorted(category_ids):
        raise ReviewPackageError("proposed categories must use deterministic order")
    if merge_keys != sorted(merge_keys):
        raise ReviewPackageError("merge suggestions must use deterministic order")
    if unresolved_ids != sorted(unresolved_ids):
        raise ReviewPackageError("unresolved answers must use deterministic order")


def _review_items(package: dict[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    collections = (
        ("existing_choice_assignments", "existing_assignment"),
        ("proposed_categories", "proposed_category"),
        ("merge_suggestions", "merge"),
        ("unresolved_answers", "unresolved"),
    )
    for question in package["questions"]:
        for collection, item_type in collections:
            items.extend(
                (item["review_item_id"], item_type) for item in question[collection]
            )
    return items


def _validate_review_item_dispositions(
    package: dict[str, Any], items: object, *, require_complete: bool
) -> None:
    if not isinstance(items, list):
        raise AnalystReviewError("review_item_dispositions must be an array")
    expected = _review_items(package)
    if len(items) != len(expected):
        raise AnalystReviewError(
            "review_item_dispositions must contain every original review item"
        )
    for item, (expected_id, item_type) in zip(items, expected, strict=True):
        if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
            raise AnalystReviewError("review item disposition has an invalid schema")
        if item["review_item_id"] != expected_id:
            raise AnalystReviewError(
                "review item dispositions must match package order and identity"
            )
        disposition = item["disposition"]
        if disposition is None and not require_complete:
            pass
        elif disposition not in _DISPOSITIONS[item_type]:
            raise AnalystReviewError(
                f"review item '{expected_id}' has an invalid disposition"
            )
        if item["note"] is not None and not isinstance(item["note"], str):
            raise AnalystReviewError("review item notes must be strings or null")


def _validate_question_state(
    package_question: dict[str, Any],
    state: dict[str, Any],
    *,
    category_ids: set[str],
    creation_sequences: set[int],
) -> None:
    if not isinstance(state["categories"], list) or not isinstance(
        state["answer_dispositions"], list
    ):
        raise AnalystReviewError("draft category and answer state must be arrays")
    processing_ids = [item["processing_id"] for item in package_question["answers"]]
    choices = {item["value"] for item in package_question["existing_choices"]}
    cluster_ids = {
        item["cluster_id"] for item in package_question["proposed_categories"]
    }
    local_categories: dict[str, dict[str, Any]] = {}
    category_member_ids: set[str] = set()
    existing_labels = {
        label
        for item in package_question["existing_choices"]
        for label in (item["english_label"], item["arabic_label"])
    }
    for category in state["categories"]:
        if not isinstance(category, dict) or set(category) != _DRAFT_CATEGORY_FIELDS:
            raise AnalystReviewError("draft category has an invalid schema")
        category_id = category["final_category_id"]
        if not isinstance(category_id, str) or not category_id:
            raise AnalystReviewError("final_category_id must be a non-empty string")
        if category_id in category_ids:
            raise AnalystReviewError(f"duplicate final category ID '{category_id}'")
        category_ids.add(category_id)
        local_categories[category_id] = category
        if category["origin"] not in _CATEGORY_ORIGINS:
            raise AnalystReviewError(f"category '{category_id}' has an invalid origin")
        components = category["component_cluster_ids"]
        members = category["member_processing_ids"]
        if (
            not isinstance(components, list)
            or len(components) != len(set(components))
            or not set(components) <= cluster_ids
        ):
            raise AnalystReviewError(
                f"category '{category_id}' has invalid component clusters"
            )
        if (
            not isinstance(members, list)
            or not members
            or len(members) != len(set(members))
            or not set(members) <= set(processing_ids)
        ):
            raise AnalystReviewError(
                f"category '{category_id}' must have valid unique members"
            )
        if category_member_ids & set(members):
            raise AnalystReviewError(
                "a processing answer belongs to multiple categories"
            )
        category_member_ids.update(members)
        sequence = category["creation_sequence"]
        if sequence is None:
            if not category_id.startswith("proposed:"):
                raise AnalystReviewError(
                    f"category '{category_id}' is missing its creation sequence"
                )
        elif (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or sequence in creation_sequences
        ):
            raise AnalystReviewError(
                "category creation sequences must be unique positive integers"
            )
        else:
            creation_sequences.add(sequence)
        other_labels = {
            label
            for other in state["categories"]
            if other is not category
            for label in (other.get("english_label"), other.get("arabic_label"))
            if isinstance(label, str)
        }
        try:
            validate_analyst_label_pair(
                category["english_label"],
                category["arabic_label"],
                existing_labels=existing_labels,
                other_category_labels=other_labels,
            )
        except (TypeError, CategoryLabelingError) as exc:
            raise AnalystReviewError(
                f"category '{category_id}' has invalid labels: {exc}"
            ) from exc
    answers = state["answer_dispositions"]
    if [
        item.get("processing_id") if isinstance(item, dict) else None
        for item in answers
    ] != processing_ids:
        raise AnalystReviewError(
            "answer dispositions must match package order and identity"
        )
    referenced_categories: set[str] = set()
    for answer in answers:
        if set(answer) != _ANSWER_FIELDS:
            raise AnalystReviewError("answer disposition has an invalid schema")
        processing_id = answer["processing_id"]
        decision = answer["decision"]
        if decision not in _ANSWER_DECISIONS:
            raise AnalystReviewError(
                f"answer '{processing_id}' has an invalid decision"
            )
        if decision == "existing_choice":
            if (
                answer["choice_value"] not in choices
                or answer["final_category_id"] is not None
                or answer["unresolved_reason"] is not None
            ):
                raise AnalystReviewError(
                    f"answer '{processing_id}' has an invalid existing-choice target"
                )
        elif decision == "new_category":
            category_id = answer["final_category_id"]
            if (
                category_id not in local_categories
                or answer["choice_value"] is not None
                or answer["unresolved_reason"] is not None
            ):
                raise AnalystReviewError(
                    f"answer '{processing_id}' has an invalid new-category target"
                )
            referenced_categories.add(category_id)
        elif (
            answer["choice_value"] is not None
            or answer["final_category_id"] is not None
            or not isinstance(answer["unresolved_reason"], str)
            or not answer["unresolved_reason"].strip()
        ):
            raise AnalystReviewError(
                f"answer '{processing_id}' has an invalid unresolved state"
            )
    if referenced_categories != set(local_categories):
        raise AnalystReviewError("every final category must be referenced by an answer")
    for category_id, category in local_categories.items():
        referenced = {
            item["processing_id"]
            for item in answers
            if item["final_category_id"] == category_id
        }
        if referenced != set(category["member_processing_ids"]):
            raise AnalystReviewError(
                f"category '{category_id}' member list does not match answer dispositions"
            )


def _normalize_category_origins(package: dict[str, Any], state: dict[str, Any]) -> None:
    """Derive category origins from the current question-scoped final state."""

    package_question = next(
        item
        for item in package["questions"]
        if item["question_id"] == state["question_id"]
    )
    proposals = {
        item["cluster_id"]: item for item in package_question["proposed_categories"]
    }
    component_counts: dict[str, int] = {}
    for category in state["categories"]:
        for component in category["component_cluster_ids"]:
            component_counts[component] = component_counts.get(component, 0) + 1
    for category in state["categories"]:
        components = category["component_cluster_ids"]
        if not components:
            category["origin"] = "manual"
        elif len(components) > 1:
            category["origin"] = "merged"
        elif component_counts[components[0]] > 1:
            category["origin"] = "split"
        else:
            proposal = proposals[components[0]]
            category["origin"] = (
                "proposed"
                if set(category["member_processing_ids"])
                == set(proposal["member_processing_ids"])
                and category["english_label"] == proposal["english_label"]
                and category["arabic_label"] == proposal["arabic_label"]
                else "modified"
            )


def _validate_completed_dispositions(
    package: dict[str, Any], draft: dict[str, Any]
) -> None:
    selected = {
        item["review_item_id"]: item["disposition"]
        for item in draft["review_item_dispositions"]
    }
    state_by_question = {item["question_id"]: item for item in draft["questions"]}
    for question in package["questions"]:
        state = state_by_question[question["question_id"]]
        answers = {item["processing_id"]: item for item in state["answer_dispositions"]}
        categories = state["categories"]
        categories_by_component: dict[str, list[dict[str, Any]]] = {}
        for category in categories:
            for cluster_id in category["component_cluster_ids"]:
                categories_by_component.setdefault(cluster_id, []).append(category)
        for item in question["existing_choice_assignments"]:
            final = answers[item["processing_id"]]
            same = (
                final["decision"] == "existing_choice"
                and final["choice_value"] == item["proposed_choice_value"]
            )
            expected = (
                "approved"
                if same
                else "rejected"
                if final["decision"] == "unresolved"
                else "overridden"
            )
            if selected[item["review_item_id"]] != expected:
                raise AnalystReviewError(
                    f"review item '{item['review_item_id']}' must be '{expected}'"
                )
        proposed_by_cluster = {
            item["cluster_id"]: item for item in question["proposed_categories"]
        }
        for cluster_id, proposal in proposed_by_cluster.items():
            containing = categories_by_component.get(cluster_id, [])
            if not containing:
                expected = "rejected"
            elif len(containing) > 1:
                expected = "split"
            else:
                category = containing[0]
                if len(category["component_cluster_ids"]) > 1:
                    expected = "merged"
                elif (
                    set(category["member_processing_ids"])
                    == set(proposal["member_processing_ids"])
                    and category["english_label"] == proposal["english_label"]
                    and category["arabic_label"] == proposal["arabic_label"]
                ):
                    expected = "approved"
                else:
                    expected = "modified"
            if selected[proposal["review_item_id"]] != expected:
                raise AnalystReviewError(
                    f"review item '{proposal['review_item_id']}' must be '{expected}'"
                )
        for item in question["merge_suggestions"]:
            first = categories_by_component.get(item["first_cluster_id"], [])
            second = categories_by_component.get(item["second_cluster_id"], [])
            together = any(category in second for category in first)
            expected = "approved" if together else "rejected"
            if selected[item["review_item_id"]] != expected:
                raise AnalystReviewError(
                    f"review item '{item['review_item_id']}' must be '{expected}'"
                )
        for item in question["unresolved_answers"]:
            expected = (
                "acknowledged"
                if answers[item["processing_id"]]["decision"] == "unresolved"
                else "assigned"
            )
            if selected[item["review_item_id"]] != expected:
                raise AnalystReviewError(
                    f"review item '{item['review_item_id']}' must be '{expected}'"
                )
        _validate_category_origins(question, categories, categories_by_component)


def _validate_category_origins(
    package_question: dict[str, Any],
    categories: list[dict[str, Any]],
    categories_by_component: dict[str, list[dict[str, Any]]],
) -> None:
    proposals = {
        item["cluster_id"]: item for item in package_question["proposed_categories"]
    }
    for category in categories:
        components = category["component_cluster_ids"]
        if not components:
            if category["origin"] not in {"manual", "merged"}:
                raise AnalystReviewError(
                    f"category '{category['final_category_id']}' origin must be "
                    "'manual' or 'merged'"
                )
            continue
        elif len(components) > 1:
            expected = "merged"
        elif len(categories_by_component[components[0]]) > 1:
            expected = "split"
        else:
            proposal = proposals[components[0]]
            exact = (
                set(category["member_processing_ids"])
                == set(proposal["member_processing_ids"])
                and category["english_label"] == proposal["english_label"]
                and category["arabic_label"] == proposal["arabic_label"]
            )
            expected = "proposed" if exact else "modified"
        if category["origin"] != expected:
            raise AnalystReviewError(
                f"category '{category['final_category_id']}' origin must be '{expected}'"
            )


def _allocate_final_values(
    package: dict[str, Any], draft: dict[str, Any]
) -> dict[str, int]:
    existing_locations: dict[int, list[str]] = {}
    for question in package["questions"]:
        for choice in question["existing_choices"]:
            if choice["value"] > 100:
                existing_locations.setdefault(choice["value"], []).append(
                    f"{question['question_id']} Code row {choice['code_row']}"
                )
    duplicate_existing = {
        value: locations
        for value, locations in existing_locations.items()
        if len(locations) > 1
    }
    if duplicate_existing:
        value = min(duplicate_existing)
        raise AnalystReviewError(
            f"generated value collision {value}: "
            + "; ".join(duplicate_existing[value])
        )
    used = set(existing_locations)
    proposals = {
        item["cluster_id"]: (
            item["proposed_value"],
            f"{question['question_id']} proposal {item['cluster_id']}",
        )
        for question in package["questions"]
        for item in question["proposed_categories"]
    }
    proposed_values = [item[0] for item in proposals.values()]
    if len(proposed_values) != len(set(proposed_values)):
        duplicated = min(
            value for value in proposed_values if proposed_values.count(value) > 1
        )
        locations = [
            location for value, location in proposals.values() if value == duplicated
        ]
        raise AnalystReviewError(
            f"generated value collision {duplicated}: " + "; ".join(locations)
        )
    collisions = used & set(proposed_values)
    if collisions:
        duplicated = min(collisions)
        proposal_locations = [
            location for value, location in proposals.values() if value == duplicated
        ]
        raise AnalystReviewError(
            f"generated value collision {duplicated}: "
            + "; ".join(existing_locations[duplicated] + proposal_locations)
        )
    used.update(proposed_values)
    proposal_values = {cluster_id: item[0] for cluster_id, item in proposals.items()}
    values: dict[str, int] = {}
    additional_splits: list[tuple[str, int, str, dict[str, Any]]] = []
    manuals: list[tuple[str, int, dict[str, Any]]] = []
    for state in draft["questions"]:
        split_groups: dict[str, list[dict[str, Any]]] = {}
        for category in state["categories"]:
            components = category["component_cluster_ids"]
            if category["origin"] == "split":
                split_groups.setdefault(components[0], []).append(category)
            elif category["origin"] == "manual" or (
                category["origin"] == "merged" and not components
            ):
                manuals.append(
                    (
                        state["question_id"],
                        category["creation_sequence"],
                        category,
                    )
                )
            elif components:
                values[category["final_category_id"]] = min(
                    proposal_values[item] for item in components
                )
        for parent, children in split_groups.items():
            ordered = sorted(
                children, key=lambda item: min(item["member_processing_ids"])
            )
            values[ordered[0]["final_category_id"]] = proposal_values[parent]
            for category in ordered[1:]:
                additional_splits.append(
                    (
                        state["question_id"],
                        proposal_values[parent],
                        min(category["member_processing_ids"]),
                        category,
                    )
                )
    if len(values.values()) != len(set(values.values())):
        raise AnalystReviewError("retained final category values collide")
    for _, _, _, category in sorted(additional_splits):
        value = _next_unused_value(used)
        values[category["final_category_id"]] = value
        used.add(value)
    for _, _, category in sorted(manuals):
        value = _next_unused_value(used)
        values[category["final_category_id"]] = value
        used.add(value)
    return values


def _ordered_categories(
    categories: list[dict[str, Any]], values: dict[str, int]
) -> list[dict[str, Any]]:
    return sorted(
        categories,
        key=lambda item: (values[item["final_category_id"]], item["final_category_id"]),
    )


def _derive_overrides(
    package_question: dict[str, Any],
    categories: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    original: dict[str, tuple[str, Any]] = {}
    source_item_by_processing: dict[str, str] = {}
    for item in package_question["existing_choice_assignments"]:
        original[item["processing_id"]] = (
            "existing_choice",
            item["proposed_choice_value"],
        )
        source_item_by_processing[item["processing_id"]] = item["review_item_id"]
    for item in package_question["proposed_categories"]:
        for processing_id in item["member_processing_ids"]:
            original[processing_id] = ("new_category", item["cluster_id"])
            source_item_by_processing[processing_id] = item["review_item_id"]
    for item in package_question["unresolved_answers"]:
        original[item["processing_id"]] = ("unresolved", item["reason"])
        source_item_by_processing[item["processing_id"]] = item["review_item_id"]
    overrides: list[tuple[str, list[str], list[str]]] = []
    for category in categories:
        processing_ids = category["member_processing_ids"]
        source_ids = sorted(
            {
                source_item_by_processing[item]
                for item in processing_ids
                if item in source_item_by_processing
            }
        )
        if category["origin"] == "manual":
            overrides.append(("create_category", source_ids, processing_ids))
        elif category["origin"] == "split":
            overrides.append(("split_category", source_ids, processing_ids))
        elif category["origin"] == "merged":
            overrides.append(("merge_category", source_ids, processing_ids))
        else:
            components = category["component_cluster_ids"]
            if components:
                proposal = next(
                    item
                    for item in package_question["proposed_categories"]
                    if item["cluster_id"] == components[0]
                )
                if (
                    category["english_label"] != proposal["english_label"]
                    or category["arabic_label"] != proposal["arabic_label"]
                ):
                    overrides.append(
                        (
                            "edit_label",
                            [proposal["review_item_id"]],
                            processing_ids,
                        )
                    )
    category_by_id = {item["final_category_id"]: item for item in categories}
    for answer in answers:
        processing_id = answer["processing_id"]
        if answer["decision"] == "existing_choice":
            final = ("existing_choice", answer["choice_value"])
        elif answer["decision"] == "new_category":
            category = category_by_id[answer["final_category_id"]]
            final = (
                "new_category",
                tuple(category["component_cluster_ids"]),
            )
        else:
            final = ("unresolved", answer["unresolved_reason"])
        before = original[processing_id]
        same = before == final or (
            before[0] == "new_category"
            and final[0] == "new_category"
            and before[1] in final[1]
        )
        if same:
            continue
        if before[0] == "existing_choice":
            operation = "override_existing_assignment"
        elif answer["decision"] == "unresolved":
            operation = "mark_unresolved"
        else:
            operation = "move_answer"
        overrides.append(
            (
                operation,
                [source_item_by_processing[processing_id]],
                [processing_id],
            )
        )
    result = []
    for index, (operation, source_ids, processing_ids) in enumerate(overrides, start=1):
        result.append(
            {
                "override_id": f"override:{index:04d}",
                "operation": operation,
                "source_review_item_ids": sorted(set(source_ids)),
                "affected_processing_ids": sorted(set(processing_ids)),
                "note": None,
            }
        )
    return result


def _draft_question(draft: dict[str, Any], question_id: str) -> dict[str, Any]:
    for question in draft["questions"]:
        if question["question_id"] == question_id:
            return question
    raise AnalystReviewError(f"unknown question '{question_id}'")


def _next_unused_value(used: set[int]) -> int:
    candidate = 101
    while candidate in used:
        candidate += 1
    return candidate


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == value
        and value not in {float("inf"), float("-inf")}
    )


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise AnalystReviewError("timestamps must include a timezone")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _require_utc_timestamp(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AnalystReviewError(f"{field} must be an RFC 3339 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AnalystReviewError(f"{field} must be an RFC 3339 UTC timestamp") from exc


def _require_uuid4(value: object, field: str) -> None:
    if not isinstance(value, str):
        raise AnalystReviewError(f"{field} must be a lowercase UUIDv4")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise AnalystReviewError(f"{field} must be a lowercase UUIDv4") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise AnalystReviewError(f"{field} must be a lowercase UUIDv4")


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _atomic_json_write(destination: Path, value: dict[str, Any]) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("xb") as output:
            output.write(_json_bytes(value))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise AnalystReviewError(
            f"could not save review draft '{destination}': {exc}"
        ) from exc


def _exclusive_json_write(destination: Path, value: dict[str, Any]) -> None:
    created = False
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            created = True
            output.write(_json_bytes(value))
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise AnalystReviewError(
            f"approval already exists and will not be overwritten: '{destination}'"
        ) from exc
    except OSError as exc:
        if created:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise AnalystReviewError(
            f"could not write approval '{destination}': {exc}"
        ) from exc
