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


def test_code_list_name_defines_the_questions_to_extract(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path)
    workbook["Survey"].append(
        ["text", "not_coded", "Not coded question", "سؤال غير مشفر"]
    )
    workbook.save(input_path)
    workbook.close()

    dataset = ingest_workbook(input_path)

    assert [question.question_id for question in dataset.questions] == ["B5_other"]


def test_code_other_suffix_is_removed_for_survey_metadata_lookup(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path)
    workbook["Survey"]["B2"] = "B5"
    workbook.save(input_path)
    workbook.close()

    dataset = ingest_workbook(input_path)

    question = dataset.questions[0]
    assert question.question_id == "B5_other"
    assert question.english_text == "Country of origin"
    assert question.arabic_text == "بلد المنشأ"
    assert question.source_column == "B5_other"
    assert question.coded_column == "B5_other_Coded"


def test_compound_code_list_name_expands_shared_choices_per_question(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path)

    survey = workbook["Survey"]
    survey["B2"] = "interview_location"
    survey["C2"] = "Interview location"
    survey["D2"] = "مكان المقابلة"
    survey.append(["text", "farm_owner", "Farm owner", "مالك المزرعة"])

    code = workbook["Code"]
    for row in range(2, 5):
        code.cell(row=row, column=1).value = "interview_location_other farm_owner_other"

    data = workbook["Data"]
    data["D1"] = "interview_location_other"
    data["E1"] = "farm_owner_other"
    for row in range(2, 6):
        data.cell(row=row, column=5).value = data.cell(row=row, column=4).value

    work = workbook["Work"]
    work["D1"] = "interview_location_other"
    work["E1"] = "interview_location_other_Coded"
    work["F1"] = "interview_location_other_C1"
    work["G1"] = "farm_owner_other"
    work["H1"] = "farm_owner_other_Coded"
    work["I1"] = "farm_owner_other_C1"
    for row in range(2, 6):
        work.cell(row=row, column=7).value = f"=Data!E{row}"
        work.cell(row=row, column=8).value = None
        work.cell(
            row=row, column=9
        ).value = f'=IFERROR(VLOOKUP(H{row},Code!$C:$D,2,FALSE),"")'

    workbook.save(input_path)
    workbook.close()

    dataset = ingest_workbook(input_path)

    assert [question.question_id for question in dataset.questions] == [
        "interview_location_other",
        "farm_owner_other",
    ]
    assert [question.english_text for question in dataset.questions] == [
        "Interview location",
        "Farm owner",
    ]
    assert all(
        [(choice.value, choice.label) for choice in question.choices]
        == [(1, "Lebanese"), (2, "Syrian")]
        for question in dataset.questions
    )
    assert {answer.question_id for answer in dataset.answers} == {
        "interview_location_other",
        "farm_owner_other",
    }


def test_ingestion_resolves_headers_by_name_when_columns_are_reordered(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path, data_only=False)

    # Header order is not part of the contract. The Work coding triplet is
    # deliberately kept contiguous and ordered because that rule is separate.
    _reorder_columns(
        workbook["Survey"],
        ["label:arabic", "label:english", "name", "type"],
    )
    _reorder_columns(
        workbook["Code"],
        ["label:arabic", "label:english", "list_name", "value"],
    )
    _reorder_columns(
        workbook["Data"],
        ["B5_other", "enumerator_name", "KEY", "enumerator_id"],
    )
    _reorder_columns(
        workbook["Work"],
        [
            "enumerator_name",
            "KEY",
            "enumerator_id",
            "B5_other",
            "B5_other_Coded",
            "B5_other_C1",
        ],
    )
    workbook.save(input_path)
    workbook.close()

    dataset = ingest_workbook(input_path)

    assert dataset.questions[0].english_text == "Country of origin"
    assert [
        (choice.value, choice.label) for choice in dataset.questions[0].choices
    ] == [
        (1, "Lebanese"),
        (2, "Syrian"),
    ]
    assert dataset.answers[0].source_cell.coordinate == "A2"
    assert dataset.answers[0].coded_cell.coordinate == "E2"


def test_ingestion_accepts_case_variants_of_fixed_schema_headers(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path)
    workbook["Survey"]["D1"] = "Label:Arabic"
    workbook["Code"]["C1"] = "Label:English"
    workbook["Code"]["D1"] = "Label:Arabic"
    workbook.save(input_path)
    workbook.close()

    dataset = ingest_workbook(input_path)

    assert dataset.questions[0].arabic_text == "بلد المنشأ"
    assert dataset.questions[0].choices[0].label == "Lebanese"
    assert dataset.questions[0].choices[0].label_arabic == "لبناني"


