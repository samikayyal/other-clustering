"""Domain records for the workbook ingestion boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CellLocation:
    """A stable reference to one cell in the source workbook."""

    sheet: str
    row: int
    column: int
    coordinate: str


@dataclass(frozen=True, slots=True)
class ChoiceRecord:
    """An existing semantic choice from the ``Code`` sheet."""

    question_id: str
    value: int
    label: str
    label_arabic: str
    code_row: int


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    """A codable question and its allowed existing choices."""

    question_id: str
    english_text: str
    arabic_text: str
    source_column: str
    coded_column: str
    c1_column: str
    survey_row: int
    choices: tuple[ChoiceRecord, ...]


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    """One respondent-level answer and its exact eventual target cell."""

    answer_id: str
    question_id: str
    source_column: str
    coded_column: str
    c1_column: str
    text: str
    respondent_key: str
    data_row: int
    source_cell: CellLocation
    coded_cell: CellLocation
    c1_cell: CellLocation


@dataclass(frozen=True, slots=True)
class ProcessingAnswerRecord:
    """One exact question/text item with all respondent rows that share it."""

    processing_id: str
    question_id: str
    text: str
    answer_ids: tuple[str, ...]

    @property
    def occurrence_count(self) -> int:
        return len(self.answer_ids)


@dataclass(frozen=True, slots=True)
class WorkbookDataset:
    """Validated, non-mutating representation of one input workbook."""

    source_path: Path
    questions: tuple[QuestionRecord, ...]
    answers: tuple[AnswerRecord, ...]
    processing_answers: tuple[ProcessingAnswerRecord, ...]

    @property
    def choices_by_question(self) -> dict[str, tuple[ChoiceRecord, ...]]:
        """Return existing choices grouped by their question ID."""

        return {question.question_id: question.choices for question in self.questions}

    @property
    def answers_by_question(self) -> dict[str, tuple[AnswerRecord, ...]]:
        """Return respondent-level answers grouped in source order."""

        grouped: dict[str, list[AnswerRecord]] = {}
        for answer in self.answers:
            grouped.setdefault(answer.question_id, []).append(answer)
        return {question_id: tuple(items) for question_id, items in grouped.items()}

    def to_summary(self, *, output_path: Path | None = None) -> dict[str, Any]:
        """Return the small JSON-safe summary printed by the CLI."""

        summary: dict[str, Any] = {
            "status": "ingested",
            "input": str(self.source_path),
            "question_count": len(self.questions),
            "answer_count": len(self.answers),
            "processing_answer_count": len(self.processing_answers),
        }
        if output_path is not None:
            summary["output"] = str(output_path)
        return summary
