"""Read and validate the supported SurveyCTO coding workbook shape."""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

from ..domain import (
    AnswerRecord,
    CellLocation,
    ChoiceRecord,
    ProcessingAnswerRecord,
    QuestionRecord,
    WorkbookDataset,
)
from ..errors import WorkbookContractError

SURVEY_SHEET = "Survey"
CODE_SHEET = "Code"
DATA_SHEET = "Data"
WORK_SHEET = "Work"
OTHER_VALUE = -96

_SURVEY_HEADERS = ("type", "name", "label:english", "label:arabic")
_CODE_HEADERS = ("list_name", "value", "label:english", "label:arabic")
_CASE_INSENSITIVE_HEADERS = frozenset(
    {
        "type",
        "name",
        "label:english",
        "label:arabic",
        "list_name",
        "value",
        "KEY",
    }
)
_OTHER_SUFFIX = "_other"
_EXPLANATION_SUFFIX = "_exp"


def ingest_workbook(path: str | Path) -> WorkbookDataset:
    """Validate and extract a workbook without saving or mutating it."""

    source_path = _normalize_source_path(path)
    try:
        workbook = load_workbook(source_path, data_only=False, read_only=False)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise WorkbookContractError(
            f"could not open input workbook '{source_path}': {exc}"
        ) from exc

    try:
        return _extract_dataset(workbook, source_path)
    finally:
        workbook.close()


def _normalize_source_path(path: str | Path) -> Path:
    source_path = Path(path).expanduser().resolve()
    if source_path.suffix.lower() != ".xlsx":
        raise WorkbookContractError(
            f"input path must be an .xlsx file: '{source_path}'"
        )
    if not source_path.exists():
        raise WorkbookContractError(f"input workbook does not exist: '{source_path}'")
    if not source_path.is_file():
        raise WorkbookContractError(f"input path is not a file: '{source_path}'")
    return source_path


def _extract_dataset(workbook: Any, source_path: Path) -> WorkbookDataset:
    issues: list[str] = []
    survey, code, data, work = _require_sheets(workbook)

    survey_headers = _read_headers(
        survey, required=_SURVEY_HEADERS, sheet_name=SURVEY_SHEET, issues=issues
    )
    code_headers = _read_headers(
        code,
        required=_CODE_HEADERS,
        sheet_name=CODE_SHEET,
        issues=issues,
    )
    _raise_if_issues(issues)

    code_choices = _extract_code_choices(code, code_headers, issues)
    _raise_if_issues(issues)

    survey_rows = _extract_questions(
        survey,
        survey_headers,
        list_names=code_choices,
        issues=issues,
    )
    _raise_if_issues(issues)

    questions = _build_questions(survey_rows, code_choices, issues)
    _raise_if_issues(issues)

    question_ids = tuple(question.question_id for question in questions)
    data_headers = _read_headers(
        data,
        required=("KEY", *question_ids),
        sheet_name=DATA_SHEET,
        issues=issues,
    )
    work_headers = _read_headers(
        work,
        required=(
            "KEY",
            *(column for question in questions for column in _triplet(question)),
        ),
        sheet_name=WORK_SHEET,
        issues=issues,
    )
    _validate_work_triplets(work_headers, questions, issues)
    _raise_if_issues(issues)

    work_key_rows = _index_work_keys(work, work_headers["KEY"], issues)
    answers = _extract_answers(
        data=data,
        work=work,
        data_headers=data_headers,
        work_headers=work_headers,
        questions=questions,
        work_key_rows=work_key_rows,
        work_key_column=work_headers["KEY"],
        issues=issues,
    )
    _raise_if_issues(issues)

    processing_answers = _deduplicate_answers(answers)
    return WorkbookDataset(
        source_path=source_path,
        questions=tuple(questions),
        answers=tuple(answers),
        processing_answers=processing_answers,
    )


def _require_sheets(workbook: Any) -> tuple[Any, Any, Any, Any]:
    required_sheets = (SURVEY_SHEET, CODE_SHEET, DATA_SHEET, WORK_SHEET)
    missing_sheets = [
        name for name in required_sheets if name not in workbook.sheetnames
    ]
    if missing_sheets:
        raise WorkbookContractError(
            [f"missing required sheet '{name}'" for name in missing_sheets]
        )
    return (
        workbook[SURVEY_SHEET],
        workbook[CODE_SHEET],
        workbook[DATA_SHEET],
        workbook[WORK_SHEET],
    )


