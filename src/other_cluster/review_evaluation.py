"""Evaluation metrics and human-readable reporting for review files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .review_file import load_review_file

MAX_REPRESENTATIVE_TEXTS = 3
_ACCEPTED_GEMINI_DECISIONS = {"existing_choice", "new_category"}


@dataclass(frozen=True, slots=True)
class ClusterEvaluation:
    """The reportable facts for one classified cluster."""

    cluster_id: str
    size: int
    representative_texts: tuple[str, ...]
    gemini_result: str


@dataclass(frozen=True, slots=True)
class QuestionEvaluation:
    """The reportable clustering and classification facts for one question."""

    question_id: str
    question_text: str
    total_canonical_answers: int
    clustered_canonical_answers: int
    unresolved_canonical_answers: int
    clustered_percentage: float
    unresolved_percentage: float
    largest_cluster_share: float
    clusters: tuple[ClusterEvaluation, ...]


def evaluate_review_file(path: str | Path) -> tuple[QuestionEvaluation, ...]:
    """Load, validate, and evaluate one persisted review file."""

    return evaluate_review_document(load_review_file(path))


def evaluate_review_document(
    document: dict[str, Any],
) -> tuple[QuestionEvaluation, ...]:
    """Calculate per-question metrics from a validated review document."""

    evaluations: list[QuestionEvaluation] = []
    for question in document["questions"]:
        answers_by_id = {
            answer["processing_id"]: answer for answer in question["answers"]
        }
        clusters = tuple(
            _cluster_evaluation(cluster, answers_by_id)
            for cluster in question["clusters"]
        )
        clustered_count = sum(cluster.size for cluster in clusters)
        unresolved_count = len(question["unresolved_answers"])
        total_count = len(question["answers"])
        evaluations.append(
            QuestionEvaluation(
                question_id=question["question_id"],
                question_text=question["question_text"]["english"],
                total_canonical_answers=total_count,
                clustered_canonical_answers=clustered_count,
                unresolved_canonical_answers=unresolved_count,
                clustered_percentage=_percentage(clustered_count, total_count),
                unresolved_percentage=_percentage(unresolved_count, total_count),
                largest_cluster_share=_percentage(
                    max((cluster.size for cluster in clusters), default=0), total_count
                ),
                clusters=clusters,
            )
        )
    return tuple(evaluations)


def format_evaluation(
    evaluations: tuple[QuestionEvaluation, ...], *, review_file: str | None = None
) -> str:
    """Format evaluation facts as a compact report for terminal output."""

    lines = [
        f"Review evaluation: {review_file}" if review_file else "Review evaluation"
    ]
    for question in evaluations:
        lines.extend(
            [
                "",
                f"Question: {question.question_id} - {question.question_text}",
                f"  Number of clusters: {len(question.clusters)}",
                f"  Cluster sizes: {_cluster_sizes(question)}",
                (
                    "  Clustered versus unresolved: "
                    f"{question.clustered_percentage:.1f}% clustered "
                    f"({question.clustered_canonical_answers}/{question.total_canonical_answers}) "
                    f"versus {question.unresolved_percentage:.1f}% unresolved "
                    f"({question.unresolved_canonical_answers}/{question.total_canonical_answers}) "
                    "canonical answer texts"
                ),
                (
                    "  Largest-cluster share: "
                    f"{question.largest_cluster_share:.1f}% of canonical answer texts"
                ),
            ]
        )
        if not question.clusters:
            lines.append("  Clusters: none")
            continue
        for cluster in question.clusters:
            lines.extend(
                [
                    f"  Cluster {cluster.cluster_id} ({cluster.size} members):",
                    "    Representative member texts: "
                    + "; ".join(cluster.representative_texts),
                    f"    Gemini: {cluster.gemini_result}",
                ]
            )
    return "\n".join(lines)


def _cluster_evaluation(
    cluster: dict[str, Any], answers_by_id: dict[str, dict[str, Any]]
) -> ClusterEvaluation:
    member_ids = cluster["member_processing_ids"]
    proposal = cluster["gemini_proposal"]
    decision = proposal["decision"]
    if decision in _ACCEPTED_GEMINI_DECISIONS:
        result = f"ACCEPTED ({decision})"
    elif decision == "reject_cluster":
        result = f"REJECTED ({decision}: {proposal['rejection_reason']})"
    else:
        result = f"ERROR ({decision}: {proposal['provider_error']})"
    return ClusterEvaluation(
        cluster_id=cluster["cluster_id"],
        size=len(member_ids),
        representative_texts=tuple(
            answers_by_id[member_id]["text"]
            for member_id in member_ids[:MAX_REPRESENTATIVE_TEXTS]
        ),
        gemini_result=result,
    )


def _cluster_sizes(question: QuestionEvaluation) -> str:
    return ", ".join(str(cluster.size) for cluster in question.clusters) or "none"


def _percentage(numerator: int, denominator: int) -> float:
    return numerator * 100 / denominator if denominator else 0.0
