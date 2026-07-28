from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from other_cluster.domain import (
    CategoryDiscoveryResult,
    CategoryLabelingResult,
    ClusterLabelDecision,
    DiscoveredCluster,
    DiscoveryPointResult,
    ExistingChoiceAssignmentResult,
    ExistingChoiceVerification,
    ProposedCategory,
)
from other_cluster.review_package import write_review_package
from other_cluster.errors import ReviewPackageError
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook

_RUN_ID = "123e4567-e89b-42d3-a456-426614174000"


def _discovery(dataset):
    cluster_id = "B5_other:cluster:0"
    processing = tuple(dataset.processing_answers)
    return CategoryDiscoveryResult(
        reductions=(),
        points=tuple(
            DiscoveryPointResult(
                processing_id=item.processing_id,
                question_id=item.question_id,
                answer_ids=item.answer_ids,
                occurrence_count=item.occurrence_count,
                raw_cluster_label=0,
                membership_probability=0.9,
                status="accepted_cluster",
                cluster_id=cluster_id,
            )
            for item in processing
        ),
        proposed_clusters=(
            DiscoveredCluster(
                cluster_id=cluster_id,
                question_id="B5_other",
                raw_cluster_label=0,
                processing_ids=tuple(item.processing_id for item in processing),
                answer_ids=tuple(
                    answer_id for item in processing for answer_id in item.answer_ids
                ),
            ),
        ),
        unresolved_answer_ids=(),
        merge_suggestions=(),
    )


def _unassigned(dataset):
    return ExistingChoiceAssignmentResult(
        verifications=tuple(
            ExistingChoiceVerification(
                processing_id=item.processing_id,
                question_id=item.question_id,
                status="no_match",
                selected_choice_value=None,
                provider_evaluated=True,
            )
            for item in dataset.processing_answers
        ),
        assignments=(),
        unassigned_answer_ids=tuple(answer.answer_id for answer in dataset.answers),
    )


def test_writes_complete_utf8_package_with_duplicate_row_mappings_and_no_workbook_mutation(
    tmp_path,
) -> None:
    source_path = create_workbook(
        tmp_path / "Input Workbook.xlsx", answers=["a", "a", "b"]
    )
    before = source_path.read_bytes()
    dataset = ingest_workbook(source_path)
    discovery = _discovery(dataset)
    labeling = CategoryLabelingResult(
        decisions=(
            ClusterLabelDecision(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                decision="label",
                english_label="Local Origins",
                arabic_label="اصول محلية",
                rejection_reason=None,
            ),
        ),
        proposed_categories=(
            ProposedCategory(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                proposed_value=101,
                english_label="Local Origins",
                arabic_label="اصول محلية",
                member_processing_ids=tuple(
                    item.processing_id for item in dataset.processing_answers
                ),
            ),
        ),
    )

    result = write_review_package(
        dataset,
        _unassigned(dataset),
        discovery,
        labeling,
        input_source=str(source_path),
        source_path=source_path,
        output_directory=tmp_path / "review_packages",
        analysis_run_id=_RUN_ID,
        created_at_utc=datetime(2026, 7, 28, tzinfo=UTC),
    )

    raw = result.package_path.read_bytes()
    package = json.loads(raw.decode("utf-8"))
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "اصول محلية" in raw.decode("utf-8")
    assert result.package_path.name == f"input_workbook_{_RUN_ID}_review.json"
    assert package["source_workbook"]["source_locator"] == str(source_path.resolve())
    assert package["questions"][0]["answers"][0]["occurrence_count"] == 2
    assert len(package["questions"][0]["answers"][0]["row_mappings"]) == 2
    assert package["questions"][0]["proposed_categories"][0]["proposed_value"] == 101
    assert source_path.read_bytes() == before


