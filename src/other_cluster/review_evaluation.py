"""Evaluation metrics and human-readable reporting for review files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .review_completion import project_review_changes
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


@dataclass(frozen=True, slots=True)
class WorkspaceGroupEvaluation:
    """Current reportable state for one active or retired V4 group."""

    group_id: str
    origin: str
    review_state: str
    unique_answer_count: int
    response_count: int
    decision: dict[str, Any] | None
    provider_warning: bool


@dataclass(frozen=True, slots=True)
class WorkspaceQuestionEvaluation:
    """Current reportable workspace state for one V4 question."""

    question_id: str
    question_text: str
    total_unique_answers: int
    total_responses: int
    active_groups: tuple[WorkspaceGroupEvaluation, ...]
    retired_groups: tuple[WorkspaceGroupEvaluation, ...]
    needs_attention_count: int
    needs_attention_responses: int
    needs_attention_provider_warnings: int
    excluded_count: int
    excluded_responses: int
    excluded_provider_warnings: int


@dataclass(frozen=True, slots=True)
class WorkspaceEvaluation:
    """Ordinary current-state evaluation for a V4 review artifact."""

    status: str
    revision: int
    questions: tuple[WorkspaceQuestionEvaluation, ...]
    net_changes: dict[str, Any]


def evaluate_review_file(
    path: str | Path,
) -> tuple[QuestionEvaluation, ...] | WorkspaceEvaluation:
    """Load, validate, and evaluate one persisted review file."""

    return evaluate_review_document(load_review_file(path))


def evaluate_review_document(
    document: dict[str, Any],
) -> tuple[QuestionEvaluation, ...] | WorkspaceEvaluation:
    """Calculate per-question metrics from a validated review document."""

    if document["schema_version"] == 4:
        return _evaluate_workspace(document)

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
    evaluations: tuple[QuestionEvaluation, ...] | WorkspaceEvaluation,
    *,
    review_file: str | None = None,
) -> str:
    """Format evaluation facts as a compact report for terminal output."""

    if isinstance(evaluations, WorkspaceEvaluation):
        return _format_workspace(evaluations, review_file=review_file)

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


def _evaluate_workspace(document: dict[str, Any]) -> WorkspaceEvaluation:
    questions = []
    for question in document["questions"]:
        answers_by_id = {
            answer["processing_id"]: answer for answer in question["answers"]
        }
        warning_ids = {
            processing_id
            for group in question["automatic_groups"]
            if group["provider_proposal"]["provider_error"]
            for processing_id in group["member_processing_ids"]
        }
        workspace = question["workspace"]
        questions.append(
            WorkspaceQuestionEvaluation(
                question_id=question["question_id"],
                question_text=question["question_text"]["english"],
                total_unique_answers=len(answers_by_id),
                total_responses=sum(
                    int(answer["occurrence_count"]) for answer in answers_by_id.values()
                ),
                active_groups=tuple(
                    _workspace_group(group, answers_by_id, warning_ids)
                    for group in workspace["active_groups"]
                ),
                retired_groups=tuple(
                    _workspace_group(group, answers_by_id, warning_ids)
                    for group in workspace["retired_groups"]
                ),
                needs_attention_count=len(workspace["needs_attention"]),
                needs_attention_responses=_response_count(
                    workspace["needs_attention"], answers_by_id
                ),
                needs_attention_provider_warnings=len(
                    warning_ids.intersection(workspace["needs_attention"])
                ),
                excluded_count=len(workspace["excluded_answers"]),
                excluded_responses=_response_count(
                    workspace["excluded_answers"], answers_by_id
                ),
                excluded_provider_warnings=len(
                    warning_ids.intersection(workspace["excluded_answers"])
                ),
            )
        )
    return WorkspaceEvaluation(
        status=document["status"],
        revision=document["revision"],
        questions=tuple(questions),
        net_changes=project_review_changes(document)["net_changes"],
    )


def _workspace_group(
    group: dict[str, Any],
    answers_by_id: dict[str, dict[str, Any]],
    warning_ids: set[str],
) -> WorkspaceGroupEvaluation:
    member_ids = group["member_processing_ids"]
    return WorkspaceGroupEvaluation(
        group_id=group["group_id"],
        origin=group["origin"],
        review_state=group["review_state"],
        unique_answer_count=len(member_ids),
        response_count=_response_count(member_ids, answers_by_id),
        decision=group["decision"],
        provider_warning=bool(warning_ids.intersection(member_ids)),
    )


def _response_count(
    processing_ids: list[str], answers_by_id: dict[str, dict[str, Any]]
) -> int:
    return sum(int(answers_by_id[item]["occurrence_count"]) for item in processing_ids)


def _format_workspace(
    evaluation: WorkspaceEvaluation, *, review_file: str | None
) -> str:
    lines = [
        f"Review evaluation: {review_file}" if review_file else "Review evaluation",
        "Schema version: 4",
        f"Status: {evaluation.status} (revision {evaluation.revision})",
    ]
    for question in evaluation.questions:
        lines.extend(
            [
                "",
                f"Question: {question.question_id} - {question.question_text}",
                (
                    f"  Totals: {question.total_unique_answers} unique answers; "
                    f"{question.total_responses} respondent responses"
                ),
                f"  Active groups: {len(question.active_groups)}",
            ]
        )
        for group in question.active_groups:
            lines.extend(_format_workspace_group(group))
        lines.extend(
            [
                (
                    f"  Needs attention: {question.needs_attention_count} "
                    f"{_noun(question.needs_attention_count, 'unique answer')}; "
                    f"{question.needs_attention_responses} "
                    f"{_noun(question.needs_attention_responses, 'respondent response')}; "
                    f"provider warnings={question.needs_attention_provider_warnings}"
                ),
                (
                    f"  Excluded: {question.excluded_count} "
                    f"{_noun(question.excluded_count, 'unique answer')}; "
                    f"{question.excluded_responses} "
                    f"{_noun(question.excluded_responses, 'respondent response')}; "
                    f"provider warnings={question.excluded_provider_warnings}"
                ),
                f"  Retired groups: {len(question.retired_groups)}",
            ]
        )
        for group in question.retired_groups:
            lines.extend(_format_workspace_group(group))
    net = evaluation.net_changes
    lines.extend(
        [
            "",
            (
                "Net modifications: "
                f"moved={net['moved_canonical_answer_count']} unique/"
                f"{net['moved_response_count']} responses; "
                f"created={net['reviewer_created_group_count']}; "
                f"retired={net['retired_original_group_count']}; "
                f"excluded={net['excluded_answer_count']} unique/"
                f"{net['excluded_response_count']} responses; "
                "invalidated confirmations="
                f"{net['confirmation_invalidated_group_count']}"
            ),
        ]
    )
    return "\n".join(lines)


def _format_workspace_group(group: WorkspaceGroupEvaluation) -> list[str]:
    return [
        (
            f"    {group.group_id} [{group.origin}]: {group.review_state}; "
            f"{group.unique_answer_count} "
            f"{_noun(group.unique_answer_count, 'unique answer')}; "
            f"{group.response_count} "
            f"{_noun(group.response_count, 'respondent response')}"
        ),
        f"      Coding destination: {_format_decision(group.decision)}",
        f"      Provider warning: {'present' if group.provider_warning else 'none'}",
    ]


def _format_decision(decision: dict[str, Any] | None) -> str:
    if decision is None:
        return "none"
    if decision["decision"] == "existing_choice":
        return f"existing choice · {decision['selected_choice_value']}"
    return f"new category · {decision['english_label']} · {decision['arabic_label']}"


def _noun(count: int, singular: str) -> str:
    return singular if count == 1 else singular + "s"


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
