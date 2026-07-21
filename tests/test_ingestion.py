from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from other_cluster.errors import WorkbookContractError
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


def test_ingestion_extracts_questions_choices_rows_and_deduplicates_text(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")

    dataset = ingest_workbook(input_path)

    assert len(dataset.questions) == 1
    question = dataset.questions[0]
    assert question.question_id == "B5_other"
    assert question.english_text == "Country of origin"
    assert question.arabic_text == "بلد المنشأ"
    assert [(choice.value, choice.label) for choice in question.choices] == [
        (1, "Lebanese"),
        (2, "Syrian"),
    ]

    assert len(dataset.answers) == 3
    assert [answer.data_row for answer in dataset.answers] == [2, 3, 5]
    assert dataset.answers[0].text == "لبناني"
    assert dataset.answers[0].source_column == "B5_other"
    assert dataset.answers[0].coded_column == "B5_other_Coded"
    assert dataset.answers[0].c1_column == "B5_other_C1"
    assert dataset.answers[0].source_cell.coordinate == "D2"
    assert dataset.answers[0].coded_cell.coordinate == "E2"
    assert dataset.answers[0].c1_cell.coordinate == "F2"
    assert dataset.answers[2].coded_cell.coordinate == "E5"

    assert len(dataset.processing_answers) == 2
    duplicate = dataset.processing_answers[0]
    assert duplicate.text == "لبناني"
    assert duplicate.answer_ids == ("B5_other:2", "B5_other:3")
    assert duplicate.occurrence_count == 2
    assert dataset.processing_answers[1].text == "other text"


def test_ingestion_keeps_hidden_rows_and_does_not_mutate_formulas(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    before = load_workbook(input_path, data_only=False)
    before_formula = before["Work"]["D2"].value
    before_c1_formula = before["Work"]["F2"].value
    before.close()

    dataset = ingest_workbook(input_path)

    assert any(answer.data_row == 5 for answer in dataset.answers)
    after = load_workbook(input_path, data_only=False)
    assert after["Work"]["D2"].value == before_formula
    assert after["Work"]["F2"].value == before_c1_formula
    after.close()


def test_formula_backed_work_keys_use_the_aligned_work_row(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path, data_only=False)
    work = workbook["Work"]
    for row in range(2, 6):
        work.cell(row=row, column=1).value = f"=Data!A{row}"
    workbook.save(input_path)
    workbook.close()

    dataset = ingest_workbook(input_path)

    assert [answer.coded_cell.coordinate for answer in dataset.answers] == [
        "E2",
        "E3",
        "E5",
    ]


def test_numeric_answers_are_rejected(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=[123])

    with pytest.raises(WorkbookContractError, match="numeric Data answers are invalid"):
        ingest_workbook(input_path)


def test_formula_answers_are_rejected(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    workbook = load_workbook(input_path, data_only=False)
    workbook["Data"]["D2"] = "=1+1"
    workbook.save(input_path)
    workbook.close()

    with pytest.raises(
        WorkbookContractError, match="formula Data answers are unsupported"
    ):
        ingest_workbook(input_path)


def test_missing_or_reordered_work_triplet_is_rejected(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path)
    work = workbook["Work"]
    work["E1"] = "B5_other_C1"
    work["F1"] = "B5_other_Coded"
    workbook.save(input_path)
    workbook.close()

    with pytest.raises(WorkbookContractError, match="must be contiguous and ordered"):
        ingest_workbook(input_path)


def test_missing_work_key_for_answer_is_rejected(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path)
    workbook["Work"]["A2"] = "different-key"
    workbook.save(input_path)
    workbook.close()

    with pytest.raises(WorkbookContractError, match="has no matching row in Work"):
        ingest_workbook(input_path)


def _delete_required_sheet(path: Path) -> None:
    workbook = load_workbook(path)
    del workbook["Work"]
    workbook.save(path)
    workbook.close()


def _remove_required_header(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["E1"] = None
    workbook.save(path)
    workbook.close()


def _duplicate_header(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["F1"] = "label"
    workbook.save(path)
    workbook.close()


def _non_text_header(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["F1"] = 123
    workbook.save(path)
    workbook.close()


def _blank_required_label(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["D2"] = "   "
    workbook.save(path)
    workbook.close()


def _remove_choice_rows(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Code"].delete_rows(2, 3)
    workbook.save(path)
    workbook.close()


def _duplicate_question_id(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"].append(
        [1, "text", "B5_other", "Country of origin", "بلد المنشأ"]
    )
    workbook.save(path)
    workbook.close()


def _non_integer_choice_value(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Code"]["B3"] = "n/a"
    workbook.save(path)
    workbook.close()


def _merge_answer_cell(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Data"].merge_cells("D2:D3")
    workbook.save(path)
    workbook.close()


def _error_answer_cell(path: Path) -> None:
    workbook = load_workbook(path)
    cell = workbook["Data"]["D2"]
    cell.value = "#N/A"
    cell.data_type = "e"
    workbook.save(path)
    workbook.close()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (_delete_required_sheet, "missing required sheet 'Work'"),
        (_remove_required_header, "missing required header 'label:arabic'"),
        (_duplicate_header, "header 'label' appears more than once"),
        (_non_text_header, "non-text header"),
        (_blank_required_label, "must contain nonblank text"),
        (_remove_choice_rows, "no choice rows"),
        (_duplicate_question_id, "question ID 'B5_other' appears more than once"),
        (_non_integer_choice_value, "must be an integer"),
        (_merge_answer_cell, "merged Data answer cells are unsupported"),
        (_error_answer_cell, "contains an Excel error value"),
    ],
    ids=[
        "missing-sheet",
        "missing-header",
        "duplicate-header",
        "non-text-header",
        "blank-required-label",
        "missing-choice-rows",
        "duplicate-question-id",
        "non-integer-choice-value",
        "merged-answer-cell",
        "error-answer-cell",
    ],
)
def test_invalid_workbook_structure_is_rejected_without_mutation(
    tmp_path: Path,
    mutate,
    match: str,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    mutate(input_path)
    before = input_path.read_bytes()

    with pytest.raises(WorkbookContractError, match=match):
        ingest_workbook(input_path)

    assert input_path.read_bytes() == before