def _raise_if_issues(issues: list[str]) -> None:
    """Stop ingestion at a phase boundary if any contract issue accumulated."""

    if issues:
        raise WorkbookContractError(issues)


def _read_headers(
    worksheet: Any,
    *,
    required: tuple[str, ...],
    sheet_name: str,
    issues: list[str],
) -> dict[str, int]:
    headers: dict[str, int] = {}
    casefolded_required = {
        header.casefold(): header
        for header in required
        if header in _CASE_INSENSITIVE_HEADERS
    }
    for column in range(1, worksheet.max_column + 1):
        value = worksheet.cell(row=1, column=column).value
        if value is None or (isinstance(value, str) and value == ""):
            continue
        if not isinstance(value, str):
            continue
        # SurveyCTO exports can vary the casing of fixed schema headers (for
        # example, ``Label:Arabic``). Resolve those aliases to the canonical
        # contract name, but leave dynamic question IDs case-sensitive.
        header = (
            value
            if value in required
            else casefolded_required.get(value.casefold(), value)
        )
        if header not in required:
            continue
        if header in headers:
            issues.append(
                f"{sheet_name} header '{value}' appears more than once "
                f"({_location(sheet_name, 1, headers[header])} and "
                f"{_location(sheet_name, 1, column)})"
            )
            continue
        headers[header] = column

    missing = [header for header in required if header not in headers]
    issues.extend(
        f"{sheet_name} is missing required header '{header}' (row 1)"
        for header in missing
    )
    return headers


def _extract_questions(
    worksheet: Any,
    headers: dict[str, int],
    *,
    list_names: dict[str, list[ChoiceRecord]],
    issues: list[str],
) -> dict[str, tuple[str, str, int]]:
    """Extract Survey metadata for the question IDs present in Code.list_name.

    ``Code.list_name`` retains the workbook's answer-column identifier. Survey
    metadata lookup applies only the documented suffix and numeric-separator
    normalization rules.
    """

    questions: dict[str, tuple[str, str, int]] = {}
    match_ranks: dict[str, int] = {}
    code_ids_by_survey_id: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for code_question_id in list_names:
        for rank, survey_lookup_id in enumerate(_survey_lookup_ids(code_question_id)):
            code_ids_by_survey_id[survey_lookup_id].append((code_question_id, rank))

    seen: dict[str, int] = {}
    for row in range(2, worksheet.max_row + 1):
        raw_question_id = worksheet.cell(row=row, column=headers["name"]).value
        if _blank(raw_question_id):
            continue
        question_id = _required_text(
            raw_question_id,
            field="Survey.name",
            location=_location(SURVEY_SHEET, row, headers["name"]),
            issues=issues,
        )
        if question_id is None or question_id not in code_ids_by_survey_id:
            continue
        labels = _resolve_bilingual_labels(
            worksheet.cell(row=row, column=headers["label:english"]).value,
            worksheet.cell(row=row, column=headers["label:arabic"]).value,
            english_location=_location(SURVEY_SHEET, row, headers["label:english"]),
            arabic_location=_location(SURVEY_SHEET, row, headers["label:arabic"]),
            field_prefix="Survey",
            row=row,
            issues=issues,
        )
        if question_id is None or labels is None:
            continue
        english_text, arabic_text = labels
        if question_id in seen:
            issues.append(
                f"Survey question ID '{question_id}' appears more than once "
                f"(rows {seen[question_id]} and {row})"
            )
            continue
        seen[question_id] = row
        for code_question_id, rank in code_ids_by_survey_id[question_id]:
            if rank >= match_ranks.get(code_question_id, math.inf):
                continue
            questions[code_question_id] = (english_text, arabic_text, row)
            match_ranks[code_question_id] = rank
    return questions


def _survey_lookup_ids(code_question_id: str) -> tuple[str, ...]:
    """Return the deterministic Survey metadata candidates for a Code list name."""

    if code_question_id.endswith(_OTHER_SUFFIX):
        base_ids = (code_question_id.removesuffix(_OTHER_SUFFIX),)
    elif code_question_id.endswith(_EXPLANATION_SUFFIX):
        base_ids = (
            code_question_id,
            code_question_id.removesuffix(_EXPLANATION_SUFFIX),
        )
    else:
        base_ids = (code_question_id,)

    candidates: list[str] = []
    for base_id in base_ids:
        for candidate in (
            base_id,
            re.sub(r"(?<=[A-Za-z])(?=\d+$)", "_", base_id),
        ):
            if candidate not in candidates:
                candidates.append(candidate)
    return tuple(candidates)


