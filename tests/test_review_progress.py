from __future__ import annotations

from other_cluster.review_progress import project_review_progress
from other_cluster.review_webapp import create_review_app

from .test_review_file import _review


def _proposal(
    decision: str = "reject_cluster", *, provider_error: str | None = None
) -> dict[str, object | None]:
    return {
        "decision": decision,
        "selected_choice_value": None,
        "english_label": None,
        "arabic_label": None,
        "rejection_reason": "not_a_single_category"
        if decision == "reject_cluster"
        else None,
        "provider_error": provider_error,
    }


def _group(
    group_id: str,
    member_ids: list[str],
    *,
    state: str = "needs_review",
    origin: str = "automatic",
    decision: dict[str, object | None] | None = None,
) -> dict[str, object]:
    return {
        "group_id": group_id,
        "origin": origin,
        "creation_order": 0,
        "member_processing_ids": member_ids,
        "decision": decision,
        "review_state": state,
    }


def _question(
    question_id: str,
    answers: list[tuple[str, int]],
    automatic_groups: list[dict[str, object]],
    workspace: dict[str, object],
) -> dict[str, object]:
    return {
        "question_id": question_id,
        "answers": [
            {"processing_id": processing_id, "occurrence_count": occurrence_count}
            for processing_id, occurrence_count in answers
        ],
        "automatic_groups": automatic_groups,
        "workspace": workspace,
    }


def test_projects_counts_status_and_provider_warning_provenance() -> None:
    warning_group = {
        "group_id": "automatic-warning",
        "member_processing_ids": ["a", "b"],
        "provider_proposal": _proposal("provider_error", provider_error="timeout"),
    }
    plain_group = {
        "group_id": "automatic-plain",
        "member_processing_ids": ["c"],
        "provider_proposal": _proposal(),
    }
    document = {
        "questions": [
            _question(
                "q1",
                [("a", 2), ("b", 3), ("c", 1), ("d", 4), ("e", 2)],
                [warning_group, plain_group],
                {
                    "active_groups": [
                        _group("automatic-warning", ["a", "b"], state="confirmed"),
                        _group("automatic-plain", ["c"]),
                    ],
                    "needs_attention": ["d"],
                    "excluded_answers": ["e"],
                    "retired_groups": [],
                    "history": [],
                },
            )
        ]
    }

    projection = project_review_progress(document)

    assert projection == {
        "complete_question_count": 0,
        "total_question_count": 1,
        "questions": [
            {
                "question_id": "q1",
                "resolved_item_count": 2,
                "remaining_item_count": 2,
                "total_unique_answer_count": 5,
                "total_response_count": 12,
                "confirmed_group_count": 1,
                "active_group_count": 2,
                "needs_review_group_count": 1,
                "needs_attention": {
                    "unique_answer_count": 1,
                    "response_count": 4,
                },
                "excluded": {"unique_answer_count": 1, "response_count": 2},
                "status": "not_started",
                "modified": True,
                "has_exclusions": True,
                "has_provider_warning": True,
                "provider_warning_processing_ids": ["a", "b"],
            }
        ],
    }


def test_status_and_modified_use_current_state_but_keep_undo_history() -> None:
    proposal = {
        "decision": "existing_choice",
        "selected_choice_value": 7,
        "english_label": None,
        "arabic_label": None,
        "rejection_reason": None,
        "provider_error": None,
    }
    automatic_group = {
        "group_id": "automatic",
        "member_processing_ids": ["a"],
        "provider_proposal": proposal,
    }
    expected_decision = {
        "decision": "existing_choice",
        "selected_choice_value": 7,
        "english_label": None,
        "arabic_label": None,
    }
    document = {
        "questions": [
            _question(
                "q1",
                [("a", 1), ("b", 2)],
                [automatic_group],
                {
                    "active_groups": [
                        _group("automatic", ["a"], decision=expected_decision)
                    ],
                    "needs_attention": ["b"],
                    "excluded_answers": [],
                    "retired_groups": [],
                    "history": [],
                },
            )
        ]
    }

    initial = project_review_progress(document)["questions"][0]

    assert initial["status"] == "not_started"
    assert initial["modified"] is False

    document["questions"][0]["workspace"]["history"].append({"operation": "undo"})
    after_exact_undo = project_review_progress(document)["questions"][0]

    assert after_exact_undo["status"] == "in_progress"
    assert after_exact_undo["modified"] is False

    document["questions"][0]["workspace"]["active_groups"][0]["decision"] = {
        **expected_decision,
        "selected_choice_value": 8,
    }
    changed_decision = project_review_progress(document)["questions"][0]

    assert changed_decision["modified"] is True


def test_provider_warning_members_follow_current_groups_and_exclusions() -> None:
    automatic_group = {
        "group_id": "automatic-warning",
        "member_processing_ids": ["a", "b"],
        "provider_proposal": _proposal("provider_error", provider_error="timeout"),
    }
    document = {
        "questions": [
            _question(
                "q1",
                [("a", 1), ("b", 2)],
                [automatic_group],
                {
                    "active_groups": [
                        _group("reviewer", ["a"], origin="reviewer")
                    ],
                    "needs_attention": [],
                    "excluded_answers": ["b"],
                    "retired_groups": [{"group_id": "automatic-warning"}],
                    "history": [{"operation": "move_answers"}],
                },
            )
        ]
    }

    question = project_review_progress(document)["questions"][0]

    assert question["has_provider_warning"] is True
    assert question["provider_warning_processing_ids"] == ["a", "b"]


def test_complete_is_derived_from_current_groups_and_needs_attention() -> None:
    automatic_group = {
        "group_id": "automatic",
        "member_processing_ids": ["a"],
        "provider_proposal": _proposal(),
    }
    document = {
        "questions": [
            _question(
                "q1",
                [("a", 2)],
                [automatic_group],
                {
                    "active_groups": [
                        _group("automatic", ["a"], state="confirmed")
                    ],
                    "needs_attention": [],
                    "excluded_answers": [],
                    "retired_groups": [],
                    "history": [],
                },
            ),
            _question(
                "q2",
                [("b", 3)],
                [],
                {
                    "active_groups": [],
                    "needs_attention": [],
                    "excluded_answers": ["b"],
                    "retired_groups": [],
                    "history": [{"operation": "exclude_answers"}],
                },
            ),
        ]
    }

    projection = project_review_progress(document)

    assert projection["complete_question_count"] == 2
    assert projection["total_question_count"] == 2
    assert [question["status"] for question in projection["questions"]] == [
        "complete",
        "complete",
    ]


def test_flask_state_exposes_server_owned_progress_projection(tmp_path) -> None:
    _, review_path = _review(tmp_path)
    client = create_review_app(review_path, working_directory=tmp_path).test_client()

    state = client.get("/api/state").get_json()

    assert state["progress"] == project_review_progress(state["review"])
