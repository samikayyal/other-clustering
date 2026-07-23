"""Validated Nebius embeddings and exact-text cache."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from .domain import AnswerRecord, ProcessingAnswerRecord, WorkbookDataset
from .errors import EmbeddingError

ENDPOINT = "https://api.tokenfactory.nebius.com/v1/embeddings"
MODEL = "Qwen/Qwen3-Embedding-8B"
DIMENSIONS = 4096
BATCH_SIZE = 32
TIMEOUT_SECONDS = 120.0
INSTRUCTION_POLICY = "none"
CACHE_SCHEMA_VERSION = 1
NORM_RTOL = 1e-5
NORM_ATOL = 1e-6

_VECTOR_VALIDATION = {
    "finite": True,
    "unit_norm": {"rtol": NORM_RTOL, "atol": NORM_ATOL},
    "application_renormalization": False,
}


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """In-memory vectors and source mappings for the active analysis run."""

    vectors: np.ndarray
    row_map: tuple[dict[str, object], ...]
    shape: tuple[int, int]


def embed_dataset(
    dataset: WorkbookDataset,
    *,
    api_key: str | None,
    cache_root: str | Path = "embedding_cache",
    client: Any | None = None,
) -> EmbeddingResult:
    """Embed canonical answers and retain aligned vectors for this process only."""

    cache_directory = Path(cache_root).resolve()
    vectors = _resolve_vectors(
        dataset.processing_answers,
        api_key=api_key,
        cache_root=cache_directory,
        client=client,
    )
    vector_matrix = (
        np.stack(vectors).astype(np.float32, copy=False)
        if vectors
        else np.empty((0, DIMENSIONS), dtype=np.float32)
    )
    return EmbeddingResult(
        vectors=vector_matrix,
        row_map=tuple(_row_map_entries(dataset)),
        shape=vector_matrix.shape,
    )


def _resolve_vectors(
    processing_answers: tuple[ProcessingAnswerRecord, ...],
    *,
    api_key: str | None,
    cache_root: Path,
    client: Any | None,
) -> list[np.ndarray]:
    vectors_by_key: dict[str, np.ndarray] = {}
    missing: list[tuple[str, str]] = []

    for answer in processing_answers:
        cache_key = _cache_key(answer.text)
        if cache_key in vectors_by_key:
            continue
        cache_path = _cache_path(cache_root, cache_key)
        if cache_path.exists():
            vectors_by_key[cache_key] = _read_cache(
                cache_path, cache_key=cache_key, text=answer.text
            )
        else:
            missing.append((cache_key, answer.text))

    if missing:
        if api_key is None or not api_key.strip():
            raise EmbeddingError(
                "NEBIUS_API_KEY is required for answers that are not in the embedding cache"
            )
        if client is None:
            try:
                with httpx.Client(timeout=TIMEOUT_SECONDS) as owned_client:
                    _fetch_missing(
                        missing,
                        api_key=api_key,
                        cache_root=cache_root,
                        client=owned_client,
                        vectors_by_key=vectors_by_key,
                    )
            except httpx.RequestError as exc:
                raise EmbeddingError(f"Nebius embedding request failed: {exc}") from exc
        else:
            _fetch_missing(
                missing,
                api_key=api_key,
                cache_root=cache_root,
                client=client,
                vectors_by_key=vectors_by_key,
            )

    return [vectors_by_key[_cache_key(answer.text)] for answer in processing_answers]


def _fetch_missing(
    missing: list[tuple[str, str]],
    *,
    api_key: str,
    cache_root: Path,
    client: Any,
    vectors_by_key: dict[str, np.ndarray],
) -> None:
    for offset in range(0, len(missing), BATCH_SIZE):
        batch = missing[offset : offset + BATCH_SIZE]
        texts = [text for _, text in batch]
        try:
            response = client.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": MODEL,
                    "input": texts,
                    "encoding_format": "float",
                    "dimensions": DIMENSIONS,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise EmbeddingError(
                f"Nebius embedding request returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise EmbeddingError(f"Nebius embedding request failed: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise EmbeddingError(
                "Nebius embedding response was not valid JSON"
            ) from exc

        vectors = _parse_response(payload, requested_count=len(batch))
        for (cache_key, text), vector in zip(batch, vectors, strict=True):
            _write_cache(
                _cache_path(cache_root, cache_key),
                cache_key=cache_key,
                text=text,
                vector=vector,
            )
            vectors_by_key[cache_key] = vector


def _parse_response(payload: object, *, requested_count: int) -> list[np.ndarray]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise EmbeddingError("Nebius embedding response must contain a data list")

    indexed_vectors: dict[int, np.ndarray] = {}
    for position, item in enumerate(payload["data"]):
        if not isinstance(item, dict):
            raise EmbeddingError(
                f"Nebius embedding response data item {position} must be an object"
            )
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise EmbeddingError(
                f"Nebius embedding response data item {position} has an invalid index"
            )
        if index in indexed_vectors:
            raise EmbeddingError(
                f"Nebius embedding response contains duplicate index {index}"
            )
        indexed_vectors[index] = _validated_vector(
            item.get("embedding"), context=f"response index {index}"
        )

    expected = set(range(requested_count))
    actual = set(indexed_vectors)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing indices {missing}")
        if unexpected:
            details.append(f"unexpected indices {unexpected}")
        raise EmbeddingError(
            "Nebius embedding response indices do not match the request: "
            + ", ".join(details)
        )
    return [indexed_vectors[index] for index in range(requested_count)]


def _validated_vector(value: object, *, context: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != DIMENSIONS:
        length = len(value) if isinstance(value, list) else "non-list"
        raise EmbeddingError(
            f"{context} embedding must contain {DIMENSIONS} values; got {length}"
        )

    numeric: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise EmbeddingError(f"{context} embedding value {index} must be numeric")
        number = float(item)
        if not math.isfinite(number):
            raise EmbeddingError(f"{context} embedding value {index} must be finite")
        numeric.append(number)

    with np.errstate(over="ignore", invalid="ignore"):
        vector = np.asarray(numeric, dtype=np.float32)
    if not np.isfinite(vector).all():
        raise EmbeddingError(
            f"{context} embedding is not finite after float32 conversion"
        )
    norm = float(np.linalg.norm(vector))
    if not np.isclose(norm, 1.0, rtol=NORM_RTOL, atol=NORM_ATOL):
        raise EmbeddingError(
            f"{context} embedding must be unit length; got L2 norm {norm:.9g}"
        )
    return vector


def _cache_identity(text: str) -> dict[str, object]:
    return {
        "text": text,
        "endpoint": ENDPOINT,
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "instruction_policy": INSTRUCTION_POLICY,
        "vector_validation": _VECTOR_VALIDATION,
    }


def _cache_key(text: str) -> str:
    return hashlib.sha256(_canonical_json(_cache_identity(text))).hexdigest()


def _cache_path(cache_root: Path, cache_key: str) -> Path:
    return cache_root / cache_key[:2] / f"{cache_key}.json"


def _read_cache(path: Path, *, cache_key: str, text: str) -> np.ndarray:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EmbeddingError(
            f"could not read embedding cache entry '{path}': {exc}"
        ) from exc

    expected = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_key": cache_key,
        **_cache_identity(text),
    }
    if not isinstance(payload, dict) or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise EmbeddingError(
            f"embedding cache entry is incompatible with the current contract: '{path}'"
        )
    return _validated_vector(payload.get("vector"), context=f"cache entry '{path}'")


def _write_cache(path: Path, *, cache_key: str, text: str, vector: np.ndarray) -> None:
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_key": cache_key,
        **_cache_identity(text),
        "vector": vector.tolist(),
    }
    _atomic_write_json(path, payload)


def _row_map_entries(dataset: WorkbookDataset) -> list[dict[str, object]]:
    answers_by_id = {answer.answer_id: answer for answer in dataset.answers}
    entries: list[dict[str, object]] = []
    for row, processing_answer in enumerate(dataset.processing_answers):
        source_locations = [
            _source_location(answers_by_id, answer_id)
            for answer_id in processing_answer.answer_ids
        ]
        entries.append(
            {
                "row": row,
                "processing_id": processing_answer.processing_id,
                "question_id": processing_answer.question_id,
                "text": processing_answer.text,
                "answer_ids": list(processing_answer.answer_ids),
                "source_locations": source_locations,
            }
        )
    return entries


def _source_location(
    answers_by_id: dict[str, AnswerRecord], answer_id: str
) -> dict[str, object]:
    try:
        answer = answers_by_id[answer_id]
    except KeyError as exc:
        raise EmbeddingError(
            f"processing answer references unknown row-level answer ID '{answer_id}'"
        ) from exc
    location = answer.source_cell
    return {
        "answer_id": answer.answer_id,
        "respondent_key": answer.respondent_key,
        "sheet": location.sheet,
        "row": location.row,
        "column": location.column,
        "coordinate": location.coordinate,
    }


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(
                    payload,
                    output,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError as exc:
        raise EmbeddingError(
            f"could not write embedding cache entry '{path}': {exc}"
        ) from exc


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
