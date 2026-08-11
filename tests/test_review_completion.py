from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from other_cluster.errors import ReviewFileError
from other_cluster.review_completion import project_review_changes
from other_cluster.review_file import apply_review_command, load_review_file
from other_cluster.review_validation import validate_review_file
from other_cluster.review_webapp import create_review_app

from .test_review_file import _review


def _complete_ready_review(tmp_path: Path) -> dict:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    question = document["questions"][0]
    workspace = question["workspace"]
    automatic = workspace["active_groups"][0]
    automatic["review_state"] = "confirmed"
    unresolved = workspace["needs_attention"].pop()
    workspace["active_groups"].append(
        {
            "group_id": "B5_other:reviewer:completion",
            "origin": "reviewer",
            "creation_order": 1,
            "member_processing_ids": [unresolved],
            "decision": {
                "decision": "new_category",
                "selected_choice_value": None,
                "english_label": "Local category",
                "arabic_label": "فئة محلية",
            },
            "review_state": "confirmed",
        }
    )
    validate_review_file(document)
    return document


def _command(document: dict, command: dict) -> dict:
    return apply_review_command(
        document,
        {"expected_revision": document["revision"], "command": command},
    )


def test_review_changes_projects_outstanding_work_and_net_current_changes(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)

    summary = project_review_changes(document)

    assert summary["can_complete"] is False
    assert summary["outstanding"]["needs_review_group_count"] == 1
    assert summary["outstanding"]["needs_attention_answer_count"] == 1
    assert (
        summary["outstanding"]["groups"][0]["group_id"]
        == (document["questions"][0]["workspace"]["active_groups"][0]["group_id"])
    )
    assert (
        summary["outstanding"]["needs_attention_answers"][0]["processing_id"]
        == document["questions"][0]["workspace"]["needs_attention"][0]
    )
    assert {
        key: summary["net_changes"][key]
        for key in (
            "moved_canonical_answer_count",
            "moved_response_count",
            "reviewer_created_group_count",
            "retired_original_group_count",
            "excluded_answer_count",
            "excluded_response_count",
            "confirmation_invalidated_group_count",
        )
    } == {
        "moved_canonical_answer_count": 0,
        "moved_response_count": 0,
        "reviewer_created_group_count": 0,
        "retired_original_group_count": 0,
        "excluded_answer_count": 0,
        "excluded_response_count": 0,
        "confirmation_invalidated_group_count": 0,
    }
    assert {failure["code"] for failure in summary["blocking_failures"]} == {
        "needs_attention",
        "needs_review",
    }


def test_undo_removes_reversed_move_from_net_change_totals(tmp_path: Path) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    question = document["questions"][0]
    processing_id = question["workspace"]["needs_attention"][0]
    destination = question["workspace"]["active_groups"][0]["group_id"]

    moved = _command(
        document,
        {
            "type": "move_answers",
            "question_id": question["question_id"],
            "processing_ids": [processing_id],
            "source_locations": [
                {"processing_id": processing_id, "location": "needs_attention"}
            ],
            "destination": {"location": "active_group", "group_id": destination},
        },
    )
    assert (
        project_review_changes(moved)["net_changes"]["moved_canonical_answer_count"]
        == 1
    )

    undone = _command(moved, {"type": "undo", "question_id": question["question_id"]})
    assert (
        project_review_changes(undone)["net_changes"]["moved_canonical_answer_count"]
        == 0
    )
    assert [
        entry["operation"] for entry in undone["questions"][0]["workspace"]["history"]
    ] == [
        "move_answers",
        "undo",
    ]


