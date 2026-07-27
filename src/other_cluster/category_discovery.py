"""Question-scoped PCA and HDBSCAN evidence for new-category discovery."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA

from .domain import (
    CategoryDiscoveryResult,
    ClusterMergeSuggestion,
    DiscoveredCluster,
    DiscoveryPointResult,
    DiscoveryReduction,
    ExistingChoiceAssignmentResult,
    ProcessingAnswerRecord,
    WorkbookDataset,
)
from .embeddings import DIMENSIONS, EmbeddingResult
from .errors import CategoryDiscoveryError


def discover_categories(
    dataset: WorkbookDataset,
    embeddings: EmbeddingResult,
    assignments: ExistingChoiceAssignmentResult,
    *,
    pca_components: int = 50,
    min_unique_answer_texts: int = 3,
    membership_probability_threshold: float = 0.5,
    merge_cosine_similarity_threshold: float = 0.90,
) -> CategoryDiscoveryResult:
    """Discover same-question dense groups among Feature 03 no-match answers."""

    _validate_inputs(
        dataset,
        embeddings,
        assignments,
        pca_components=pca_components,
        min_unique_answer_texts=min_unique_answer_texts,
        membership_probability_threshold=membership_probability_threshold,
        merge_cosine_similarity_threshold=merge_cosine_similarity_threshold,
    )
    vectors_by_processing_id = {
        processing_answer.processing_id: embeddings.vectors[index]
        for index, processing_answer in enumerate(dataset.processing_answers)
    }
    unassigned_ids = set(assignments.unassigned_answer_ids)
    grouped = _unassigned_processing_answers(dataset.processing_answers, unassigned_ids)

    reductions: list[DiscoveryReduction] = []
    points: list[DiscoveryPointResult] = []
    proposed_clusters: list[DiscoveredCluster] = []
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
        reduced_vectors = PCA(
            n_components=effective_components,
            svd_solver="randomized",
            random_state=42,
            whiten=False,
        ).fit_transform(question_vectors)
        reductions.append(
            DiscoveryReduction(
                question_id=question_id,
                processing_ids=tuple(item.processing_id for item in question_answers),
                requested_components=pca_components,
                effective_components=effective_components,
                reduced_vectors=reduced_vectors,
            )
        )
        labels, probabilities = _cluster(reduced_vectors)
        question_points, question_clusters = _classify_question(
            question_id,
            question_answers,
            labels,
            probabilities,
            membership_probability_threshold=membership_probability_threshold,
            min_unique_answer_texts=min_unique_answer_texts,
        )
        points.extend(question_points)
        proposed_clusters.extend(question_clusters)

    ordered_clusters = tuple(
        sorted(
            proposed_clusters,
            key=lambda cluster: (cluster.question_id, cluster.raw_cluster_label),
        )
    )
    merge_suggestions = _merge_suggestions(
        ordered_clusters,
        vectors_by_processing_id,
        merge_cosine_similarity_threshold=merge_cosine_similarity_threshold,
    )
    point_by_processing_id = {point.processing_id: point for point in points}
    ordered_points = tuple(
        point_by_processing_id[item.processing_id]
        for item in dataset.processing_answers
        if item.processing_id in point_by_processing_id
    )
    unresolved_answer_ids = tuple(
        answer_id
        for point in ordered_points
        if point.status != "accepted_cluster"
        for answer_id in point.answer_ids
    )
    return CategoryDiscoveryResult(
        reductions=tuple(reductions),
        points=ordered_points,
        proposed_clusters=ordered_clusters,
        unresolved_answer_ids=unresolved_answer_ids,
        merge_suggestions=merge_suggestions,
    )


def _validate_inputs(
    dataset: WorkbookDataset,
    embeddings: EmbeddingResult,
    assignments: ExistingChoiceAssignmentResult,
    *,
    pca_components: int,
    min_unique_answer_texts: int,
    membership_probability_threshold: float,
    merge_cosine_similarity_threshold: float,
) -> None:
    expected_shape = (len(dataset.processing_answers), DIMENSIONS)
    if embeddings.shape != expected_shape or embeddings.vectors.shape != expected_shape:
        raise CategoryDiscoveryError(
            "embedding result is not aligned with processing answers: "
            f"expected shape {expected_shape}, got {embeddings.shape}"
        )
    if embeddings.vectors.dtype != np.float32:
        raise CategoryDiscoveryError("embedding result vectors must be float32")
    if not np.isfinite(embeddings.vectors).all():
        raise CategoryDiscoveryError("embedding result vectors must be finite")
    _validate_row_map_alignment(dataset.processing_answers, embeddings.row_map)
    if (
        not isinstance(pca_components, int)
        or isinstance(pca_components, bool)
        or pca_components < 1
    ):
        raise CategoryDiscoveryError("pca_components must be a positive integer")
    if (
        not isinstance(min_unique_answer_texts, int)
        or isinstance(min_unique_answer_texts, bool)
        or min_unique_answer_texts < 3
    ):
        raise CategoryDiscoveryError(
            "min_unique_answer_texts must be an integer at least 3"
        )
    for name, value in (
        ("membership_probability_threshold", membership_probability_threshold),
        ("merge_cosine_similarity_threshold", merge_cosine_similarity_threshold),
    ):
        if isinstance(value, bool) or not np.isfinite(value) or not 0.0 <= value <= 1.0:
            raise CategoryDiscoveryError(
                f"{name} must be a finite number in [0.0, 1.0]"
            )

    known_answer_ids = {answer.answer_id for answer in dataset.answers}
    unknown = sorted(set(assignments.unassigned_answer_ids) - known_answer_ids)
    if unknown:
        raise CategoryDiscoveryError(
            "existing-choice result references unknown unassigned answer ID(s): "
            + ", ".join(unknown)
        )


def _validate_row_map_alignment(
    processing_answers: tuple[ProcessingAnswerRecord, ...],
    row_map: tuple[dict[str, object], ...],
) -> None:
    if len(row_map) != len(processing_answers):
        raise CategoryDiscoveryError(
            "embedding row map is not aligned with processing answers: "
            f"expected {len(processing_answers)} entries, got {len(row_map)}"
        )

    for row, (processing_answer, entry) in enumerate(
        zip(processing_answers, row_map, strict=True)
    ):
        expected = {
            "row": row,
            "processing_id": processing_answer.processing_id,
            "question_id": processing_answer.question_id,
            "text": processing_answer.text,
            "answer_ids": list(processing_answer.answer_ids),
        }
        if not isinstance(entry, dict) or any(
            entry.get(key) != value for key, value in expected.items()
        ):
            raise CategoryDiscoveryError(
                "embedding row map entry "
                f"{row} does not match processing answer "
                f"'{processing_answer.processing_id}'"
            )


def _unassigned_processing_answers(
    processing_answers: tuple[ProcessingAnswerRecord, ...],
    unassigned_ids: set[str],
) -> dict[str, list[ProcessingAnswerRecord]]:
    grouped: dict[str, list[ProcessingAnswerRecord]] = defaultdict(list)
    for processing_answer in processing_answers:
        member_ids = set(processing_answer.answer_ids)
        selected_ids = member_ids & unassigned_ids
        if not selected_ids:
            continue
        if selected_ids != member_ids:
            raise CategoryDiscoveryError(
                "existing-choice result splits duplicate processing answer "
                f"'{processing_answer.processing_id}' across assigned and unassigned rows"
            )
        grouped[processing_answer.question_id].append(processing_answer)
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


def _cluster(reduced_vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    try:
        clustering = HDBSCAN(
            min_cluster_size=3,
            min_samples=None,
            metric="euclidean",
            cluster_selection_method="eom",
            cluster_selection_epsilon=0.0,
            allow_single_cluster=True,
        ).fit(reduced_vectors)
    except Exception as exc:
        raise CategoryDiscoveryError("HDBSCAN clustering failed") from exc
    labels = np.asarray(clustering.labels_)
    probabilities = np.asarray(clustering.probabilities_, dtype=float)
    if labels.shape != (len(reduced_vectors),) or probabilities.shape != (
        len(reduced_vectors),
    ):
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
    provisional: list[DiscoveryPointResult] = []
    for item, raw_label, probability in zip(
        processing_answers, labels, probabilities, strict=True
    ):
        label = int(raw_label)
        score = float(probability)
        if label == -1:
            provisional.append(_point(item, label, score, status="noise"))
        elif score < membership_probability_threshold:
            provisional.append(_point(item, label, score, status="low_probability"))
        else:
            accepted_by_label[label].append(item)

    clusters: list[DiscoveredCluster] = []
    statuses_by_processing_id: dict[str, DiscoveryPointResult] = {
        point.processing_id: point for point in provisional
    }
    for label in sorted(accepted_by_label):
        members = accepted_by_label[label]
        if len(members) < min_unique_answer_texts:
            for item in members:
                statuses_by_processing_id[item.processing_id] = _point(
                    item,
                    label,
                    _probability_for(item, processing_answers, probabilities),
                    status="rejected_cluster",
                )
            continue
        cluster_id = _cluster_id(question_id, label)
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
            statuses_by_processing_id[item.processing_id] = _point(
                item,
                label,
                _probability_for(item, processing_answers, probabilities),
                status="accepted_cluster",
                cluster_id=cluster_id,
            )
    return (
        [statuses_by_processing_id[item.processing_id] for item in processing_answers],
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


def _probability_for(
    item: ProcessingAnswerRecord,
    processing_answers: list[ProcessingAnswerRecord],
    probabilities: np.ndarray,
) -> float:
    index = processing_answers.index(item)
    return float(probabilities[index])


def _cluster_id(question_id: str, raw_cluster_label: int) -> str:
    return f"{question_id}:cluster:{raw_cluster_label}"


def _merge_suggestions(
    clusters: tuple[DiscoveredCluster, ...],
    vectors_by_processing_id: dict[str, np.ndarray],
    *,
    merge_cosine_similarity_threshold: float,
) -> tuple[ClusterMergeSuggestion, ...]:
    by_question: dict[str, list[DiscoveredCluster]] = defaultdict(list)
    for cluster in clusters:
        by_question[cluster.question_id].append(cluster)

    suggestions: list[ClusterMergeSuggestion] = []
    for question_id in sorted(by_question):
        question_clusters = sorted(
            by_question[question_id], key=lambda cluster: cluster.raw_cluster_label
        )
        for first_index, first in enumerate(question_clusters):
            first_centroid = _centroid(first, vectors_by_processing_id)
            for second in question_clusters[first_index + 1 :]:
                similarity = _cosine_similarity(
                    first_centroid, _centroid(second, vectors_by_processing_id)
                )
                if similarity >= merge_cosine_similarity_threshold:
                    suggestions.append(
                        ClusterMergeSuggestion(
                            question_id=question_id,
                            first_cluster_id=first.cluster_id,
                            second_cluster_id=second.cluster_id,
                            cosine_similarity=similarity,
                            first_processing_ids=first.processing_ids,
                            second_processing_ids=second.processing_ids,
                        )
                    )
    return tuple(suggestions)


def _centroid(
    cluster: DiscoveredCluster, vectors_by_processing_id: dict[str, np.ndarray]
) -> np.ndarray:
    centroid = np.mean(
        np.stack([vectors_by_processing_id[item] for item in cluster.processing_ids]),
        axis=0,
    )
    if not np.isfinite(centroid).all():
        raise CategoryDiscoveryError(
            f"cluster '{cluster.cluster_id}' has a non-finite original-space centroid"
        )
    if float(np.linalg.norm(centroid)) == 0.0:
        raise CategoryDiscoveryError(
            f"cluster '{cluster.cluster_id}' has a zero original-space centroid"
        )
    return centroid


def _cosine_similarity(first: np.ndarray, second: np.ndarray) -> float:
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if not np.isfinite(denominator) or denominator == 0.0:
        raise CategoryDiscoveryError(
            "cluster centroids must have finite non-zero norms"
        )
    similarity = float(np.dot(first, second) / denominator)
    if not np.isfinite(similarity):
        raise CategoryDiscoveryError("cluster centroid cosine similarity is not finite")
    return similarity
