"""Domain records for the workbook ingestion boundary."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
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
    survey_row: int
    choices: tuple[ChoiceRecord, ...]


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    """One respondent-level answer and its exact source cell."""

    answer_id: str
    question_id: str
    source_column: str
    text: str
    respondent_key: str
    data_row: int
    source_cell: CellLocation


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
class ExistingChoiceVerification:
    """One Feature 03 outcome for a canonical question/text processing item."""

    processing_id: str
    question_id: str
    status: str
    selected_choice_value: int | None
    provider_evaluated: bool


@dataclass(frozen=True, slots=True)
class ExistingChoiceAssignment:
    """An accepted existing-choice value fanned out to one respondent answer."""

    answer_id: str
    question_id: str
    choice_value: int


@dataclass(frozen=True, slots=True)
class ExistingChoiceAssignmentResult:
    """Feature 03 decisions, accepted assignments, and discovery input IDs."""

    verifications: tuple[ExistingChoiceVerification, ...]
    assignments: tuple[ExistingChoiceAssignment, ...]
    unassigned_answer_ids: tuple[str, ...]

    @property
    def assignments_by_answer_id(self) -> dict[str, int]:
        """Return accepted assignments keyed by their stable answer IDs."""

        return {
            assignment.answer_id: assignment.choice_value
            for assignment in self.assignments
        }


@dataclass(frozen=True, slots=True)
class DiscoveryReduction:
    """Question-scoped PCA evidence retained for the active analysis run."""

    question_id: str
    processing_ids: tuple[str, ...]
    requested_components: int
    effective_components: int
    reduced_vectors: Any


@dataclass(frozen=True, slots=True)
class DiscoveryPointResult:
    """Raw and accepted discovery evidence for one canonical answer text."""

    processing_id: str
    question_id: str
    answer_ids: tuple[str, ...]
    occurrence_count: int
    raw_cluster_label: int | None
    membership_probability: float | None
    status: str
    cluster_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredCluster:
    """A proposal-eligible group, before labeling or code allocation."""

    cluster_id: str
    question_id: str
    raw_cluster_label: int
    processing_ids: tuple[str, ...]
    answer_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClusterMergeSuggestion:
    """Original-vector cosine evidence for a possible cluster merge."""

    question_id: str
    first_cluster_id: str
    second_cluster_id: str
    cosine_similarity: float
    first_processing_ids: tuple[str, ...]
    second_processing_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CategoryDiscoveryResult:
    """Feature 04 facts, preserving every discovery input for review."""

    reductions: tuple[DiscoveryReduction, ...]
    points: tuple[DiscoveryPointResult, ...]
    proposed_clusters: tuple[DiscoveredCluster, ...]
    unresolved_answer_ids: tuple[str, ...]
    merge_suggestions: tuple[ClusterMergeSuggestion, ...]


@dataclass(slots=True)
class WorkbookDiagnostics:
    """Mutable diagnostics collected during workbook extraction."""

    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_issue(self, message: str) -> None:
        self.issues.append(message)

    def add_issues(self, messages: Iterable[str]) -> None:
        self.issues.extend(messages)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


@dataclass(frozen=True, slots=True)
class WorkbookDataset:
    """Validated, non-mutating representation of one input workbook."""

    source_path: Path
    questions: tuple[QuestionRecord, ...]
    answers: tuple[AnswerRecord, ...]
    processing_answers: tuple[ProcessingAnswerRecord, ...]
    warnings: tuple[str, ...] = ()

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
