from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook


def create_workbook(path: Path, *, answers: list[object] | None = None) -> Path:
    """Create a small representative workbook for Feature 01 tests."""

    answer_values = answers or ["لبناني", "لبناني", None, "other text"]
    workbook = Workbook()

    survey = workbook.active
    survey.title = "Survey"
    survey.append(["Coding", "type", "name", "label", "label:arabic"])
    survey.append([1, "text", "B5_other", "Country of origin", "بلد المنشأ"])

    code = workbook.create_sheet("Code")
    code.append(["list_name", "value", "label", "label:arabic"])
    code.append(["B5_other", -96, "Other", "أخرى"])
    code.append(["B5_other", 1, "Lebanese", "لبناني"])
    code.append(["B5_other", 2, "Syrian", "سوري"])

    data = workbook.create_sheet("Data")
    data.append(["KEY", "enumerator_id", "enumerator_name", "B5_other"])
    for index, answer in enumerate(answer_values, start=1):
        data.append(
            [f"respondent-{index}", f"enum-{index}", f"Enumerator {index}", answer]
        )
    if len(answer_values) >= 4:
        data.row_dimensions[5].hidden = True

    work = workbook.create_sheet("Work")
    work.append(
        [
            "KEY",
            "enumerator_id",
            "enumerator_name",
            "B5_other",
            "B5_other_Coded",
            "B5_other_C1",
        ]
    )
    for index in range(1, len(answer_values) + 1):
        row = index + 1
        work.append(
            [
                f"respondent-{index}",
                f"enum-{index}",
                f"Enumerator {index}",
                f"=Data!D{row}",
                None,
                f'=IFERROR(VLOOKUP(E{row},Code!$C:$D,2,FALSE),"")',
            ]
        )

    workbook.create_sheet("Counter")
    workbook.create_sheet("Note")
    workbook.create_sheet("Report")
    workbook.save(path)
    return path