@pytest.mark.parametrize(
    ("english_value", "arabic_value"),
    [(None, "بلد المنشأ"), ("Country of origin", None)],
    ids=["english-falls-back-to-arabic", "arabic-falls-back-to-english"],
)
def test_blank_bilingual_labels_fall_back_to_the_other_label(
    tmp_path: Path,
    english_value: str | None,
    arabic_value: str | None,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    workbook = load_workbook(input_path)
    workbook["Survey"]["C2"] = english_value
    workbook["Survey"]["D2"] = arabic_value
    workbook["Code"]["C3"] = english_value
    workbook["Code"]["D3"] = arabic_value
    workbook.save(input_path)
    workbook.close()

    dataset = ingest_workbook(input_path)

    question = dataset.questions[0]
    assert question.english_text == (english_value or arabic_value)
    assert question.arabic_text == (arabic_value or english_value)
    choice = question.choices[0]
    assert choice.label == (english_value or arabic_value)
    assert choice.label_arabic == (arabic_value or english_value)
    assert dataset.answers[0].c1_cell.coordinate == "F2"


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

    with pytest.raises(
        WorkbookContractError, match=r"Data!D2.*numeric Data answers are invalid"
    ):
        ingest_workbook(input_path)


def test_formula_answers_are_rejected(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    workbook = load_workbook(input_path, data_only=False)
    workbook["Data"]["D2"] = "=1+1"
    workbook.save(input_path)
    workbook.close()

    with pytest.raises(
        WorkbookContractError,
        match=r"Data!D2.*formula Data answers are unsupported",
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

    with pytest.raises(
        WorkbookContractError, match=r"Data row 2 with KEY 'respondent-1'"
    ):
        ingest_workbook(input_path)


def _delete_required_sheet(path: Path) -> None:
    workbook = load_workbook(path)
    del workbook["Work"]
    workbook.save(path)
    workbook.close()


def _remove_required_header(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["D1"] = None
    workbook.save(path)
    workbook.close()


def _duplicate_header(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["D1"] = "label:english"
    workbook.save(path)
    workbook.close()


def _non_text_header(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["D1"] = 123
    workbook.save(path)
    workbook.close()


def _blank_bilingual_survey_labels(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"]["C2"] = "   "
    workbook["Survey"]["D2"] = None
    workbook.save(path)
    workbook.close()


def _blank_bilingual_code_labels(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Code"]["C3"] = "   "
    workbook["Code"]["D3"] = None
    workbook.save(path)
    workbook.close()


def _remove_survey_question(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"].delete_rows(2, 1)
    workbook.save(path)
    workbook.close()


def _duplicate_question_id(path: Path) -> None:
    workbook = load_workbook(path)
    workbook["Survey"].append(["text", "B5", "Country of origin", "بلد المنشأ"])
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
        (
            _remove_required_header,
            r"missing required header 'label:arabic' \(row 1\)",
        ),
        (_duplicate_header, "header 'label:english' appears more than once"),
        (_non_text_header, "non-text header"),
        (
            _blank_bilingual_survey_labels,
            r"Survey row 2 has empty 'label:english' and 'label:arabic'",
        ),
        (
            _blank_bilingual_code_labels,
            r"Code row 3 has empty 'label:english' and 'label:arabic'",
        ),
        (
            _remove_survey_question,
            r"Code\.list_name 'B5_other' on row\(s\) 2, 3, 4",
        ),
        (
            _duplicate_question_id,
            r"question ID 'B5' appears more than once \(rows 2 and 3\)",
        ),
        (_non_integer_choice_value, r"Code!B3.*must be an integer"),
        (_merge_answer_cell, "merged Data answer cells are unsupported"),
        (_error_answer_cell, "contains an Excel error value"),
    ],
    ids=[
        "missing-sheet",
        "missing-header",
        "duplicate-header",
        "non-text-header",
        "blank-bilingual-survey-labels",
        "blank-bilingual-code-labels",
        "missing-survey-row-for-code-list",
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


def _reorder_columns(worksheet, ordered_headers: list[str]) -> None:
    """Rebuild fixture columns in a requested order without changing row data."""

    original_width = worksheet.max_column
    if len(ordered_headers) != original_width:
        raise AssertionError("test helper must account for every fixture column")

    header_columns = {
        worksheet.cell(row=1, column=column).value: column
        for column in range(1, original_width + 1)
    }
    rows = [
        [
            worksheet.cell(row=row, column=header_columns[header]).value
            for header in ordered_headers
        ]
        for row in range(1, worksheet.max_row + 1)
    ]

    for row in range(1, worksheet.max_row + 1):
        for column in range(1, original_width + 1):
            worksheet.cell(row=row, column=column).value = None

    for row, values in enumerate(rows, start=1):
        for column, value in enumerate(values, start=1):
            worksheet.cell(row=row, column=column).value = value
