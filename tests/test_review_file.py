from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from other_cluster.domain import (
    CategoryDiscoveryResult,
    ClusterClassificationResult,
    ClusterProposal,
    DiscoveredCluster,
    DiscoveryPointResult,
)
from other_cluster.errors import ReviewFileError
from other_cluster.review_file import (
    load_review_file,
    write_review_file,
)
from other_cluster.review_webapp import create_review_app
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


def _facts(dataset, *, proposal_decision: str = "new_category"):
    processing = {item.text: item for item in dataset.processing_answers}
    cluster_members = tuple(processing[text].processing_id for text in ("a", "b", "c"))
    points = []
    for item in dataset.processing_answers:
        if item.text in {"a", "b", "c"}:
            points.append(
                DiscoveryPointResult(
                    processing_id=item.processing_id,
                    question_id=item.question_id,
                    answer_ids=item.answer_ids,
                    occurrence_count=item.occurrence_count,
                    raw_cluster_label=0,
                    membership_probability=0.9,
                    status="accepted_cluster",
                    cluster_id="B5_other:cluster:0",
                )
            )
        else:
            points.append(
                DiscoveryPointResult(
                    processing_id=item.processing_id,
                    question_id=item.question_id,
                    answer_ids=item.answer_ids,
                    occurrence_count=item.occurrence_count,
                    raw_cluster_label=-1,
                    membership_probability=0.0,
                    status="noise",
                )
            )
    cluster = DiscoveredCluster(
        cluster_id="B5_other:cluster:0",
        question_id="B5_other",
        raw_cluster_label=0,
        processing_ids=cluster_members,
        answer_ids=tuple(
            answer_id
            for processing_id in cluster_members
            for answer_id in next(
                item
                for item in dataset.processing_answers
                if item.processing_id == processing_id
            ).answer_ids
        ),
    )
    proposal = ClusterProposal(
        cluster_id=cluster.cluster_id,
        question_id=cluster.question_id,
        decision=proposal_decision,
        selected_choice_value=None,
        english_label="Fresh category" if proposal_decision == "new_category" else None,
        arabic_label="فئة جديدة" if proposal_decision == "new_category" else None,
        rejection_reason="mixed_meanings"
        if proposal_decision == "reject_cluster"
        else None,
    )
    # ClusterProposal intentionally has no selected-choice field; the provider
    # choice is represented by its decision fields in the review proposal.
    return (
        CategoryDiscoveryResult(
            points=tuple(points),
            proposed_clusters=(cluster,),
            unresolved_processing_ids=tuple(
                point.processing_id
                for point in points
                if point.status != "accepted_cluster"
            ),
        ),
        ClusterClassificationResult(proposals=(proposal,)),
    )


def _review(tmp_path: Path, *, proposal_decision: str = "new_category"):
    source = create_workbook(
        tmp_path / "Input Workbook.xlsx", answers=["a", "b", "c", "d", "a"]
    )
    dataset = ingest_workbook(source)
    discovery, classification = _facts(dataset, proposal_decision=proposal_decision)
    result = write_review_file(
        dataset,
        discovery,
        classification,
        input_source=str(source.resolve()),
        source_path=source,
        output_directory=tmp_path / "reviews",
        analysis_run_id=str(uuid.uuid4()),
    )
    return source, result.review_file_path


def test_schema_version_4_file_preserves_evidence_and_arabic_atomically(
    tmp_path: Path,
) -> None:
    source, path = _review(tmp_path)
    document = load_review_file(path)
    assert document["schema_version"] == 4
    assert document["status"] == "in_review"
    assert document["completed_at_utc"] is None
    assert (
        document["questions"][0]["automatic_groups"][0]["provider_proposal"]["decision"]
        == "new_category"
    )
    assert "فئة جديدة" in path.read_text(encoding="utf-8")
    assert document["questions"][0]["answers"][0]["row_mappings"]
    assert "analyst_name" not in document
    assert document["questions"][0]["workspace"]["needs_attention"]
    assert source.read_bytes()


def test_old_schema_version_one_is_rejected_clearly(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(ReviewFileError, match="schema versions 1 and 2.*new analysis"):
        load_review_file(path)


def test_old_schema_version_two_is_rejected_clearly(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    with pytest.raises(ReviewFileError, match="schema versions 1 and 2.*new analysis"):
        load_review_file(path)


def test_review_page_exposes_identity_free_draft_apply_confirm_controls(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    page = create_review_app(path, working_directory=tmp_path).test_client().get("/")

    assert page.status_code == 200
    assert b"Review answer groups" in page.data
    assert b"analyst-name" not in page.data
    assert b"GROUND_TRUTH" not in page.data
    script = (
        create_review_app(path, working_directory=tmp_path)
        .test_client()
        .get("/static/review.js")
    )
    assert b"data-decision-select" in script.data
    assert b"Unsaved decision draft" in script.data
    assert b"Apply decision changes" in script.data
    assert b"Discard draft" in script.data
    assert b"Confirm group" in script.data
    assert b'fetch("/api/commands"' in script.data


def test_review_page_omits_evaluation_when_no_ground_truth_is_supplied(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    page = create_review_app(path, working_directory=tmp_path).test_client().get("/")

    assert page.status_code == 200
    assert b'id="clustering-evaluation"' not in page.data
    assert b'id="coded-ground-truth-only"' not in page.data
