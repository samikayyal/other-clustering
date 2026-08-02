from __future__ import annotations

import json
import uuid
from pathlib import Path

from openpyxl import Workbook

from other_cluster.cli.main import main


def _answer(
    processing_id: str,
    text: str,
    *,
    status: str,
    cluster_id: str | None = None,
) -> dict[str, object]:
    return {
        "processing_id": processing_id,
        "text": text,
        "occurrence_count": 1,
        "row_mappings": [
            {
                "answer_id": f"answer-{processing_id}",
                "respondent_key": f"respondent-{processing_id}",
                "sheet": "Data",
                "row": 2,
                "column": 4,
                "coordinate": "D2",
            }
        ],
        "discovery_evidence": {
            "raw_cluster_label": 0 if cluster_id else -1,
            "membership_probability": 0.9 if cluster_id else 0.0,
            "status": status,
            "cluster_id": cluster_id,
        },
    }


def _cluster(
    cluster_id: str,
    member_ids: list[str],
    *,
    decision: str,
    rejection: str | None = None,
) -> dict[str, object]:
    return {
        "cluster_id": cluster_id,
        "raw_cluster_label": 0,
        "member_processing_ids": member_ids,
        "gemini_proposal": {
            "decision": decision,
            "selected_choice_value": None,
            "english_label": "New category" if decision == "new_category" else None,
            "arabic_label": "فئة جديدة" if decision == "new_category" else None,
            "rejection_reason": rejection,
            "provider_error": None,
        },
        "analyst_decision": None,
    }


def _question_with_clusters() -> dict[str, object]:
    answers = [
        _answer(f"a-{letter}", letter, status="accepted_cluster", cluster_id="q1:c1")
        for letter in ("a", "b", "c")
    ]
    answers.extend(
        _answer(f"b-{letter}", letter, status="accepted_cluster", cluster_id="q1:c2")
        for letter in ("d", "e", "f")
    )
    answers.append(_answer("unresolved", "g", status="noise"))
    return {
        "question_id": "q1",
        "question_text": {"english": "Question one", "arabic": "السؤال الأول"},
        "source_column": "q1",
        "existing_choices": [],
        "answers": answers,
        "clusters": [
            _cluster("q1:c1", ["a-a", "a-b", "a-c"], decision="new_category"),
            _cluster(
                "q1:c2",
                ["b-d", "b-e", "b-f"],
                decision="reject_cluster",
                rejection="mixed_meanings",
            ),
        ],
        "unresolved_answers": [
            {
                "processing_id": "unresolved",
                "reason": "noise",
                "analyst_decision": None,
            }
        ],
    }


def _review_document() -> dict[str, object]:
    return {
        "schema_version": 3,
        "analysis_run_id": str(uuid.uuid4()),
        "status": "in_review",
        "created_at_utc": "2026-07-30T00:00:00Z",
        "updated_at_utc": "2026-07-30T00:00:00Z",
        "completed_at_utc": None,
        "analyst_name": None,
        "source_workbook": {
            "input_kind": "local_xlsx",
            "source_locator": "input.xlsx",
            "display_name": "input.xlsx",
            "size_bytes": 1,
            "sha256": "0" * 64,
        },
        "questions": [
            _question_with_clusters(),
            {
                "question_id": "q2",
                "question_text": {
                    "english": "Question two",
                    "arabic": "السؤال الثاني",
                },
                "source_column": "q2",
                "existing_choices": [],
                "answers": [_answer("q2-a", "only unresolved", status="noise")],
                "clusters": [],
                "unresolved_answers": [
                    {
                        "processing_id": "q2-a",
                        "reason": "noise",
                        "analyst_decision": None,
                    }
                ],
            },
        ],
        "warnings": [],
    }


def test_evaluate_prints_per_question_metrics_and_gemini_results(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(_review_document(), ensure_ascii=False), encoding="utf-8"
    )

    assert main(["evaluate", "--review-file", str(path)]) == 0

    output = capsys.readouterr().out
    assert "Question: q1 - Question one" in output
    assert "Number of clusters: 2" in output
    assert "Cluster sizes: 3, 3" in output
    assert "85.7% clustered (6/7) versus 14.3% unresolved (1/7)" in output
    assert "Largest-cluster share: 42.9%" in output
    assert "Representative member texts: a; b; c" in output
    assert "Gemini: ACCEPTED (new_category)" in output
    assert "Gemini: REJECTED (reject_cluster: mixed_meanings)" in output
    assert "Question: q2 - Question two" in output
    assert "Number of clusters: 0" in output
    assert (
        "Clustered versus unresolved: 0.0% clustered (0/1) versus "
        "100.0% unresolved (1/1)"
    ) in output
    assert "Clusters: none" in output


def test_evaluate_reports_invalid_review_file_as_cli_error(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{}", encoding="utf-8")

    assert main(["evaluate", "--review-file", str(path)]) == 1
    assert "error:" in capsys.readouterr().err


def test_evaluate_accepts_work_tab_ground_truth(tmp_path: Path, capsys) -> None:
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(_review_document(), ensure_ascii=False), encoding="utf-8"
    )
    ground_truth_path = tmp_path / "ground-truth.xlsx"
    workbook = Workbook()
    work = workbook.active
    work.title = "Work"
    work.append(["KEY", "q1", "q1_Coded", "q1_C1"])
    for processing_id, text, code in (
        ("a-a", "a", 101),
        ("a-b", "b", 101),
        ("a-c", "c", 101),
        ("b-d", "d", 102),
        ("b-e", "e", 102),
        ("b-f", "f", 102),
        ("unresolved", "g", 103),
    ):
        work.append([f"respondent-{processing_id}", text, f"Label {code}", code])
    workbook.save(ground_truth_path)
    workbook.close()

    assert (
        main(
            [
                "evaluate",
                "--review-file",
                str(review_path),
                "--ground-truth",
                str(ground_truth_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Ground-truth clustering benchmark" in output
    assert "Alignment: 7/8 canonical answers" in output
    assert "Question: q1 (3 human clusters)" in output
