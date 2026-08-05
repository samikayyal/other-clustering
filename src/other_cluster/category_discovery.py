"""Question-scoped lexical evidence for Cluster-First V1."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .domain import (
    CategoryDiscoveryResult,
    DiscoveredCluster,
    DiscoveryPointResult,
    ProcessingAnswerRecord,
    WorkbookDataset,
)
from .errors import CategoryDiscoveryError

SVD_COMPONENTS = 50
DISTANCE_THRESHOLD = 0.9125
MIN_UNIQUE_ANSWER_TEXTS = 2
_DIACRITICS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")
_NORMALIZATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ی": "ي",
        "ک": "ك",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)


def discover_categories(
    dataset: WorkbookDataset,
    *,
    svd_components: int = SVD_COMPONENTS,
    distance_threshold: float = DISTANCE_THRESHOLD,
    min_unique_answer_texts: int = MIN_UNIQUE_ANSWER_TEXTS,
    progress: Callable[[str], None] | None = None,
) -> CategoryDiscoveryResult:
    """Discover fixed clusters from every canonical answer in every question."""

    _validate_settings(svd_components, distance_threshold, min_unique_answer_texts)
    grouped = _group_by_question(dataset.processing_answers)
    points: list[DiscoveryPointResult] = []
    proposal_clusters: list[DiscoveredCluster] = []
    question_total = len(grouped)

    if progress is not None:
        progress(
            "discovery: starting; "
            f"questions={question_total}; "
            f"canonical_answers={len(dataset.processing_answers)}"
        )

    for question_index, question_id in enumerate(sorted(grouped), start=1):
        question_answers = grouped[question_id]
        if len(question_answers) < min_unique_answer_texts:
            rare_points = _rare_points(question_answers)
            points.extend(rare_points)
            if progress is not None:
                progress(
                    "discovery: question "
                    f"{question_index}/{question_total} '{question_id}' complete; "
                    f"canonical_answers={len(question_answers)}; "
                    f"clusters=0; unresolved={len(rare_points)}; "
                    "status=rare_insufficient_distinct_texts"
                )
            continue

        features, effective_components = _text_features(
            question_answers,
            question_id=question_id,
            svd_components=svd_components,
        )
        labels, probabilities = _cluster(
            features, question_id=question_id, distance_threshold=distance_threshold
        )
        question_points, question_clusters = _classify_question(
            question_id,
            question_answers,
            labels,
            probabilities,
            min_unique_answer_texts=min_unique_answer_texts,
        )
        points.extend(question_points)
        proposal_clusters.extend(question_clusters)
        if progress is not None:
            status_counts = Counter(point.status for point in question_points)
            statuses = ",".join(
                f"{status}={status_counts[status]}" for status in sorted(status_counts)
            )
            progress(
                "discovery: question "
                f"{question_index}/{question_total} '{question_id}' complete; "
                f"canonical_answers={len(question_answers)}; "
                f"svd_components={effective_components}; "
                f"clusters={len(question_clusters)}; statuses={statuses}"
            )

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
    result = CategoryDiscoveryResult(
        points=ordered_points,
        proposed_clusters=ordered_clusters,
        unresolved_processing_ids=unresolved_processing_ids,
    )
    if progress is not None:
        status_counts = Counter(point.status for point in result.points)
        statuses = ",".join(
            f"{status}={status_counts[status]}" for status in sorted(status_counts)
        )
        progress(
            "discovery: complete; "
            f"points={len(result.points)}; "
            f"proposal_eligible_clusters={len(result.proposed_clusters)}; "
            f"unresolved={len(result.unresolved_processing_ids)}; "
            f"statuses={statuses or 'none'}"
        )
    return result


def _validate_settings(
    svd_components: int,
    distance_threshold: float,
    min_unique_answer_texts: int,
) -> None:
    if (
        not isinstance(svd_components, int)
        or isinstance(svd_components, bool)
        or svd_components < 1
    ):
        raise CategoryDiscoveryError("svd_components must be a positive integer")
    if (
        isinstance(distance_threshold, bool)
        or not np.isfinite(distance_threshold)
        or not 0.0 < distance_threshold <= 2.0
    ):
        raise CategoryDiscoveryError(
            "distance_threshold must be a finite number in (0.0, 2.0]"
        )
    if (
        not isinstance(min_unique_answer_texts, int)
        or isinstance(min_unique_answer_texts, bool)
        or min_unique_answer_texts < MIN_UNIQUE_ANSWER_TEXTS
    ):
        raise CategoryDiscoveryError(
            "min_unique_answer_texts must be an integer at least 2"
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


def _normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).translate(_NORMALIZATION)
    value = _DIACRITICS.sub("", value).replace("ـ", "")
    value = _NON_WORD.sub(" ", value).casefold()
    normalized = _SPACE.sub(" ", value).strip()
    return normalized or unicodedata.normalize("NFKC", text).casefold()


def _text_features(
    processing_answers: list[ProcessingAnswerRecord],
    *,
    question_id: str,
    svd_components: int,
) -> tuple[np.ndarray, int]:
    try:
        matrix = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 5),
            min_df=1,
            sublinear_tf=True,
            preprocessor=_normalize_text,
        ).fit_transform(item.text for item in processing_answers)
        effective_components = min(
            svd_components,
            matrix.shape[0] - 1,
            matrix.shape[1] - 1,
        )
        if effective_components >= 1:
            features = TruncatedSVD(
                n_components=effective_components, random_state=42
            ).fit_transform(matrix)
        else:
            features = matrix.toarray()
        return normalize(features), max(effective_components, 0)
    except Exception as exc:
        raise CategoryDiscoveryError(
            f"text representation failed for question '{question_id}'"
        ) from exc


def _cluster(
    features: np.ndarray, *, question_id: str, distance_threshold: float
) -> tuple[np.ndarray, np.ndarray]:
    try:
        labels = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=distance_threshold,
        ).fit_predict(features)
    except Exception as exc:
        raise CategoryDiscoveryError(
            f"agglomerative clustering failed for question '{question_id}'"
        ) from exc
    labels = np.asarray(labels)
    return labels, np.ones(len(labels), dtype=float)


def _classify_question(
    question_id: str,
    processing_answers: list[ProcessingAnswerRecord],
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
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