def test_label_rejection_turns_cluster_members_into_unresolved_review_items(
    tmp_path,
) -> None:
    source_path = create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    dataset = ingest_workbook(source_path)
    labeling = CategoryLabelingResult(
        decisions=(
            ClusterLabelDecision(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                decision="reject",
                english_label=None,
                arabic_label=None,
                rejection_reason="mixed_meanings",
            ),
        ),
        proposed_categories=(),
    )

    result = write_review_package(
        dataset,
        _unassigned(dataset),
        _discovery(dataset),
        labeling,
        input_source=str(source_path),
        source_path=source_path,
        output_directory=tmp_path / "review_packages",
        analysis_run_id=_RUN_ID,
    )

    package = json.loads(result.package_path.read_text(encoding="utf-8"))
    unresolved = package["questions"][0]["unresolved_answers"]
    assert len(unresolved) == len(dataset.processing_answers)
    assert {item["reason"] for item in unresolved} == {"label_rejected_mixed_meanings"}


def test_google_source_uses_canonical_sheet_locator(tmp_path) -> None:
    source_path = create_workbook(tmp_path / "downloaded.xlsx", answers=["a", "b", "c"])
    dataset = ingest_workbook(source_path)
    discovery = _discovery(dataset)
    labeling = CategoryLabelingResult(
        decisions=(
            ClusterLabelDecision(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                decision="label",
                english_label="Local Origins",
                arabic_label="اصول محلية",
                rejection_reason=None,
            ),
        ),
        proposed_categories=(
            ProposedCategory(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                proposed_value=101,
                english_label="Local Origins",
                arabic_label="اصول محلية",
                member_processing_ids=tuple(
                    item.processing_id for item in dataset.processing_answers
                ),
            ),
        ),
    )

    result = write_review_package(
        dataset,
        _unassigned(dataset),
        discovery,
        labeling,
        input_source="https://docs.google.com/spreadsheets/d/abc123/edit?gid=12",
        source_path=source_path,
        output_directory=tmp_path / "review_packages",
        analysis_run_id=_RUN_ID,
    )

    package = json.loads(result.package_path.read_text(encoding="utf-8"))
    assert package["source_workbook"]["input_kind"] == "google_sheets"
    assert package["source_workbook"]["source_locator"] == (
        "https://docs.google.com/spreadsheets/d/abc123"
    )


def test_invalid_labeling_handoff_writes_no_partial_package(tmp_path) -> None:
    source_path = create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    dataset = ingest_workbook(source_path)
    labeling = CategoryLabelingResult(
        decisions=(
            ClusterLabelDecision(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                decision="label",
                english_label="Local Origins",
                arabic_label="اصول محلية",
                rejection_reason=None,
            ),
        ),
        proposed_categories=(),
    )
    destination = tmp_path / "review_packages"

    with pytest.raises(ReviewPackageError, match="missing its proposed category"):
        write_review_package(
            dataset,
            _unassigned(dataset),
            _discovery(dataset),
            labeling,
            input_source=str(source_path),
            source_path=source_path,
            output_directory=destination,
            analysis_run_id=_RUN_ID,
        )

    assert not destination.exists()


def test_package_filename_collision_preserves_the_existing_package(tmp_path) -> None:
    source_path = create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    dataset = ingest_workbook(source_path)
    destination = tmp_path / "review_packages"
    destination.mkdir()
    existing_package = destination / f"input_{_RUN_ID}_review.json"
    existing_package.write_text("existing package", encoding="utf-8")
    labeling = CategoryLabelingResult(
        decisions=(
            ClusterLabelDecision(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                decision="label",
                english_label="Local Origins",
                arabic_label="اصول محلية",
                rejection_reason=None,
            ),
        ),
        proposed_categories=(
            ProposedCategory(
                cluster_id="B5_other:cluster:0",
                question_id="B5_other",
                proposed_value=101,
                english_label="Local Origins",
                arabic_label="اصول محلية",
                member_processing_ids=tuple(
                    item.processing_id for item in dataset.processing_answers
                ),
            ),
        ),
    )

    with pytest.raises(ReviewPackageError, match="filename collision"):
        write_review_package(
            dataset,
            _unassigned(dataset),
            _discovery(dataset),
            labeling,
            input_source=str(source_path),
            source_path=source_path,
            output_directory=destination,
            analysis_run_id=_RUN_ID,
        )

    assert existing_package.read_text(encoding="utf-8") == "existing package"