def test_undo_removes_confirmation_invalidations_from_reversed_edit(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    question = document["questions"][0]
    source, destination = question["workspace"]["active_groups"]
    processing_id = source["member_processing_ids"][0]

    moved = _command(
        document,
        {
            "type": "move_answers",
            "question_id": question["question_id"],
            "processing_ids": [processing_id],
            "source_locations": [
                {
                    "processing_id": processing_id,
                    "location": "active_group",
                    "group_id": source["group_id"],
                }
            ],
            "destination": {
                "location": "active_group",
                "group_id": destination["group_id"],
            },
        },
    )
    assert (
        project_review_changes(moved)["net_changes"][
            "confirmation_invalidated_group_count"
        ]
        == 2
    )

    undone = _command(moved, {"type": "undo", "question_id": question["question_id"]})

    assert (
        project_review_changes(undone)["net_changes"]["confirmation_invalidated_groups"]
        == []
    )


def test_retired_automatic_group_uses_immutable_original_membership_counts(
    tmp_path: Path,
) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    question = document["questions"][0]
    group = question["workspace"]["active_groups"][0]
    processing_ids = list(group["member_processing_ids"])
    answers_by_id = {answer["processing_id"]: answer for answer in question["answers"]}
    expected_response_count = sum(
        answers_by_id[processing_id]["occurrence_count"]
        for processing_id in processing_ids
    )

    updated = _command(
        document,
        {
            "type": "move_answers",
            "question_id": question["question_id"],
            "processing_ids": processing_ids,
            "source_locations": [
                {
                    "processing_id": processing_id,
                    "location": "active_group",
                    "group_id": group["group_id"],
                }
                for processing_id in processing_ids
            ],
            "destination": {"location": "needs_attention"},
        },
    )

    retired = project_review_changes(updated)["net_changes"]["retired_original_groups"]
    assert retired == [
        {
            "question_id": question["question_id"],
            "group_id": group["group_id"],
            "canonical_answer_count": len(processing_ids),
            "response_count": expected_response_count,
        }
    ]


def test_complete_review_allocates_values_persists_summary_and_locks(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    evidence_before = deepcopy(document["questions"][0])
    summary = project_review_changes(document)
    assert summary["can_complete"] is True

    completed = _command(document, {"type": "complete_review"})

    assert completed["status"] == "complete"
    assert completed["completed_at_utc"].endswith("Z")
    assert completed["completion_summary"] == summary
    groups = completed["questions"][0]["workspace"]["active_groups"]
    assert groups[0]["decision"]["allocated_value"] == 101
    assert groups[1]["decision"]["allocated_value"] == 102
    completed_question = completed["questions"][0]
    assert completed_question["automatic_groups"] == evidence_before["automatic_groups"]
    assert completed_question["answers"] == evidence_before["answers"]
    assert (
        completed_question["workspace"]["history"]
        == evidence_before["workspace"]["history"]
    )
    assert (
        completed_question["workspace"]["retired_groups"]
        == evidence_before["workspace"]["retired_groups"]
    )
    assert all(
        question["workspace"]["undo"] is None for question in completed["questions"]
    )
    validate_review_file(completed, require_complete=True)

    with pytest.raises(ReviewFileError, match="read-only"):
        _command(completed, {"type": "confirm_group"})


def test_similar_labels_and_provider_warnings_are_non_blocking_cautions(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    question = document["questions"][0]
    question["existing_choices"].append(
        {
            "value": 3,
            "english_label": "Fresh categories",
            "arabic_label": "فئات جديدة",
            "code_row": 100,
        }
    )
    proposal = question["automatic_groups"][0]["provider_proposal"]
    proposal.update(
        decision="provider_error",
        selected_choice_value=None,
        english_label=None,
        arabic_label=None,
        rejection_reason=None,
        provider_error="HTTP 503",
    )
    validate_review_file(document)

    summary = project_review_changes(document)

    assert summary["can_complete"] is True
    assert {item["code"] for item in summary["cautions"]} >= {
        "provider_warning",
        "similar_label",
    }


def test_similar_existing_choices_do_not_create_review_cautions(tmp_path: Path) -> None:
    _, path = _review(tmp_path)
    document = load_review_file(path)
    question = document["questions"][0]
    question["existing_choices"].extend(
        [
            {
                "value": 3,
                "english_label": "Fresh category",
                "arabic_label": "فئة حديثة",
                "code_row": 100,
            },
            {
                "value": 4,
                "english_label": "Fresh categories",
                "arabic_label": "فئات حديثة",
                "code_row": 101,
            },
        ]
    )
    for group in question["workspace"]["active_groups"]:
        group["decision"] = {
            "decision": "existing_choice",
            "selected_choice_value": 1,
            "english_label": None,
            "arabic_label": None,
        }

    cautions = project_review_changes(document)["cautions"]

    assert all(item["code"] != "similar_label" for item in cautions)


def test_summary_identifies_groups_whose_confirmation_was_invalidated(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    question = document["questions"][0]
    group = question["workspace"]["active_groups"][0]

    updated = _command(
        document,
        {
            "type": "apply_decision",
            "question_id": question["question_id"],
            "group_id": group["group_id"],
            "decision": deepcopy(group["decision"]),
        },
    )
    summary = project_review_changes(updated)

    assert summary["net_changes"]["confirmation_invalidated_groups"] == [
        {"question_id": question["question_id"], "group_id": group["group_id"]}
    ]


def test_exclusions_do_not_block_and_existing_choice_values_may_repeat(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    question = document["questions"][0]
    workspace = question["workspace"]
    excluded_group = workspace["active_groups"].pop()
    workspace["excluded_answers"] = excluded_group["member_processing_ids"]
    excluded_group["member_processing_ids"] = []
    excluded_group["review_state"] = "needs_review"
    workspace["retired_groups"].append(excluded_group)
    workspace["active_groups"][0]["decision"] = {
        "decision": "existing_choice",
        "selected_choice_value": 1,
        "english_label": None,
        "arabic_label": None,
    }
    validate_review_file(document)

    summary = project_review_changes(document)
    assert summary["can_complete"] is True
    assert summary["net_changes"]["excluded_answer_count"] == 1
    assert summary["net_changes"]["moved_canonical_answer_count"] == 0

    completed = _command(document, {"type": "complete_review"})
    assert completed["questions"][0]["workspace"]["active_groups"][0]["decision"] == {
        "decision": "existing_choice",
        "selected_choice_value": 1,
        "english_label": None,
        "arabic_label": None,
        "allocated_value": None,
    }


def test_completion_uses_stable_creation_order_and_reserves_existing_values(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    question = document["questions"][0]
    question["existing_choices"].append(
        {
            "value": 101,
            "english_label": "Reserved",
            "arabic_label": "محجوز",
            "code_row": 99,
        }
    )
    completed = _command(document, {"type": "complete_review"})
    values = [
        group["decision"]["allocated_value"]
        for group in completed["questions"][0]["workspace"]["active_groups"]
    ]
    assert values == [102, 103]


def test_flask_exposes_read_only_summary_and_explicit_completion(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    review_path = tmp_path / "ready-review.json"
    review_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    before = review_path.read_bytes()
    client = create_review_app(review_path, working_directory=tmp_path).test_client()

    page = client.get("/")
    state = client.get("/api/state").get_json()
    assert page.status_code == 200
    assert b"Review changes" in page.data
    assert state["review_changes"]["can_complete"] is True
    assert review_path.read_bytes() == before

    response = client.post(
        "/api/commands",
        json={
            "expected_revision": document["revision"],
            "command": {"type": "complete_review"},
        },
    )
    assert response.status_code == 200
    assert response.get_json()["review"]["status"] == "complete"
    assert load_review_file(review_path)["status"] == "complete"

    rejected = client.post(
        "/api/commands",
        json={
            "expected_revision": response.get_json()["review"]["revision"],
            "command": {"type": "confirm_group"},
        },
    )
    assert rejected.status_code == 400
    assert "read-only" in rejected.get_json()["error"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicated",
        "empty",
        "invalid_label",
        "duplicate_label",
        "schema",
    ],
)
def test_validation_boundary_blocks_every_invalid_completion_partition(
    tmp_path: Path, mutation: str
) -> None:
    document = _complete_ready_review(tmp_path)
    question = document["questions"][0]
    groups = question["workspace"]["active_groups"]
    member = groups[0]["member_processing_ids"][0]
    if mutation == "missing":
        groups[0]["member_processing_ids"].remove(member)
    elif mutation == "duplicated":
        question["workspace"]["needs_attention"].append(member)
    elif mutation == "empty":
        groups[1]["member_processing_ids"] = []
    elif mutation == "invalid_label":
        groups[1]["decision"]["english_label"] = ""
    elif mutation == "duplicate_label":
        groups[1]["decision"] = dict(groups[0]["decision"])
    else:
        document["unexpected"] = True

    with pytest.raises(ReviewFileError):
        validate_review_file(document)
    with pytest.raises(ReviewFileError):
        _command(document, {"type": "complete_review"})