def _build_questions(
    survey_rows: dict[str, tuple[str, str, int]],
    code_choices: dict[str, list[ChoiceRecord]],
    issues: list[str],
) -> list[QuestionRecord]:
    questions: list[QuestionRecord] = []
    for question_id, rows in code_choices.items():
        survey_row_data = survey_rows.get(question_id)
        if survey_row_data is None:
            code_rows = ", ".join(str(choice.code_row) for choice in rows)
            issues.append(
                f"Code.list_name '{question_id}' on row(s) {code_rows} has no "
                "matching Survey row"
            )
            continue
        english_text, arabic_text, survey_row = survey_row_data
        choices = tuple(choice for choice in rows if choice.value != OTHER_VALUE)
        questions.append(
            QuestionRecord(
                question_id=question_id,
                english_text=english_text,
                arabic_text=arabic_text,
                source_column=question_id,
                coded_column=f"{question_id}_Coded",
                c1_column=f"{question_id}_C1",
                survey_row=survey_row,
                choices=choices,
            )
        )
    return questions


def _extract_code_choices(
    worksheet: Any, headers: dict[str, int], issues: list[str]
) -> dict[str, list[ChoiceRecord]]:
    choices: dict[str, list[ChoiceRecord]] = defaultdict(list)
    for row in range(2, worksheet.max_row + 1):
        values = [
            worksheet.cell(row=row, column=headers[header]).value
            for header in _CODE_HEADERS
        ]
        if all(_blank(value) for value in values):
            continue
        question_id = _required_text(
            values[0],
            field="Code.list_name",
            location=_location(CODE_SHEET, row, headers["list_name"]),
            issues=issues,
        )
        value = _choice_value(
            values[1],
            location=_location(CODE_SHEET, row, headers["value"]),
            issues=issues,
        )
        labels = _resolve_bilingual_labels(
            values[2],
            values[3],
            english_location=_location(CODE_SHEET, row, headers["label:english"]),
            arabic_location=_location(CODE_SHEET, row, headers["label:arabic"]),
            field_prefix="Code",
            row=row,
            issues=issues,
        )
        if question_id is None or value is None or labels is None:
            continue
        label, label_arabic = labels
        for question_id in _split_code_question_ids(question_id):
            choices[question_id].append(
                ChoiceRecord(
                    question_id=question_id,
                    value=value,
                    label=label,
                    label_arabic=label_arabic,
                    code_row=row,
                )
            )
    return choices


def _split_code_question_ids(list_name: str) -> tuple[str, ...]:
    """Return the question IDs encoded in one Code.list_name cell.

    Some source workbooks reuse one choice block for multiple ``Other``
    questions and store those IDs as whitespace-separated values, for example
    ``"interview_location_other farm_owner_other"``. The downstream model is
    question-scoped, so each ID becomes its own internal choice group while
    retaining the same source Code row.
    """

    return tuple(list_name.split())


def _validate_work_triplets(
    headers: dict[str, int], questions: list[QuestionRecord], issues: list[str]
) -> None:
    for question in questions:
        expected = _triplet(question)
        missing = [header for header in expected if header not in headers]
        if missing:
            issues.append(
                f"Work row 1 is missing triplet member(s) for "
                f"'{question.question_id}': " + ", ".join(missing)
            )
            continue
        positions = [headers[header] for header in expected]
        if positions != list(range(positions[0], positions[0] + 3)):
            rendered = ", ".join(
                f"{header}={get_column_letter(headers[header])}1" for header in expected
            )
            issues.append(
                f"Work triplet for '{question.question_id}' must be contiguous and ordered "
                f"as {expected[0]}, {expected[1]}, {expected[2]} ({rendered})"
            )


def _index_work_keys(
    worksheet: Any, key_column: int, issues: list[str]
) -> dict[str, int]:
    key_rows: dict[str, int] = {}
    for row in range(2, worksheet.max_row + 1):
        value = worksheet.cell(row=row, column=key_column).value
        key = _respondent_key(
            value,
            location=_location(WORK_SHEET, row, key_column),
            issues=issues,
            required=False,
        )
        if key is None:
            continue
        key_cell = worksheet.cell(row=row, column=key_column)
        if key_cell.data_type == "f":
            continue
        if key in key_rows:
            issues.append(
                f"Work KEY '{key}' appears more than once "
                f"(rows {key_rows[key]} and {row})"
            )
            continue
        key_rows[key] = row
    return key_rows


