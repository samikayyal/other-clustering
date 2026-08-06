from __future__ import annotations

from pathlib import Path

import numpy as np
from openpyxl import Workbook

from other_cluster.domain import WorkbookDataset
from other_cluster.embeddings import (
    DiscoveryEmbeddingResult,
    MEDIUM_QUESTION_MAX_ANSWERS,
    MODERATE_QUESTION_MAX_ANSWERS,
    SMALL_QUESTION_MAX_ANSWERS,
)


def create_workbook(path: Path, *, answers: list[object] | None = None) -> Path:
    """Create a small representative workbook for Feature 01 tests."""

    answer_values = answers or ["لبناني", "لبناني", None, "other text"]
    workbook = Workbook()

    survey = workbook.active
    survey.title = "Survey"
    survey.append(["type", "name", "label:english", "label:arabic"])
    survey.append(["text", "B5", "Country of origin", "بلد المنشأ"])

    code = workbook.create_sheet("Code")
    code.append(["list_name", "value", "label:english", "label:arabic"])
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

    workbook.create_sheet("Counter")
    workbook.create_sheet("Note")
    workbook.create_sheet("Report")
    workbook.save(path)
    return path


def discovery_embeddings(dataset: WorkbookDataset) -> DiscoveryEmbeddingResult:
    """Return simple aligned unit vectors for discovery-focused tests."""

    counts = {
        question_id: sum(
            answer.question_id == question_id for answer in dataset.processing_answers
        )
        for question_id in {answer.question_id for answer in dataset.processing_answers}
    }
    vector = np.asarray([1.0, 0.0])
    instructed = {
        answer.processing_id: vector
        for answer in dataset.processing_answers
        if counts[answer.question_id] >= 2
    }
    raw = {
        answer.processing_id: vector
        for answer in dataset.processing_answers
        if counts[answer.question_id] >= 2
        and (
            counts[answer.question_id] <= SMALL_QUESTION_MAX_ANSWERS
            or MEDIUM_QUESTION_MAX_ANSWERS
            < counts[answer.question_id]
            <= MODERATE_QUESTION_MAX_ANSWERS
        )
    }
    return DiscoveryEmbeddingResult(instructed, raw)
