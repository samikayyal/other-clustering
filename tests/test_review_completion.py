from __future__ import annotations

import json
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
    assert summary["outstanding"] == {
        "needs_review_group_count": 1,
        "needs_attention_answer_count": 1,
    }
    assert summary["net_changes"] == {
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


def test_complete_review_allocates_values_persists_summary_and_locks(
    tmp_path: Path,
) -> None:
    document = _complete_ready_review(tmp_path)
    summary = project_review_changes(document)
    assert summary["can_complete"] is True

    completed = _command(document, {"type": "complete_review"})

    assert completed["status"] == "complete"
    assert completed["completed_at_utc"].endswith("Z")
    assert completed["completion_summary"] == summary
    groups = completed["questions"][0]["workspace"]["active_groups"]
    assert groups[0]["decision"]["allocated_value"] == 101
    assert groups[1]["decision"]["allocated_value"] == 102
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
