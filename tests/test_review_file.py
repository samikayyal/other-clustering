from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from openpyxl import load_workbook

from other_cluster.domain import (
    CategoryDiscoveryResult,
    ClusterClassificationResult,
    ClusterProposal,
    DiscoveredCluster,
    DiscoveryPointResult,
)
from other_cluster.errors import ReviewFileError
from other_cluster.review_file import (
    complete_and_save_review_file,
    load_review_file,
    update_and_save_review_file,
    validate_review_file,
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


def _review(tmp_path: Path):
    source = create_workbook(
        tmp_path / "Input Workbook.xlsx", answers=["a", "b", "c", "d", "a"]
    )
    dataset = ingest_workbook(source)
    discovery, classification = _facts(dataset)
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


def _payload(
    document: dict[str, object], *, cluster_decision: str = "new_category"
) -> dict[str, object]:
    question = document["questions"][0]
    cluster = question["clusters"][0]
    unresolved = question["unresolved_answers"][0]
    cluster_value = {
        "decision": cluster_decision,
        "selected_choice_value": None,
        "english_label": "Analyst category"
        if cluster_decision == "new_category"
        else None,
        "arabic_label": "فئة المحلل" if cluster_decision == "new_category" else None,
        "allocated_value": None,
    }
    if cluster_decision == "existing_choice":
        cluster_value["selected_choice_value"] = 1
    elif cluster_decision == "unresolved":
        cluster_value["english_label"] = None
        cluster_value["arabic_label"] = None
    return {
        "analyst_name": "Analyst One",
        "questions": [
            {
                "question_id": question["question_id"],
                "clusters": [
                    {
                        "cluster_id": cluster["cluster_id"],
                        "analyst_decision": cluster_value,
                    }
                ],
                "unresolved_answers": [
                    {
                        "processing_id": unresolved["processing_id"],
                        "analyst_decision": {
                            "decision": "existing_choice",
                            "selected_choice_value": 2,
                            "english_label": None,
                            "arabic_label": None,
                            "allocated_value": None,
                        },
                    }
                ],
            }
        ],
    }


def test_schema_version_3_file_preserves_evidence_and_arabic_atomically(
    tmp_path: Path,
) -> None:
    source, path = _review(tmp_path)
    document = load_review_file(path)
    assert document["schema_version"] == 3
    assert document["status"] == "in_review"
    assert document["completed_at_utc"] is None
    assert (
        document["questions"][0]["clusters"][0]["gemini_proposal"]["decision"]
        == "new_category"
    )
    assert "فئة جديدة" in path.read_text(encoding="utf-8")
    assert document["questions"][0]["answers"][0]["row_mappings"]
    assert "members" not in document["questions"][0]["clusters"][0]
    assert set(document["questions"][0]["unresolved_answers"][0]) == {
        "processing_id",
        "reason",
        "analyst_decision",
    }
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


def test_in_review_resume_and_completion_allocates_per_question_decision(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    updated = update_and_save_review_file(path, _payload(document))
    assert updated["status"] == "in_review"
    completed = complete_and_save_review_file(path, _payload(updated))
    assert completed["status"] == "complete"
    assert completed["completed_at_utc"]
    decision = completed["questions"][0]["clusters"][0]["analyst_decision"]
    assert decision["allocated_value"] == 101
    assert (
        completed["questions"][0]["unresolved_answers"][0]["analyst_decision"][
            "selected_choice_value"
        ]
        == 2
    )
    assert load_review_file(path)["status"] == "complete"


def test_completion_blocks_missing_decisions_and_invalid_noise_new_category(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    missing_name = _payload(document)
    missing_name["analyst_name"] = ""
    with pytest.raises(ReviewFileError, match="completion requires a nonblank"):
        complete_and_save_review_file(path, missing_name)
    bad = _payload(document)
    bad["questions"][0]["unresolved_answers"][0]["analyst_decision"]["decision"] = (
        "new_category"
    )
    bad["questions"][0]["unresolved_answers"][0]["analyst_decision"][
        "english_label"
    ] = "New"
    bad["questions"][0]["unresolved_answers"][0]["analyst_decision"]["arabic_label"] = (
        "جديد"
    )
    with pytest.raises(ReviewFileError, match="invalid analyst decision"):
        update_and_save_review_file(path, bad)


def test_fixed_membership_and_free_standing_routes_are_not_editable(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    app = create_review_app(path, working_directory=tmp_path)
    client = app.test_client()
    response = client.put(
        "/api/review",
        json={
            "analyst_name": "A",
            "questions": [
                {
                    "question_id": "B5_other",
                    "clusters": [
                        {
                            "cluster_id": "B5_other:cluster:0",
                            "member_processing_ids": ["moved"],
                            "analyst_decision": None,
                        }
                    ],
                    "unresolved_answers": [
                        {"processing_id": "missing", "analyst_decision": None}
                    ],
                }
            ],
        },
    )
    assert response.status_code == 400
    assert client.post("/api/categories", json={}).status_code == 404
    assert client.put("/api/draft", json={}).status_code == 404


def test_completed_file_is_read_only_in_browser(tmp_path: Path) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    complete_and_save_review_file(path, _payload(document))
    app = create_review_app(path, working_directory=tmp_path)
    client = app.test_client()
    page = client.get("/")
    assert page.status_code == 200
    assert b"Read-only final results" in page.data
    assert (
        client.put("/api/review", json=_payload(load_review_file(path))).status_code
        == 400
    )


def test_completion_allocates_independently_per_question_and_reuses_values(
    tmp_path: Path,
) -> None:
    source = create_workbook(tmp_path / "two questions.xlsx", answers=["a", "b", "c"])
    workbook = load_workbook(source)
    workbook["Survey"].append(["text", "B6", "Second question", "السؤال الثاني"])
    workbook["Code"]["B3"] = 101
    workbook["Code"].append(["B6_other", -96, "Other", "أخرى"])
    workbook["Code"].append(["B6_other", 1, "One", "واحد"])
    workbook["Code"].append(["B6_other", 2, "Two", "اثنان"])
    data = workbook["Data"]
    data.cell(row=1, column=5).value = "B6_other"
    for row in range(2, 5):
        data.cell(row=row, column=5).value = data.cell(row=row, column=4).value
    workbook.save(source)
    workbook.close()
    dataset = ingest_workbook(source)

    points = []
    clusters = []
    proposals = []
    for question in dataset.questions:
        items = [
            item
            for item in dataset.processing_answers
            if item.question_id == question.question_id
        ]
        member_ids = tuple(item.processing_id for item in items)
        cluster_id = f"{question.question_id}:cluster:0"
        clusters.append(
            DiscoveredCluster(
                cluster_id,
                question.question_id,
                0,
                member_ids,
                tuple(answer_id for item in items for answer_id in item.answer_ids),
            )
        )
        proposals.append(
            ClusterProposal(
                cluster_id=cluster_id,
                question_id=question.question_id,
                decision="new_category",
                selected_choice_value=None,
                english_label="Fresh Origin"
                if question.question_id == "B5_other"
                else "Fresh Meaning",
                arabic_label="فئة مختلفة",
                rejection_reason=None,
            )
        )
        points.extend(
            DiscoveryPointResult(
                processing_id=item.processing_id,
                question_id=question.question_id,
                answer_ids=item.answer_ids,
                occurrence_count=item.occurrence_count,
                raw_cluster_label=0,
                membership_probability=0.9,
                status="accepted_cluster",
                cluster_id=cluster_id,
            )
            for item in items
        )
    discovery = CategoryDiscoveryResult(tuple(points), tuple(clusters), ())
    classification = ClusterClassificationResult(tuple(proposals))
    result = write_review_file(
        dataset,
        discovery,
        classification,
        input_source=str(source.resolve()),
        source_path=source,
        output_directory=tmp_path / "reviews",
    )
    document = load_review_file(result.review_file_path)
    payload = {
        "analyst_name": "Analyst Two",
        "questions": [
            {
                "question_id": question["question_id"],
                "clusters": [
                    {
                        "cluster_id": cluster["cluster_id"],
                        "analyst_decision": {
                            "decision": "new_category",
                            "selected_choice_value": None,
                            "english_label": "Approved Origin"
                            if question["question_id"] == "B5_other"
                            else "Approved Meaning",
                            "arabic_label": "فئة معتمدة",
                            "allocated_value": None,
                        },
                    }
                    for cluster in question["clusters"]
                ],
                "unresolved_answers": [],
            }
            for question in document["questions"]
        ],
    }
    completed = complete_and_save_review_file(result.review_file_path, payload)
    values = {
        question["question_id"]: question["clusters"][0]["analyst_decision"][
            "allocated_value"
        ]
        for question in completed["questions"]
    }
    assert values == {"B5_other": 102, "B6_other": 101}
