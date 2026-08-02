"""Label-invariant clustering evaluation against a hand-coded ``Work`` sheet."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sklearn.metrics import adjusted_rand_score

from .errors import GroundTruthError
from .input_sources import materialize_input
from .review_file import load_review_file

WORK_SHEET = "Work"
CODED_SUFFIX = "_Coded"
CODE_SUFFIX = "_C1"
_GOOGLE_SHEET_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class PartitionMetrics:
    """Label-invariant facts for one predicted/ground-truth partition pair."""

    item_count: int
    clustered_item_count: int
    clustered_percentage: float
    adjusted_rand_index: float
    pairwise_precision: float
    pairwise_recall: float
    pairwise_f1: float


@dataclass(frozen=True, slots=True)
class GroundTruthGroup:
    """One human-coded answer group for display in the review browser."""

    code: str
    label: str
    member_processing_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundTruthQuestionEvaluation:
    """Benchmark results for one question with hand-coded answers."""

    question_id: str
    human_cluster_count: int
    canonical: PartitionMetrics
    occurrences: PartitionMetrics
    ground_truth_groups: tuple[GroundTruthGroup, ...] = ()


@dataclass(frozen=True, slots=True)
class GroundTruthAlignment:
    """Coverage and exclusion diagnostics for review-to-Work alignment."""

    review_canonical_answers: int
    review_occurrences: int
    labeled_canonical_answers: int
    labeled_occurrences: int
    unlabeled_occurrences: int
    missing_key_occurrences: int
    text_mismatch_occurrences: int
    ambiguous_canonical_answers: int


@dataclass(frozen=True, slots=True)
class GroundTruthEvaluation:
    """Overall and per-question benchmark results."""

    alignment: GroundTruthAlignment
    human_cluster_count: int
    canonical: PartitionMetrics
    occurrences: PartitionMetrics
    questions: tuple[GroundTruthQuestionEvaluation, ...]


@dataclass(frozen=True, slots=True)
class _AlignedAnswer:
    question_id: str
    processing_id: str
    predicted_label: str
    truth_label: str
    truth_code: str
    truth_display_label: str
    labeled_occurrence_count: int
    clustered: bool


@dataclass(frozen=True, slots=True)
class _WorkQuestion:
    raw_column: int
    coded_column: int
    code_column: int


def evaluate_ground_truth_file(
    review_path: str | Path, ground_truth_source: str | Path
) -> GroundTruthEvaluation:
    """Evaluate one validated review file against a local or Google Work sheet."""

    document = load_review_file(review_path)
    with materialize_ground_truth(ground_truth_source) as ground_truth_path:
        return evaluate_ground_truth_document(document, ground_truth_path)


@contextmanager
def materialize_ground_truth(source: str | Path) -> Iterator[Path]:
    """Resolve XLSX, Google Sheets URL, or local ``.gsheet`` pointer input."""

    source_text = str(source)
    path = Path(source_text)
    resolved_source = source_text
    if path.suffix.casefold() == ".gsheet":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GroundTruthError(
                f"could not read Google Sheets pointer '{path}': {exc}"
            ) from exc
        document_id = payload.get("doc_id") if isinstance(payload, dict) else None
        if not isinstance(document_id, str) or not _GOOGLE_SHEET_ID.fullmatch(
            document_id
        ):
            raise GroundTruthError(
                f"Google Sheets pointer '{path}' has an invalid doc_id"
            )
        resolved_source = f"https://docs.google.com/spreadsheets/d/{document_id}/edit"
    with materialize_input(resolved_source) as materialized:
        if materialized.suffix.casefold() != ".xlsx":
            raise GroundTruthError("ground truth must resolve to an .xlsx workbook")
        yield materialized


def evaluate_ground_truth_document(
    document: dict[str, Any], ground_truth_path: str | Path
) -> GroundTruthEvaluation:
    """Align a validated review document to ``Work`` and calculate metrics."""

    try:
        workbook = load_workbook(ground_truth_path, data_only=True, read_only=False)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise GroundTruthError(
            f"could not open ground-truth workbook '{ground_truth_path}': {exc}"
        ) from exc
    try:
        if WORK_SHEET not in workbook.sheetnames:
            raise GroundTruthError(
                f"ground-truth workbook is missing required sheet '{WORK_SHEET}'"
            )
        work = workbook[WORK_SHEET]
        key_column = _key_column(work)
        rows_by_key = _rows_by_key(work, key_column)
        questions = _work_questions(work)
        aligned, alignment = _align_document(document, work, rows_by_key, questions)
    finally:
        workbook.close()

    grouped = _group_by_question(aligned)
    question_results = tuple(
        _evaluate_question(question_id, items)
        for question_id, items in sorted(grouped.items())
    )
    return GroundTruthEvaluation(
        alignment=alignment,
        human_cluster_count=sum(item.human_cluster_count for item in question_results),
        canonical=_partition_metrics(aligned, occurrence_weighted=False),
        occurrences=_partition_metrics(aligned, occurrence_weighted=True),
        questions=question_results,
    )


def format_ground_truth_evaluation(
    evaluation: GroundTruthEvaluation,
    *,
    review_file: str | None = None,
    ground_truth: str | None = None,
) -> str:
    """Format a ground-truth benchmark as a compact terminal report."""

    title = "Ground-truth clustering benchmark"
    if review_file:
        title += f": {review_file}"
    lines = [title]
    if ground_truth:
        lines.append(f"Ground truth: {ground_truth} (Work tab)")
    alignment = evaluation.alignment
    lines.extend(
        [
            (
                "Alignment: "
                f"{alignment.labeled_canonical_answers}/"
                f"{alignment.review_canonical_answers} canonical answers and "
                f"{alignment.labeled_occurrences}/"
                f"{alignment.review_occurrences} respondent occurrences have "
                "human codes"
            ),
            (
                "Excluded occurrences: "
                f"unlabeled={alignment.unlabeled_occurrences}, "
                f"missing_key={alignment.missing_key_occurrences}, "
                f"text_mismatch={alignment.text_mismatch_occurrences}; "
                "ambiguous canonical answers="
                f"{alignment.ambiguous_canonical_answers}"
            ),
            "",
            f"Overall ({evaluation.human_cluster_count} human clusters):",
            "  Canonical answers: " + _format_metrics(evaluation.canonical),
            "  Respondent occurrences: " + _format_metrics(evaluation.occurrences),
        ]
    )
    for question in evaluation.questions:
        lines.extend(
            [
                "",
                f"Question: {question.question_id} "
                f"({question.human_cluster_count} human clusters)",
                "  Canonical answers: " + _format_metrics(question.canonical),
                "  Respondent occurrences: " + _format_metrics(question.occurrences),
            ]
        )
    return "\n".join(lines)


def _format_metrics(metrics: PartitionMetrics) -> str:
    return (
        f"n={metrics.item_count}, coverage={metrics.clustered_percentage:.1f}%, "
        f"ARI={metrics.adjusted_rand_index:.3f}, "
        f"pairwise precision={metrics.pairwise_precision:.3f}, "
        f"recall={metrics.pairwise_recall:.3f}, F1={metrics.pairwise_f1:.3f}"
    )


def _key_column(work: Any) -> int:
    matches = [
        column
        for column in range(1, work.max_column + 1)
        if isinstance(work.cell(1, column).value, str)
        and work.cell(1, column).value.casefold() == "key"
    ]
    if len(matches) != 1:
        raise GroundTruthError("Work row 1 must contain exactly one KEY header")
    return matches[0]


def _rows_by_key(work: Any, key_column: int) -> dict[str, int]:
    rows: dict[str, int] = {}
    for row in range(2, work.max_row + 1):
        key = _text_key(work.cell(row, key_column).value)
        if key is None:
            continue
        if key in rows:
            raise GroundTruthError(
                f"Work KEY '{key}' appears more than once (rows {rows[key]} and {row})"
            )
        rows[key] = row
    return rows


def _work_questions(work: Any) -> dict[str, _WorkQuestion]:
    headers = {
        value: column
        for column in range(1, work.max_column + 1)
        if isinstance((value := work.cell(1, column).value), str) and value
    }
    questions: dict[str, _WorkQuestion] = {}
    for header, raw_column in headers.items():
        coded_column = headers.get(header + CODED_SUFFIX)
        code_column = headers.get(header + CODE_SUFFIX)
        if coded_column is None and code_column is None:
            continue
        if coded_column is None or code_column is None:
            raise GroundTruthError(
                f"Work question '{header}' must have both {header + CODED_SUFFIX} "
                f"and {header + CODE_SUFFIX} headers"
            )
        questions[header] = _WorkQuestion(
            raw_column=raw_column,
            coded_column=coded_column,
            code_column=code_column,
        )
    if not questions:
        raise GroundTruthError("Work contains no raw/_Coded/_C1 question blocks")
    return questions


def _align_document(
    document: dict[str, Any],
    work: Any,
    rows_by_key: dict[str, int],
    work_questions: dict[str, _WorkQuestion],
) -> tuple[list[_AlignedAnswer], GroundTruthAlignment]:
    aligned: list[_AlignedAnswer] = []
    review_canonical = review_occurrences = 0
    labeled_occurrences = unlabeled = missing_keys = mismatches = ambiguous = 0
    labels_by_code: dict[tuple[str, str], str] = {}

    for question in document["questions"]:
        question_id = question["question_id"]
        work_question = work_questions.get(question_id)
        for answer in question["answers"]:
            review_canonical += 1
            mappings = answer["row_mappings"]
            review_occurrences += len(mappings)
            if work_question is None:
                unlabeled += len(mappings)
                continue
            codes: Counter[str] = Counter()
            answer_labeled_occurrences = 0
            for mapping in mappings:
                key = _text_key(mapping["respondent_key"])
                row = rows_by_key.get(key) if key is not None else None
                if row is None:
                    missing_keys += 1
                    continue
                raw = work.cell(row, work_question.raw_column).value
                if not _same_text(raw, answer["text"]):
                    mismatches += 1
                    continue
                code = _code(work.cell(row, work_question.code_column).value)
                if code is None:
                    unlabeled += 1
                    continue
                coded_label = work.cell(row, work_question.coded_column).value
                label = coded_label.strip() if isinstance(coded_label, str) else ""
                label_key = (question_id, code)
                previous_label = labels_by_code.get(label_key)
                if previous_label is not None and label and previous_label != label:
                    raise GroundTruthError(
                        f"Work code {code!r} for question '{question_id}' maps to "
                        f"multiple labels ({previous_label!r} and {label!r})"
                    )
                if label:
                    labels_by_code[label_key] = label
                codes[code] += 1
                answer_labeled_occurrences += 1
            labeled_occurrences += answer_labeled_occurrences
            if not codes:
                continue
            if len(codes) != 1:
                ambiguous += 1
                labeled_occurrences -= answer_labeled_occurrences
                continue
            code = next(iter(codes))
            evidence = answer["discovery_evidence"]
            cluster_id = evidence["cluster_id"]
            clustered = isinstance(cluster_id, str)
            predicted_label = (
                f"{question_id}:predicted:{cluster_id}"
                if clustered
                else f"{question_id}:singleton:{answer['processing_id']}"
            )
            aligned.append(
                _AlignedAnswer(
                    question_id=question_id,
                    processing_id=answer["processing_id"],
                    predicted_label=predicted_label,
                    truth_label=f"{question_id}:truth:{code}",
                    truth_code=code,
                    truth_display_label=labels_by_code.get((question_id, code), ""),
                    labeled_occurrence_count=answer_labeled_occurrences,
                    clustered=clustered,
                )
            )

    return aligned, GroundTruthAlignment(
        review_canonical_answers=review_canonical,
        review_occurrences=review_occurrences,
        labeled_canonical_answers=len(aligned),
        labeled_occurrences=labeled_occurrences,
        unlabeled_occurrences=unlabeled,
        missing_key_occurrences=missing_keys,
        text_mismatch_occurrences=mismatches,
        ambiguous_canonical_answers=ambiguous,
    )


def _text_key(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(int(value)) if value.is_integer() else str(value)
    return None


def _same_text(value: object, expected: str) -> bool:
    return isinstance(value, str) and value == expected


def _code(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _group_by_question(
    items: list[_AlignedAnswer],
) -> dict[str, list[_AlignedAnswer]]:
    grouped: dict[str, list[_AlignedAnswer]] = defaultdict(list)
    for item in items:
        grouped[item.question_id].append(item)
    return grouped


def _evaluate_question(
    question_id: str, items: list[_AlignedAnswer]
) -> GroundTruthQuestionEvaluation:
    return GroundTruthQuestionEvaluation(
        question_id=question_id,
        human_cluster_count=len({item.truth_label for item in items}),
        canonical=_partition_metrics(items, occurrence_weighted=False),
        occurrences=_partition_metrics(items, occurrence_weighted=True),
        ground_truth_groups=_ground_truth_groups(items),
    )


def _ground_truth_groups(
    items: list[_AlignedAnswer],
) -> tuple[GroundTruthGroup, ...]:
    members_by_code: dict[str, list[str]] = defaultdict(list)
    labels_by_code: dict[str, str] = {}
    for item in items:
        members_by_code[item.truth_code].append(item.processing_id)
        if item.truth_display_label and item.truth_code not in labels_by_code:
            labels_by_code[item.truth_code] = item.truth_display_label
    return tuple(
        GroundTruthGroup(
            code=code,
            label=labels_by_code.get(code, ""),
            member_processing_ids=tuple(processing_ids),
        )
        for code, processing_ids in sorted(members_by_code.items())
    )


def _partition_metrics(
    items: list[_AlignedAnswer], *, occurrence_weighted: bool
) -> PartitionMetrics:
    predicted: list[str] = []
    truth: list[str] = []
    clustered_count = 0
    for item in items:
        weight = item.labeled_occurrence_count if occurrence_weighted else 1
        predicted.extend([item.predicted_label] * weight)
        truth.extend([item.truth_label] * weight)
        if item.clustered:
            clustered_count += weight
    item_count = len(truth)
    precision, recall, f1 = _pairwise_scores(predicted, truth)
    return PartitionMetrics(
        item_count=item_count,
        clustered_item_count=clustered_count,
        clustered_percentage=(clustered_count * 100 / item_count if item_count else 0),
        adjusted_rand_index=(
            float(adjusted_rand_score(truth, predicted)) if item_count else 0.0
        ),
        pairwise_precision=precision,
        pairwise_recall=recall,
        pairwise_f1=f1,
    )


def _pairwise_scores(
    predicted: list[str], truth: list[str]
) -> tuple[float, float, float]:
    predicted_counts = Counter(predicted)
    truth_counts = Counter(truth)
    joint_counts = Counter(zip(predicted, truth, strict=True))
    predicted_pairs = sum(_pairs(count) for count in predicted_counts.values())
    truth_pairs = sum(_pairs(count) for count in truth_counts.values())
    true_positive_pairs = sum(_pairs(count) for count in joint_counts.values())
    precision = true_positive_pairs / predicted_pairs if predicted_pairs else 0.0
    recall = true_positive_pairs / truth_pairs if truth_pairs else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _pairs(count: int) -> int:
    return count * (count - 1) // 2
