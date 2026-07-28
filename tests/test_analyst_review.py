from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from other_cluster.analyst_review import (
    add_analyst_category,
    complete_review,
    create_initial_draft,
    load_or_create_draft,
    load_review_package,
    save_draft,
    validate_draft,
)
from other_cluster.errors import AnalystReviewError
from other_cluster.review_webapp import create_review_app

_RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
_APPROVAL_ID = "223e4567-e89b-42d3-a456-426614174000"


def _answer(
    processing_id: str,
    text: str,
    *,
    status: str | None,
    cluster_id: str | None = None,
) -> dict:
    return {
        "processing_id": processing_id,
        "text": text,
        "occurrence_count": 1,
        "row_mappings": [
            {
                "answer_id": f"answer:{processing_id}",
                "respondent_key": f"key:{processing_id}",
                "sheet": "Data",
                "row": int(processing_id[1:]) + 1,
                "column": 4,
                "coordinate": f"D{int(processing_id[1:]) + 1}",
            }
        ],
        "discovery_evidence": {
            "raw_cluster_label": 0 if cluster_id else None,
            "membership_probability": 0.9 if cluster_id else None,
            "status": status,
            "cluster_id": cluster_id,
        },
    }


def _package(*, two_categories: bool = False) -> dict:
    answers = [
        _answer("p1", "Lebanese", status=None),
        _answer(
            "p2", "Local origin", status="accepted_cluster", cluster_id="cluster-a"
        ),
        _answer("p3", "Noise answer", status="noise"),
    ]
    categories = [
        {
            "review_item_id": "proposed_category:cluster-a",
            "cluster_id": "cluster-a",
            "proposed_value": 101,
            "english_label": "Local Origins",
            "arabic_label": "اصول محلية",
            "member_processing_ids": ["p2"],
        }
    ]
    unresolved = [
        {
            "review_item_id": "unresolved:p3",
            "processing_id": "p3",
            "reason": "noise",
            "cluster_id": None,
        }
    ]
    merges = []
    if two_categories:
        answers.append(
            _answer(
                "p4",
                "Nearby origin",
                status="accepted_cluster",
                cluster_id="cluster-b",
            )
        )
        categories.append(
            {
                "review_item_id": "proposed_category:cluster-b",
                "cluster_id": "cluster-b",
                "proposed_value": 102,
                "english_label": "Nearby Origins",
                "arabic_label": "اصول قريبة",
                "member_processing_ids": ["p4"],
            }
        )
        merges.append(
            {
                "review_item_id": "merge:cluster-a:cluster-b",
                "first_cluster_id": "cluster-a",
                "second_cluster_id": "cluster-b",
                "cosine_similarity": 0.93,
                "combined_member_processing_ids": ["p2", "p4"],
            }
        )
    return {
        "schema_version": 1,
        "analysis_run_id": _RUN_ID,
        "created_at_utc": "2026-07-28T00:00:00.000000Z",
        "source_workbook": {
            "input_kind": "local_xlsx",
            "source_locator": "D:\\input.xlsx",
            "display_name": "Input Workbook.xlsx",
            "size_bytes": 123,
            "sha256": "a" * 64,
        },
        "questions": [
            {
                "question_id": "B5_other",
                "question_text": {
                    "english": "Nationality",
                    "arabic": "الجنسية",
                },
                "source_column": "B5_other",
                "existing_choices": [
                    {
                        "value": 1,
                        "english_label": "Lebanese",
                        "arabic_label": "لبناني",
                        "code_row": 2,
                    },
                    {
                        "value": 150,
                        "english_label": "Existing High",
                        "arabic_label": "قيمة حالية",
                        "code_row": 3,
                    },
                ],
                "answers": answers,
                "existing_choice_assignments": [
                    {
                        "review_item_id": "existing_assignment:p1",
                        "processing_id": "p1",
                        "proposed_choice_value": 1,
                        "provider_decision": "assign",
                    }
                ],
                "proposed_categories": categories,
                "merge_suggestions": merges,
                "unresolved_answers": unresolved,
            }
        ],
        "warnings": [],
    }


def _write_package(tmp_path: Path, *, two_categories: bool = False) -> Path:
    return _write_raw_package(tmp_path, _package(two_categories=two_categories))