def _extract_answers(
    *,
    data: Any,
    work: Any,
    data_headers: dict[str, int],
    work_headers: dict[str, int],
    questions: list[QuestionRecord],
    work_key_rows: dict[str, int],
    work_key_column: int,
    issues: list[str],
) -> list[AnswerRecord]:
    answers: list[AnswerRecord] = []
    seen_data_keys: dict[str, int] = {}
    merged_ranges = tuple(data.merged_cells.ranges)
    key_column = data_headers["KEY"]

    for row in range(2, data.max_row + 1):
        row_answers = _scan_row_answers(
            data=data,
            data_headers=data_headers,
            questions=questions,
            row=row,
            merged_ranges=merged_ranges,
            issues=issues,
        )
        if not row_answers:
            continue

        key = _claim_data_key(
            data=data,
            key_column=key_column,
            row=row,
            seen_data_keys=seen_data_keys,
            issues=issues,
        )
        if key is None:
            continue

        work_row = _resolve_work_row(
            work=work,
            key=key,
            data_row=row,
            work_key_rows=work_key_rows,
            work_key_column=work_key_column,
        )
        if work_row is None:
            issues.append(
                f"Data row {row} with KEY '{key}' has no matching row in Work"
            )
            continue

        for question, source_column, text in row_answers:
            answers.append(
                _build_answer_record(
                    data=data,
                    work=work,
                    work_headers=work_headers,
                    question=question,
                    row=row,
                    work_row=work_row,
                    source_column=source_column,
                    text=text,
                    respondent_key=key,
                )
            )
    return answers


def _scan_row_answers(
    *,
    data: Any,
    data_headers: dict[str, int],
    questions: list[QuestionRecord],
    row: int,
    merged_ranges: tuple[Any, ...],
    issues: list[str],
) -> list[tuple[QuestionRecord, int, str]]:
    row_answers: list[tuple[QuestionRecord, int, str]] = []
    for question in questions:
        source_column = data_headers[question.source_column]
        cell = data.cell(row=row, column=source_column)
        text = _read_answer_text(
            cell,
            location=_location(DATA_SHEET, row, source_column),
            merged_ranges=merged_ranges,
            issues=issues,
        )
        if text is not None:
            row_answers.append((question, source_column, text))
    return row_answers


def _claim_data_key(
    *,
    data: Any,
    key_column: int,
    row: int,
    seen_data_keys: dict[str, int],
    issues: list[str],
) -> str | None:
    key = _respondent_key(
        data.cell(row=row, column=key_column).value,
        location=_location(DATA_SHEET, row, key_column),
        issues=issues,
        required=True,
    )
    if key is None:
        return None
    if key in seen_data_keys:
        issues.append(
            f"Data KEY '{key}' appears on more than one answer row "
            f"(rows {seen_data_keys[key]} and {row})"
        )
        return None
    seen_data_keys[key] = row
    return key


def _resolve_work_row(
    *,
    work: Any,
    key: str,
    data_row: int,
    work_key_rows: dict[str, int],
    work_key_column: int,
) -> int | None:
    """Return the Work row that owns a respondent KEY.

    Literal Work keys are matched by value. When the Work KEY cell is a
    formula (for example ``=Data!A2``) its computed value is unavailable while
    reading formulas, so the row is matched positionally against the aligned
    Data row, which the Work-mirrors-Data column contract guarantees.
    """

    work_row = work_key_rows.get(key)
    if work_row is not None:
        return work_row
    if data_row <= work.max_row:
        work_key_cell = work.cell(row=data_row, column=work_key_column)
        if work_key_cell.data_type == "f":
            return data_row
    return None


def _build_answer_record(
    *,
    data: Any,
    work: Any,
    work_headers: dict[str, int],
    question: QuestionRecord,
    row: int,
    work_row: int,
    source_column: int,
    text: str,
    respondent_key: str,
) -> AnswerRecord:
    return AnswerRecord(
        answer_id=f"{question.question_id}:{row}",
        question_id=question.question_id,
        source_column=question.source_column,
        coded_column=question.coded_column,
        c1_column=question.c1_column,
        text=text,
        respondent_key=respondent_key,
        data_row=row,
        source_cell=_cell_location(data, DATA_SHEET, row, source_column),
        coded_cell=_cell_location(
            work, WORK_SHEET, work_row, work_headers[question.coded_column]
        ),
        c1_cell=_cell_location(
            work, WORK_SHEET, work_row, work_headers[question.c1_column]
        ),
    )


