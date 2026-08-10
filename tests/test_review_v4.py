from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from other_cluster.errors import ReviewFileError
from other_cluster.review_file import apply_review_command, load_review_file
from other_cluster.review_validation import validate_review_file
from other_cluster.review_webapp import create_review_app

from .test_review_file import _review


def _review_with_two_active_groups(tmp_path: Path):
    _, path = _review(tmp_path)
    document = load_review_file(path)
    question = document["questions"][0]
    workspace = question["workspace"]
    lone_answer = workspace["needs_attention"].pop()
    first_group = workspace["active_groups"][0]
    first_group["review_state"] = "confirmed"
    workspace["active_groups"].append(
        {
            "group_id": "B5_other:reviewer:test",
            "origin": "reviewer",
            "creation_order": 1,
            "member_processing_ids": [lone_answer],
            "decision": {
                "decision": "existing_choice",
                "selected_choice_value": 2,
                "english_label": None,
                "arabic_label": None,
            },
            "review_state": "confirmed",
        }
    )
    validate_review_file(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, document


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


def test_move_answers_to_active_group_is_atomic_and_retires_empty_source(
    tmp_path: Path,
) -> None:
    path, initial = _review_with_two_active_groups(tmp_path)
    question = initial["questions"][0]
    first_group, destination_group = question["workspace"]["active_groups"]
    selected = list(first_group["member_processing_ids"])
    client = create_review_app(path, working_directory=tmp_path).test_client()

    response = client.post(
        "/api/commands",
        json={
            "expected_revision": 0,
            "command": {
                "type": "move_answers",
                "question_id": question["question_id"],
                "processing_ids": selected,
                "source_locations": [
                    {
                        "processing_id": processing_id,
                        "location": "active_group",
                        "group_id": first_group["group_id"],
                    }
                    for processing_id in selected
                ],
                "destination": {
                    "location": "active_group",
                    "group_id": destination_group["group_id"],
                },
            },
        },
    )

    assert response.status_code == 200
    updated = response.get_json()["review"]
    workspace = updated["questions"][0]["workspace"]
    assert updated["revision"] == 1
    assert load_review_file(path) == updated
    assert [group["group_id"] for group in workspace["active_groups"]] == [
        destination_group["group_id"]
    ]
    assert workspace["active_groups"][0]["member_processing_ids"] == sorted(
        answer["processing_id"] for answer in question["answers"]
    )
    assert workspace["active_groups"][0]["decision"] == destination_group["decision"]
    assert workspace["active_groups"][0]["review_state"] == "needs_review"
    assert workspace["retired_groups"] == [
        {
            **first_group,
            "member_processing_ids": [],
            "review_state": "needs_review",
        }
    ]
    history = workspace["history"][0]
    assert history["operation"] == "move_answers"
    assert history["group_id"] == destination_group["group_id"]
    assert history["affected_processing_ids"] == selected
    assert history["affected_answer_count"] == 3
    assert history["affected_response_count"] == 4
    assert history["after"]["destination"] == {
        "location": "active_group",
        "group_id": destination_group["group_id"],
    }

    stale = client.post(
        "/api/commands",
        json={
            "expected_revision": 0,
            "command": {
                "type": "move_answers",
                "question_id": question["question_id"],
                "processing_ids": selected,
                "source_locations": [],
                "destination": {"location": "needs_attention"},
            },
        },
    )
    assert stale.status_code == 409
    assert load_review_file(path) == updated


def test_retired_group_labels_do_not_reserve_active_category_labels(
    tmp_path: Path,
) -> None:
    path, initial = _review_with_two_active_groups(tmp_path)
    question = initial["questions"][0]
    source_group, destination_group = question["workspace"]["active_groups"]
    selected = list(source_group["member_processing_ids"])
    client = create_review_app(path, working_directory=tmp_path).test_client()

    moved_response = client.post(
        "/api/commands",
        json={
            "expected_revision": 0,
            "command": {
                "type": "move_answers",
                "question_id": question["question_id"],
                "processing_ids": selected,
                "source_locations": [
                    {
                        "processing_id": processing_id,
                        "location": "active_group",
                        "group_id": source_group["group_id"],
                    }
                    for processing_id in selected
                ],
                "destination": {
                    "location": "active_group",
                    "group_id": destination_group["group_id"],
                },
            },
        },
    )
    assert moved_response.status_code == 200

    relabeled_response = client.post(
        "/api/commands",
        json={
            "expected_revision": 1,
            "command": {
                "type": "apply_decision",
                "question_id": question["question_id"],
                "group_id": destination_group["group_id"],
                "decision": {
                    "decision": "new_category",
                    "selected_choice_value": None,
                    "english_label": source_group["decision"]["english_label"],
                    "arabic_label": source_group["decision"]["arabic_label"],
                },
            },
        },
    )

    assert relabeled_response.status_code == 200
    updated = relabeled_response.get_json()["review"]
    assert updated["revision"] == 2
    assert updated["questions"][0]["workspace"]["active_groups"][0]["decision"] == {
        "decision": "new_category",
        "selected_choice_value": None,
        "english_label": "Fresh category",
        "arabic_label": "فئة جديدة",
    }


def test_move_answers_from_multiple_groups_to_needs_attention_preserves_order(
    tmp_path: Path,
) -> None:
    path, initial = _review_with_two_active_groups(tmp_path)
    question = initial["questions"][0]
    first_group, second_group = question["workspace"]["active_groups"]
    answers = {answer["text"]: answer for answer in question["answers"]}
    selected = [answers["d"]["processing_id"], answers["a"]["processing_id"]]
    client = create_review_app(path, working_directory=tmp_path).test_client()

    response = client.post(
        "/api/commands",
        json={
            "expected_revision": 0,
            "command": {
                "type": "move_answers",
                "question_id": question["question_id"],
                "processing_ids": selected,
                "source_locations": [
                    {
                        "processing_id": selected[0],
                        "location": "active_group",
                        "group_id": second_group["group_id"],
                    },
                    {
                        "processing_id": selected[1],
                        "location": "active_group",
                        "group_id": first_group["group_id"],
                    },
                ],
                "destination": {"location": "needs_attention"},
            },
        },
    )

    assert response.status_code == 200
    workspace = response.get_json()["review"]["questions"][0]["workspace"]
    assert workspace["needs_attention"] == sorted(selected)
    assert workspace["active_groups"][0]["member_processing_ids"] == sorted(
        answer["processing_id"]
        for answer in question["answers"]
        if answer["text"] in {"b", "c"}
    )
    assert workspace["active_groups"][0]["decision"] == first_group["decision"]
    assert workspace["active_groups"][0]["review_state"] == "needs_review"
    assert workspace["retired_groups"][0]["group_id"] == second_group["group_id"]
    assert workspace["history"][0]["affected_processing_ids"] == sorted(selected)
    assert workspace["history"][0]["affected_response_count"] == 3


def test_move_command_rejects_wrong_answer_source_or_destination_without_effect(
    tmp_path: Path,
) -> None:
    path, initial = _review_with_two_active_groups(tmp_path)
    question = initial["questions"][0]
    first_group = question["workspace"]["active_groups"][0]
    processing_id = first_group["member_processing_ids"][0]
    original = path.read_bytes()
    client = create_review_app(path, working_directory=tmp_path).test_client()
    base_command = {
        "type": "move_answers",
        "question_id": question["question_id"],
        "processing_ids": [processing_id],
        "source_locations": [
            {
                "processing_id": processing_id,
                "location": "active_group",
                "group_id": first_group["group_id"],
            }
        ],
        "destination": {"location": "needs_attention"},
    }
    invalid_commands = []
    unknown_answer = deepcopy(base_command)
    unknown_answer["processing_ids"] = ["missing-answer"]
    unknown_answer["source_locations"][0]["processing_id"] = "missing-answer"
    invalid_commands.append(unknown_answer)
    non_string_answer = deepcopy(base_command)
    non_string_answer["processing_ids"] = [{}]
    non_string_answer["source_locations"][0]["processing_id"] = {}
    invalid_commands.append(non_string_answer)
    wrong_source = deepcopy(base_command)
    wrong_source["source_locations"][0]["location"] = "needs_attention"
    wrong_source["source_locations"][0].pop("group_id")
    invalid_commands.append(wrong_source)
    unknown_destination = deepcopy(base_command)
    unknown_destination["destination"] = {
        "location": "active_group",
        "group_id": "missing-group",
    }
    invalid_commands.append(unknown_destination)

    for command in invalid_commands:
        response = client.post(
            "/api/commands",
            json={"expected_revision": 0, "command": command},
        )
        assert response.status_code == 400
        assert path.read_bytes() == original


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