def _write_raw_package(tmp_path: Path, package: dict) -> Path:
    path = tmp_path / "input_review.json"
    path.write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _complete_simple_draft(draft: dict) -> dict:
    completed = deepcopy(draft)
    completed["analyst_name"] = "Sami Analyst"
    selections = {
        "existing_assignment:p1": "approved",
        "proposed_category:cluster-a": "approved",
        "unresolved:p3": "acknowledged",
    }
    for item in completed["review_item_dispositions"]:
        item["disposition"] = selections[item["review_item_id"]]
    return completed


def test_initial_draft_preserves_proposals_but_requires_every_explicit_disposition(
    tmp_path,
) -> None:
    loaded = load_review_package(_write_package(tmp_path))

    draft = create_initial_draft(loaded)

    assert draft["review_package_sha256"] == loaded.sha256
    assert [item["disposition"] for item in draft["review_item_dispositions"]] == [
        None,
        None,
        None,
    ]
    state = draft["questions"][0]
    assert state["categories"][0]["member_processing_ids"] == ["p2"]
    assert [item["decision"] for item in state["answer_dispositions"]] == [
        "existing_choice",
        "new_category",
        "unresolved",
    ]
    with pytest.raises(AnalystReviewError, match="invalid disposition"):
        validate_draft(loaded, draft, require_complete=True)


def test_draft_is_atomic_resumable_and_bound_to_exact_package_hash(tmp_path) -> None:
    loaded = load_review_package(_write_package(tmp_path))
    state_directory = tmp_path / "review_state"
    draft = create_initial_draft(loaded)

    saved, destination = save_draft(
        loaded,
        draft,
        state_directory,
        saved_at_utc=datetime(2026, 7, 28, tzinfo=UTC),
    )

    assert destination.exists()
    assert load_or_create_draft(loaded, state_directory) == saved
    stale = deepcopy(saved)
    stale["review_package_sha256"] = "b" * 64
    with pytest.raises(AnalystReviewError, match="SHA-256"):
        save_draft(loaded, stale, state_directory)
    assert load_or_create_draft(loaded, state_directory) == saved


def test_complete_review_writes_immutable_utf8_approval_without_workbook_output(
    tmp_path,
) -> None:
    loaded = load_review_package(_write_package(tmp_path))
    draft = _complete_simple_draft(create_initial_draft(loaded))

    approval, destination = complete_review(
        loaded,
        draft,
        tmp_path / "review_approvals",
        approval_id=_APPROVAL_ID,
        approved_at_utc=datetime(2026, 7, 28, tzinfo=UTC),
    )

    raw = destination.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "اصول محلية" in raw.decode("utf-8")
    assert approval["review_package_sha256"] == loaded.sha256
    assert approval["questions"][0]["final_categories"][0]["value"] == 101
    assert approval["complete_review_confirmed"] is True
    assert approval["authorize_finalization"] is True
    assert list(tmp_path.glob("*.xlsx")) == []
    with pytest.raises(AnalystReviewError, match="will not be overwritten"):
        complete_review(
            loaded,
            draft,
            tmp_path / "review_approvals",
            approval_id=_APPROVAL_ID,
        )


def test_manual_category_gets_stable_id_and_smallest_unused_non_recycled_value(
    tmp_path,
) -> None:
    loaded = load_review_package(_write_package(tmp_path))
    draft = create_initial_draft(loaded)
    draft, category_id = add_analyst_category(
        loaded,
        draft,
        question_id="B5_other",
        english_label="Noise Meaning",
        arabic_label="معنى الضوضاء",
        member_processing_ids=["p3"],
    )
    state = draft["questions"][0]
    category = state["categories"][-1]
    answer = state["answer_dispositions"][-1]
    assert answer["final_category_id"] == category_id
    draft["analyst_name"] = "Sami"
    selections = {
        "existing_assignment:p1": "approved",
        "proposed_category:cluster-a": "approved",
        "unresolved:p3": "assigned",
    }
    for item in draft["review_item_dispositions"]:
        item["disposition"] = selections[item["review_item_id"]]

    approval, _ = complete_review(
        loaded,
        draft,
        tmp_path / "approvals",
        approval_id=_APPROVAL_ID,
    )

    categories = approval["questions"][0]["final_categories"]
    assert category_id == "analyst-category:0001"
    assert {item["value"] for item in categories} == {101, 102}
    manual = next(item for item in categories if item["origin"] == "manual")
    assert manual["value"] == 102
    assert any(
        item["operation"] == "create_category"
        for item in approval["questions"][0]["analyst_overrides"]
    )


