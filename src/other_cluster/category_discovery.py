"""Question-scoped PCA and HDBSCAN evidence for Cluster-First V1."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA

from .domain import (
    CategoryDiscoveryResult,
    DiscoveredCluster,
    DiscoveryPointResult,
    ProcessingAnswerRecord,
    WorkbookDataset,
)
from .embeddings import DIMENSIONS, EmbeddingResult
from .errors import CategoryDiscoveryError

PCA_COMPONENTS = 50
MIN_CLUSTER_SIZE = 3
MIN_UNIQUE_ANSWER_TEXTS = 3
MEMBERSHIP_PROBABILITY_THRESHOLD = 0.5


def discover_categories(
    dataset: WorkbookDataset,
    embeddings: EmbeddingResult,
    *,
    pca_components: int = PCA_COMPONENTS,
    min_unique_answer_texts: int = MIN_UNIQUE_ANSWER_TEXTS,
    membership_probability_threshold: float = MEMBERSHIP_PROBABILITY_THRESHOLD,
) -> CategoryDiscoveryResult:
    """Discover fixed clusters from every canonical answer in every question."""

    _validate_settings(
        pca_components, min_unique_answer_texts, membership_probability_threshold
    )
    vectors_by_processing_id = {
        processing.processing_id: embeddings.vectors[index]
        for index, processing in enumerate(dataset.processing_answers)
    }
    grouped = _group_by_question(dataset.processing_answers)
    points: list[DiscoveryPointResult] = []
    proposal_clusters: list[DiscoveredCluster] = []

    for question_id in sorted(grouped):
        question_answers = grouped[question_id]
        if len(question_answers) < min_unique_answer_texts:
            points.extend(_rare_points(question_answers))
            continue

        question_vectors = np.stack(
            [vectors_by_processing_id[item.processing_id] for item in question_answers]
        )
        effective_components = min(
            pca_components,
            len(question_answers) - 1,
            question_vectors.shape[1],
        )
        if effective_components < 1:
            raise CategoryDiscoveryError(
                f"question '{question_id}' has no valid PCA component count"
            )
        try:
            reduced_vectors = PCA(
                n_components=effective_components,
                svd_solver="randomized",
                random_state=42,
                whiten=False,
            ).fit_transform(question_vectors)
        except Exception as exc:
            raise CategoryDiscoveryError(
                f"PCA reduction failed for question '{question_id}'"
            ) from exc
        labels, probabilities = _cluster(reduced_vectors, question_id=question_id)
        question_points, question_clusters = _classify_question(
            question_id,
            question_answers,
            labels,
            probabilities,
            membership_probability_threshold=membership_probability_threshold,
            min_unique_answer_texts=min_unique_answer_texts,
        )
        points.extend(question_points)
        proposal_clusters.extend(question_clusters)

    points_by_id = {point.processing_id: point for point in points}
    ordered_points = tuple(
        points_by_id[item.processing_id] for item in dataset.processing_answers
    )
    ordered_clusters = tuple(
        sorted(proposal_clusters, key=lambda item: (item.question_id, item.cluster_id))
    )
    unresolved_processing_ids = tuple(
        point.processing_id
        for point in ordered_points
        if point.status != "accepted_cluster"
    )
    return CategoryDiscoveryResult(
        points=ordered_points,
        proposed_clusters=ordered_clusters,
        unresolved_processing_ids=unresolved_processing_ids,
    )


def _validate_settings(
    pca_components: int,
    min_unique_answer_texts: int,
    membership_probability_threshold: float,
) -> None:
    if (
        not isinstance(pca_components, int)
        or isinstance(pca_components, bool)
        or pca_components < 1
    ):
        raise CategoryDiscoveryError("pca_components must be a positive integer")
    if (
        not isinstance(min_unique_answer_texts, int)
        or isinstance(min_unique_answer_texts, bool)
        or min_unique_answer_texts < MIN_UNIQUE_ANSWER_TEXTS
    ):
        raise CategoryDiscoveryError(
            "min_unique_answer_texts must be an integer at least 3"
        )
    if (
        isinstance(membership_probability_threshold, bool)
        or not np.isfinite(membership_probability_threshold)
        or not 0.0 <= membership_probability_threshold <= 1.0
    ):
        raise CategoryDiscoveryError(
            "membership_probability_threshold must be a finite number in [0.0, 1.0]"
        )


def _group_by_question(
    processing_answers: tuple[ProcessingAnswerRecord, ...],
) -> dict[str, list[ProcessingAnswerRecord]]:
    grouped: dict[str, list[ProcessingAnswerRecord]] = defaultdict(list)
    for item in processing_answers:
        grouped[item.question_id].append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item.processing_id)
    return grouped


def _rare_points(
    processing_answers: list[ProcessingAnswerRecord],
) -> list[DiscoveryPointResult]:
    return [
        DiscoveryPointResult(
            processing_id=item.processing_id,
            question_id=item.question_id,
            answer_ids=item.answer_ids,
            occurrence_count=item.occurrence_count,
            raw_cluster_label=None,
            membership_probability=None,
            status="rare_insufficient_distinct_texts",
        )
        for item in processing_answers
    ]


def _cluster(
    reduced_vectors: np.ndarray, *, question_id: str
) -> tuple[np.ndarray, np.ndarray]:
    try:
        clustering = HDBSCAN(
            min_cluster_size=MIN_CLUSTER_SIZE,
            min_samples=None,
            metric="euclidean",
            cluster_selection_method="eom",
            cluster_selection_epsilon=0.0,
            allow_single_cluster=True,
        ).fit(reduced_vectors)
    except Exception as exc:
        raise CategoryDiscoveryError(
            f"HDBSCAN clustering failed for question '{question_id}'"
        ) from exc
    labels = np.asarray(clustering.labels_)
    probabilities = np.asarray(clustering.probabilities_, dtype=float)
    expected_shape = (len(reduced_vectors),)
    if labels.shape != expected_shape or probabilities.shape != expected_shape:
        raise CategoryDiscoveryError(
            "HDBSCAN output is not aligned with discovery points"
        )
    if (
        not np.isfinite(probabilities).all()
        or np.any(probabilities < 0.0)
        or np.any(probabilities > 1.0)
    ):
        raise CategoryDiscoveryError(
            "HDBSCAN membership probabilities must be finite in [0, 1]"
        )
    return labels, probabilities


def _classify_question(
    question_id: str,
    processing_answers: list[ProcessingAnswerRecord],
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    membership_probability_threshold: float,
    min_unique_answer_texts: int,
) -> tuple[list[DiscoveryPointResult], list[DiscoveredCluster]]:
    accepted_by_label: dict[int, list[ProcessingAnswerRecord]] = defaultdict(list)
    points_by_id: dict[str, DiscoveryPointResult] = {}
    probabilities_by_id: dict[str, float] = {}
    labels_by_id: dict[str, int] = {}
    for item, raw_label, raw_probability in zip(
        processing_answers, labels, probabilities, strict=True
    ):
        label = int(raw_label)
        probability = float(raw_probability)
        labels_by_id[item.processing_id] = label
        probabilities_by_id[item.processing_id] = probability
        if label == -1:
            points_by_id[item.processing_id] = _point(
                item, label, probability, status="noise"
            )
        elif probability < membership_probability_threshold:
            points_by_id[item.processing_id] = _point(
                item, label, probability, status="low_probability"
            )
        else:
            accepted_by_label[label].append(item)

    clusters: list[DiscoveredCluster] = []
    for label in sorted(accepted_by_label):
        members = sorted(accepted_by_label[label], key=lambda item: item.processing_id)
        cluster_id = _cluster_id(question_id, label)
        status = (
            "accepted_cluster"
            if len(members) >= min_unique_answer_texts
            else "rejected_small_cluster"
        )
        if status == "accepted_cluster":
            clusters.append(
                DiscoveredCluster(
                    cluster_id=cluster_id,
                    question_id=question_id,
                    raw_cluster_label=label,
                    processing_ids=tuple(item.processing_id for item in members),
                    answer_ids=tuple(
                        answer_id for item in members for answer_id in item.answer_ids
                    ),
                )
            )
        for item in members:
            points_by_id[item.processing_id] = _point(
                item,
                labels_by_id[item.processing_id],
                probabilities_by_id[item.processing_id],
                status=status,
                cluster_id=cluster_id if status == "accepted_cluster" else None,
            )
    return (
        [points_by_id[item.processing_id] for item in processing_answers],
        clusters,
    )


def _point(
    item: ProcessingAnswerRecord,
    raw_cluster_label: int,
    probability: float,
    *,
    status: str,
    cluster_id: str | None = None,
) -> DiscoveryPointResult:
    return DiscoveryPointResult(
        processing_id=item.processing_id,
        question_id=item.question_id,
        answer_ids=item.answer_ids,
        occurrence_count=item.occurrence_count,
        raw_cluster_label=raw_cluster_label,
        membership_probability=probability,
        status=status,
        cluster_id=cluster_id,
    )


def _cluster_id(question_id: str, raw_cluster_label: int) -> str:
    return f"{question_id}:cluster:{raw_cluster_label}"
