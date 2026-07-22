"""Write the extracted question and answer records to CSV."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .domain import WorkbookDataset
from .errors import ExtractionOutputError

_CSV_HEADERS = (
    "answer_id",
    "question_id",
    "question_english",
    "question_arabic",
    "answer",
    "respondent_key",
    "data_row",
    "source_sheet",
    "source_column",
    "source_cell",
)


def write_extracted_csv(
    dataset: WorkbookDataset, *, output_directory: str | Path
) -> Path:
    """Write one row per extracted answer and return the created CSV path."""

    output_directory = Path(output_directory).expanduser().resolve()
    output_path = output_directory / (
        f"{_normalized_stem(dataset.source_path)}_extracted.csv"
    )
    questions_by_id = {question.question_id: question for question in dataset.questions}

    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=_CSV_HEADERS)
            writer.writeheader()
            for answer in dataset.answers:
                question = questions_by_id[answer.question_id]
                writer.writerow(
                    {
                        "answer_id": answer.answer_id,
                        "question_id": answer.question_id,
                        "question_english": question.english_text,
                        "question_arabic": question.arabic_text,
                        "answer": answer.text,
                        "respondent_key": answer.respondent_key,
                        "data_row": answer.data_row,
                        "source_sheet": answer.source_cell.sheet,
                        "source_column": answer.source_column,
                        "source_cell": answer.source_cell.coordinate,
                    }
                )
    except (KeyError, OSError, csv.Error) as exc:
        raise ExtractionOutputError(
            f"could not save extracted CSV '{output_path}': {exc}"
        ) from exc

    return output_path


def _normalized_stem(source_path: Path) -> str:
    """Return a lowercase, underscore-separated source filename stem."""

    normalized = re.sub(r"\s+", "_", source_path.stem.strip().lower())
    return normalized or "workbook"
