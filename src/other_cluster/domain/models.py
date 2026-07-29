"""Small domain records shared by the V1 pipeline boundaries."""

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
        """Return the number of respondent occurrences represented by this item."""

        return len(self.answer_ids)


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
    """A fixed-membership, proposal-eligible group before classification."""

    cluster_id: str
    question_id: str
    raw_cluster_label: int
    processing_ids: tuple[str, ...]
    answer_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CategoryDiscoveryResult:
    """All-answer, question-scoped discovery facts for V1."""

    reductions: tuple[DiscoveryReduction, ...]
    points: tuple[DiscoveryPointResult, ...]
    proposed_clusters: tuple[DiscoveredCluster, ...]
    unresolved_processing_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClusterProposal:
    """One validated Gemini classification for a fixed system cluster."""

    cluster_id: str
    question_id: str
    decision: str
    selected_choice_value: int | None
    english_label: str | None
    arabic_label: str | None
    rejection_reason: str | None
    provider_error: str | None = None


@dataclass(frozen=True, slots=True)
class ClusterClassificationResult:
    """Cluster proposals and safe warnings produced by Gemini classification."""

    proposals: tuple[ClusterProposal, ...]
    warnings: tuple[dict[str, str | None], ...] = ()

    @property
    def request_count(self) -> int:
        """Return the number of eligible clusters submitted to Gemini."""

        return len(self.proposals)

    @property
    def provider_error_count(self) -> int:
        """Return the number of clusters whose provider calls exhausted."""

        return sum(item.decision == "provider_error" for item in self.proposals)


@dataclass(frozen=True, slots=True)
class ReviewFileResult:
    """The authoritative schema-version-2 review file and compact counts."""

    review_file_path: Path
    analysis_run_id: str
    source_sha256: str
    counts: dict[str, int]


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
        """Return existing choices grouped by question ID."""

        return {question.question_id: question.choices for question in self.questions}

    @property
    def answers_by_question(self) -> dict[str, tuple[AnswerRecord, ...]]:
        """Return respondent-level answers grouped in source order."""

        grouped: dict[str, list[AnswerRecord]] = {}
        for answer in self.answers:
            grouped.setdefault(answer.question_id, []).append(answer)
        return {question_id: tuple(items) for question_id, items in grouped.items()}

    def to_summary(self) -> dict[str, Any]:
        """Return the small JSON-safe ingestion summary used by tests and CLI."""

        return {
            "status": "ingested",
            "input": str(self.source_path),
            "question_count": len(self.questions),
            "answer_count": len(self.answers),
            "processing_answer_count": len(self.processing_answers),
        }