def test_category_creation_requires_members_and_preserves_a_valid_draft(
    tmp_path,
) -> None:
    loaded = load_review_package(_write_package(tmp_path))
    draft = create_initial_draft(loaded)

    with pytest.raises(AnalystReviewError, match="must contain unique"):
        add_analyst_category(
            loaded,
            draft,
            question_id="B5_other",
            english_label="Noise Meaning",
            arabic_label="معنى الضوضاء",
            member_processing_ids=[],
        )
    with pytest.raises(AnalystReviewError, match="must not use a prohibited"):
        add_analyst_category(
            loaded,
            draft,
            question_id="B5_other",
            english_label="Other",
            arabic_label="معنى الضوضاء",
            member_processing_ids=["p3"],
        )
    validate_draft(loaded, draft, require_complete=False)


def test_web_category_creation_autosaves_a_complete_valid_draft(tmp_path) -> None:
    app = create_review_app(_write_package(tmp_path), working_directory=tmp_path)
    app.testing = True
    client = app.test_client()
    draft = client.get("/api/state").get_json()["draft"]

    response = client.post(
        "/api/categories",
        json={
            "draft": draft,
            "question_id": "B5_other",
            "english_label": "Noise Meaning",
            "arabic_label": "معنى الضوضاء",
            "origin": "manual",
            "component_cluster_ids": [],
            "member_processing_ids": ["p3"],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    saved = payload["draft"]
    category = saved["questions"][0]["categories"][-1]
    assert category["member_processing_ids"] == ["p3"]
    assert (
        saved["questions"][0]["answer_dispositions"][-1]["final_category_id"]
        == (payload["final_category_id"])
    )
    assert Path(payload["draft_path"]).exists()


def test_review_javascript_renders_discovery_evidence() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "other_cluster" / "static" / "review.js"
    ).read_text(encoding="utf-8")

    assert "function renderDiscoveryEvidence" in source
    assert "membership_probability" in source
    assert "raw label:" in source


def test_approved_merge_collapses_components_and_retains_smallest_value(
    tmp_path,
) -> None:
    loaded = load_review_package(_write_package(tmp_path, two_categories=True))
    draft = create_initial_draft(loaded)
    draft, merged_id = add_analyst_category(
        loaded,
        draft,
        question_id="B5_other",
        english_label="Combined Origins",
        arabic_label="اصول مجمعة",
        origin="merged",
        component_cluster_ids=["cluster-a", "cluster-b"],
        member_processing_ids=["p2", "p4"],
    )
    state = draft["questions"][0]
    merged = state["categories"][-1]
    state["categories"] = [merged]
    draft["analyst_name"] = "Sami"
    selections = {
        "existing_assignment:p1": "approved",
        "proposed_category:cluster-a": "merged",
        "proposed_category:cluster-b": "merged",
        "merge:cluster-a:cluster-b": "approved",
        "unresolved:p3": "acknowledged",
    }
    for item in draft["review_item_dispositions"]:
        item["disposition"] = selections[item["review_item_id"]]

    approval, _ = complete_review(
        loaded,
        draft,
        tmp_path / "approvals",
        approval_id=_APPROVAL_ID,
    )

    final = approval["questions"][0]["final_categories"]
    assert len(final) == 1
    assert final[0]["value"] == 101
    assert final[0]["component_cluster_ids"] == ["cluster-a", "cluster-b"]


def test_conflicting_rejected_merge_edge_blocks_completion(tmp_path) -> None:
    loaded = load_review_package(_write_package(tmp_path, two_categories=True))
    draft = create_initial_draft(loaded)
    draft, merged_id = add_analyst_category(
        loaded,
        draft,
        question_id="B5_other",
        english_label="Combined Origins",
        arabic_label="اصول مجمعة",
        origin="merged",
        component_cluster_ids=["cluster-a", "cluster-b"],
        member_processing_ids=["p2", "p4"],
    )
    state = draft["questions"][0]
    merged = state["categories"][-1]
    state["categories"] = [merged]
    draft["analyst_name"] = "Sami"
    for item in draft["review_item_dispositions"]:
        item["disposition"] = {
            "existing_assignment:p1": "approved",
            "proposed_category:cluster-a": "merged",
            "proposed_category:cluster-b": "merged",
            "merge:cluster-a:cluster-b": "rejected",
            "unresolved:p3": "acknowledged",
        }[item["review_item_id"]]

    with pytest.raises(
        AnalystReviewError,
        match="merge:cluster-a:cluster-b.*must be 'approved'",
    ):
        complete_review(
            loaded,
            draft,
            tmp_path / "approvals",
            approval_id=_APPROVAL_ID,
        )
    assert not (tmp_path / "approvals").exists()


def test_split_retains_parent_value_for_lexicographically_first_child(tmp_path) -> None:
    package = _package()
    question = package["questions"][0]
    question["answers"][2]["discovery_evidence"] = {
        "raw_cluster_label": 0,
        "membership_probability": 0.8,
        "status": "accepted_cluster",
        "cluster_id": "cluster-a",
    }
    question["proposed_categories"][0]["member_processing_ids"] = ["p2", "p3"]
    question["unresolved_answers"] = []
    loaded = load_review_package(_write_raw_package(tmp_path, package))
    draft = create_initial_draft(loaded)
    draft, child_id = add_analyst_category(
        loaded,
        draft,
        question_id="B5_other",
        english_label="Second Origin",
        arabic_label="اصل ثان",
        origin="split",
        component_cluster_ids=["cluster-a"],
        member_processing_ids=["p3"],
    )
    state = draft["questions"][0]
    parent = state["categories"][0]
    parent["origin"] = "split"
    child = state["categories"][1]
    assert child["member_processing_ids"] == ["p3"]
    assert state["answer_dispositions"][2]["final_category_id"] == child_id
    draft["analyst_name"] = "Sami"
    for item in draft["review_item_dispositions"]:
        item["disposition"] = {
            "existing_assignment:p1": "approved",
            "proposed_category:cluster-a": "split",
        }[item["review_item_id"]]

    approval, _ = complete_review(
        loaded,
        draft,
        tmp_path / "approvals",
        approval_id=_APPROVAL_ID,
    )

    categories = {
        item["final_category_id"]: item
        for item in approval["questions"][0]["final_categories"]
    }
    assert categories["proposed:cluster-a"]["value"] == 101
    assert categories[child_id]["value"] == 102


def test_generated_value_collision_reports_existing_row_and_proposal(tmp_path) -> None:
    package = _package()
    package["questions"][0]["existing_choices"][1]["value"] = 101
    loaded = load_review_package(_write_raw_package(tmp_path, package))
    draft = _complete_simple_draft(create_initial_draft(loaded))

    with pytest.raises(
        AnalystReviewError,
        match=r"collision 101: B5_other Code row 3; B5_other proposal cluster-a",
    ):
        complete_review(
            loaded,
            draft,
            tmp_path / "approvals",
            approval_id=_APPROVAL_ID,
        )


def test_review_package_rejects_unknown_nested_fields(tmp_path) -> None:
    package = _package()
    package["questions"][0]["answers"][0]["unexpected"] = True

    with pytest.raises(AnalystReviewError, match="invalid schema"):
        load_review_package(_write_raw_package(tmp_path, package))


def test_web_app_renders_question_scope_autosaves_and_completes(tmp_path) -> None:
    package_path = _write_package(tmp_path)
    app = create_review_app(package_path, working_directory=tmp_path)
    app.testing = True
    client = app.test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert b"Analyst review" in page.data
    assert "الجنسية" in page.get_data(as_text=True)

    state = client.get("/api/state").get_json()["draft"]
    completed = _complete_simple_draft(state)
    saved = client.put("/api/draft", json=completed)
    assert saved.status_code == 200
    result = client.post("/api/complete", json=completed)
    assert result.status_code == 200
    assert Path(result.get_json()["approval_path"]).exists()


def test_web_app_rejects_partial_completion_without_approval_file(tmp_path) -> None:
    package_path = _write_package(tmp_path)
    app = create_review_app(package_path, working_directory=tmp_path)
    app.testing = True
    client = app.test_client()
    draft = client.get("/api/state").get_json()["draft"]
    draft["analyst_name"] = "Sami"

    response = client.post("/api/complete", json=draft)

    assert response.status_code == 400
    assert "invalid disposition" in response.get_json()["error"]
    assert not (tmp_path / "review_approvals").exists()
