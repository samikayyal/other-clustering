from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from other_cluster.errors import ReviewFileError
from other_cluster.review_file import apply_review_command, load_review_file
from other_cluster.review_validation import validate_review_file
from other_cluster.review_webapp import create_review_app

from .test_review_file import _review


def test_new_analysis_creates_strict_identity_free_v4_workspace(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    question = document["questions"][0]
    automatic = question["automatic_groups"][0]
    group = question["workspace"]["active_groups"][0]

    assert document["schema_version"] == 4
    assert document["revision"] == 0
    assert "analyst_name" not in document
    assert set(question["workspace"]) == {
        "active_groups",
        "needs_attention",
        "excluded_answers",
        "retired_groups",
        "history",
        "undo",
    }
    assert automatic["member_processing_ids"] == group["member_processing_ids"]
    assert automatic["provider_proposal"]["decision"] == "new_category"
    assert group["decision"] == {
        "decision": "new_category",
        "selected_choice_value": None,
        "english_label": "Fresh category",
        "arabic_label": "فئة جديدة",
    }
    assert group["review_state"] == "needs_review"
    assert question["workspace"]["needs_attention"]
    assert question["workspace"]["history"] == []
    assert question["workspace"]["undo"] is None

    malformed = deepcopy(document)
    malformed["questions"][0]["workspace"]["unexpected"] = []
    with pytest.raises(ReviewFileError, match="workspace has an invalid schema"):
        validate_review_file(malformed)


def test_rejected_provider_proposal_does_not_prefill_editable_decision(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path, proposal_decision="reject_cluster")
    document = load_review_file(path)
    question = document["questions"][0]

    assert question["automatic_groups"][0]["provider_proposal"]["decision"] == (
        "reject_cluster"
    )
    assert question["workspace"]["active_groups"][0]["decision"] is None
    assert question["workspace"]["active_groups"][0]["review_state"] == ("needs_review")


def test_apply_decision_then_confirm_group_is_revision_checked_and_durable(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    initial = load_review_file(path)
    question = initial["questions"][0]
    group_id = question["workspace"]["active_groups"][0]["group_id"]
    client = create_review_app(path, working_directory=tmp_path).test_client()

    applied_response = client.post(
        "/api/commands",
        json={
            "expected_revision": 0,
            "command": {
                "type": "apply_decision",
                "question_id": question["question_id"],
                "group_id": group_id,
                "decision": {
                    "decision": "existing_choice",
                    "selected_choice_value": 1,
                    "english_label": None,
                    "arabic_label": None,
                },
            },
        },
    )
    assert applied_response.status_code == 200
    applied = applied_response.get_json()["review"]
    assert applied["revision"] == 1
    assert (
        applied["questions"][0]["workspace"]["active_groups"][0]["review_state"]
        == "needs_review"
    )
    assert load_review_file(path) == applied

    stale = client.post(
        "/api/commands",
        json={
            "expected_revision": 0,
            "command": {
                "type": "confirm_group",
                "question_id": question["question_id"],
                "group_id": group_id,
            },
        },
    )
    assert stale.status_code == 409
    assert "revision" in stale.get_json()["error"]
    assert load_review_file(path)["revision"] == 1

    confirmed_response = client.post(
        "/api/commands",
        json={
            "expected_revision": 1,
            "command": {
                "type": "confirm_group",
                "question_id": question["question_id"],
                "group_id": group_id,
            },
        },
    )
    assert confirmed_response.status_code == 200
    confirmed = confirmed_response.get_json()["review"]
    workspace = confirmed["questions"][0]["workspace"]
    assert confirmed["revision"] == 2
    assert workspace["active_groups"][0]["review_state"] == "confirmed"
    assert [entry["operation"] for entry in workspace["history"]] == [
        "apply_decision",
        "confirm_group",
    ]
    assert client.put("/api/review", json={}).status_code == 404


def test_command_boundary_rejects_invalid_decisions_without_changing_file(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    initial = load_review_file(path)
    question = initial["questions"][0]
    group_id = question["workspace"]["active_groups"][0]["group_id"]
    client = create_review_app(path, working_directory=tmp_path).test_client()

    response = client.post(
        "/api/commands",
        json={
            "expected_revision": 0,
            "command": {
                "type": "apply_decision",
                "question_id": question["question_id"],
                "group_id": group_id,
                "decision": {
                    "decision": "new_category",
                    "selected_choice_value": None,
                    "english_label": "Only English",
                    "arabic_label": "",
                },
            },
        },
    )

    assert response.status_code == 400
    assert load_review_file(path) == initial


def test_command_boundary_rejects_boolean_existing_choice_value(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    initial = load_review_file(path)
    question = initial["questions"][0]
    group_id = question["workspace"]["active_groups"][0]["group_id"]
    response = (
        create_review_app(path, working_directory=tmp_path)
        .test_client()
        .post(
            "/api/commands",
            json={
                "expected_revision": 0,
                "command": {
                    "type": "apply_decision",
                    "question_id": question["question_id"],
                    "group_id": group_id,
                    "decision": {
                        "decision": "existing_choice",
                        "selected_choice_value": True,
                        "english_label": None,
                        "arabic_label": None,
                    },
                },
            },
        )
    )

    assert response.status_code == 400
    assert load_review_file(path) == initial


def test_command_boundary_rejects_duplicate_reviewer_category_labels(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    question = document["questions"][0]
    processing_id = question["workspace"]["needs_attention"].pop()
    question["workspace"]["active_groups"].append(
        {
            "group_id": f"{question['question_id']}:reviewer:1",
            "origin": "reviewer",
            "creation_order": 1,
            "member_processing_ids": [processing_id],
            "decision": {
                "decision": "new_category",
                "selected_choice_value": None,
                "english_label": "Different label",
                "arabic_label": "فئة مختلفة",
            },
            "review_state": "needs_review",
        }
    )
    validate_review_file(document)

    with pytest.raises(ReviewFileError, match="duplicate another proposed category"):
        apply_review_command(
            document,
            {
                "expected_revision": 0,
                "command": {
                    "type": "apply_decision",
                    "question_id": question["question_id"],
                    "group_id": f"{question['question_id']}:reviewer:1",
                    "decision": {
                        "decision": "new_category",
                        "selected_choice_value": None,
                        "english_label": "Fresh category",
                        "arabic_label": "فئة جديدة",
                    },
                },
            },
        )


@pytest.mark.parametrize("rejection_reason", [None, "unexpected_reason"])
def test_strict_v4_validation_rejects_inconsistent_provider_provenance(
    tmp_path: Path, rejection_reason: object
) -> None:
    _, path = _review(tmp_path, proposal_decision="reject_cluster")
    document = load_review_file(path)
    proposal = document["questions"][0]["automatic_groups"][0]["provider_proposal"]
    proposal["rejection_reason"] = rejection_reason

    with pytest.raises(ReviewFileError, match="invalid provider proposal"):
        validate_review_file(document)


def test_v3_artifact_is_viewable_but_always_read_only(tmp_path: Path) -> None:
    _, path = _review(tmp_path)
    v3 = load_review_file(path)
    v3["schema_version"] = 3
    v3.pop("revision")
    v3["analyst_name"] = None
    for question in v3["questions"]:
        question["clusters"] = [
            {
                "cluster_id": item["group_id"],
                "raw_cluster_label": question["automatic_groups"][index][
                    "raw_cluster_label"
                ],
                "member_processing_ids": item["member_processing_ids"],
                "gemini_proposal": question["automatic_groups"][index][
                    "provider_proposal"
                ],
                "analyst_decision": None,
            }
            for index, item in enumerate(question["workspace"]["active_groups"])
        ]
        question["unresolved_answers"] = [
            {
                "processing_id": processing_id,
                "reason": next(
                    answer["discovery_evidence"]["status"]
                    for answer in question["answers"]
                    if answer["processing_id"] == processing_id
                ),
                "analyst_decision": None,
            }
            for processing_id in question["workspace"]["needs_attention"]
        ]
        question.pop("automatic_groups")
        question.pop("workspace")
    path.write_text(__import__("json").dumps(v3), encoding="utf-8")

    client = create_review_app(path, working_directory=tmp_path).test_client()
    page = client.get("/")
    state = client.get("/api/state").get_json()

    assert page.status_code == 200
    assert b"Read-only legacy review" in page.data
    assert state["read_only"] is True
    assert client.post("/api/commands", json={}).status_code == 400
