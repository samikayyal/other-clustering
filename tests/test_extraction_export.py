from __future__ import annotations

import csv
from pathlib import Path

from other_cluster.extraction_export import write_extracted_csv
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


def test_extracted_csv_uses_normalized_filename_and_preserves_answer_provenance(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "My Survey Answers.xlsx")
    dataset = ingest_workbook(input_path)

    output_path = write_extracted_csv(
        dataset, output_directory=tmp_path / "extracted_data"
    )

    assert (
        output_path == tmp_path / "extracted_data" / "my_survey_answers_extracted.csv"
    )
    with output_path.open("r", newline="", encoding="utf-8-sig") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert len(rows) == 3
    assert rows[0] == {
        "answer_id": "B5_other:2",
        "question_id": "B5_other",
        "question_english": "Country of origin",
        "question_arabic": "بلد المنشأ",
        "answer": "لبناني",
        "respondent_key": "respondent-1",
        "data_row": "2",
        "source_sheet": "Data",
        "source_column": "B5_other",
        "source_cell": "D2",
    }