def _deduplicate_answers(
    answers: list[AnswerRecord],
) -> tuple[ProcessingAnswerRecord, ...]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for answer in answers:
        grouped.setdefault((answer.question_id, answer.text), []).append(
            answer.answer_id
        )

    processing: list[ProcessingAnswerRecord] = []
    for (question_id, text), answer_ids in grouped.items():
        digest = hashlib.sha256(f"{question_id}\0{text}".encode("utf-8")).hexdigest()
        processing.append(
            ProcessingAnswerRecord(
                processing_id=f"{question_id}:{digest}",
                question_id=question_id,
                text=text,
                answer_ids=tuple(answer_ids),
            )
        )
    return tuple(processing)


def _triplet(question: QuestionRecord) -> tuple[str, str, str]:
    return (question.question_id, question.coded_column, question.c1_column)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _resolve_bilingual_labels(
    english_value: object,
    arabic_value: object,
    *,
    english_location: str,
    arabic_location: str,
    field_prefix: str,
    row: int,
    issues: list[str],
) -> tuple[str, str] | None:
    """Validate a bilingual pair and fill a blank side from the other side."""

    english, english_valid = _optional_text(
        english_value,
        field=f"{field_prefix}.label:english",
        location=english_location,
        issues=issues,
    )
    arabic, arabic_valid = _optional_text(
        arabic_value,
        field=f"{field_prefix}.label:arabic",
        location=arabic_location,
        issues=issues,
    )
    if not english_valid or not arabic_valid:
        return None
    if english is None and arabic is None:
        issues.append(
            f"{field_prefix} row {row} has empty 'label:english' and "
            "'label:arabic'; at least one label must contain text"
        )
        return None
    if english is None:
        english = arabic
    if arabic is None:
        arabic = english
    assert english is not None and arabic is not None
    return english, arabic


def _optional_text(
    value: object,
    *,
    field: str,
    location: str,
    issues: list[str],
) -> tuple[str | None, bool]:
    if _blank(value):
        return None, True
    if not isinstance(value, str):
        issues.append(f"{location} ({field}) must contain nonblank text")
        return None, False
    return value, True


def _required_text(
    value: object,
    *,
    field: str,
    location: str,
    issues: list[str],
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{location} ({field}) must contain nonblank text")
        return None
    return value


def _choice_value(value: object, *, location: str, issues: list[str]) -> int | None:
    if isinstance(value, bool):
        issues.append(f"{location} (Code.value) must be an integer")
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    issues.append(f"{location} (Code.value) must be an integer")
    return None


def _respondent_key(
    value: object,
    *,
    location: str,
    issues: list[str],
    required: bool,
) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            issues.append(f"{location} (KEY) must contain a respondent identifier")
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        issues.append(f"{location} (KEY) must contain a respondent identifier")
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return str(value)
    issues.append(f"{location} (KEY) must contain a supported identifier")
    return None


def _read_answer_text(
    cell: Cell | MergedCell,
    *,
    location: str,
    merged_ranges: tuple[Any, ...],
    issues: list[str],
) -> str | None:
    if any(cell.coordinate in merged_range for merged_range in merged_ranges):
        issues.append(f"{location} is merged; merged Data answer cells are unsupported")
        return None
    if cell.data_type == "f":
        issues.append(
            f"{location} is formula-based; formula Data answers are unsupported"
        )
        return None
    if cell.data_type == "e":
        issues.append(f"{location} contains an Excel error value")
        return None

    value = cell.value
    if value is None:
        return None
    if isinstance(value, str):
        return None if not value.strip() else value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        issues.append(
            f"{location} contains a numeric answer; numeric Data answers are invalid"
        )
        return None
    issues.append(f"{location} must contain text or a blank answer")
    return None


def _location(sheet: str, row: int, column: int) -> str:
    return f"{sheet}!{get_column_letter(column)}{row} (row {row})"


def _cell_location(worksheet: Any, sheet: str, row: int, column: int) -> CellLocation:
    return CellLocation(
        sheet=sheet,
        row=row,
        column=column,
        coordinate=worksheet.cell(row=row, column=column).coordinate,
    )
