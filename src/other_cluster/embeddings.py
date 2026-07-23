"""Validated Nebius embeddings, exact-text cache, and per-dataset artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
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
DTYPE = "float32"
INSTRUCTION_POLICY = "none"
SCHEMA_VERSION = 1
NORM_RTOL = 1e-5
NORM_ATOL = 1e-6

_VECTOR_VALIDATION = {
    "finite": True,
    "unit_norm": {"rtol": NORM_RTOL, "atol": NORM_ATOL},
    "application_renormalization": False,
}


@dataclass(frozen=True, slots=True)
class EmbeddingArtifacts:
    """Completed vector artifacts aligned to a workbook dataset."""

    directory: Path
    embeddings_path: Path
    row_map_path: Path
    dataset_fingerprint: str
    shape: tuple[int, int]
    reused: bool


def embed_dataset(
    dataset: WorkbookDataset,
    *,
    api_key: str | None,
    artifact_root: str | Path = "embedding_artifacts",
    cache_root: str | Path = "embedding_cache",
    client: Any | None = None,
) -> EmbeddingArtifacts:
    """Embed canonical answers and atomically publish validated run artifacts."""

    source_sha256 = _file_sha256(dataset.source_path)
    entries = _row_map_entries(dataset)
    fingerprint = _dataset_fingerprint(source_sha256, entries)
    artifact_directory = Path(artifact_root).resolve() / fingerprint
    expected_row_map = _row_map_document(
        source_sha256=source_sha256,
        dataset_fingerprint=fingerprint,
        entries=entries,
    )

    if artifact_directory.exists():
        return _reuse_artifacts(artifact_directory, expected_row_map)

    cache_directory = Path(cache_root).resolve()
    vectors = _resolve_vectors(
        dataset.processing_answers,
        api_key=api_key,
        cache_root=cache_directory,
        client=client,
    )
    return _publish_artifacts(
        artifact_directory=artifact_directory,
        expected_row_map=expected_row_map,
        vectors=vectors,
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
        "schema_version": SCHEMA_VERSION,
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
        "schema_version": SCHEMA_VERSION,
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


def _dataset_fingerprint(source_sha256: str, entries: list[dict[str, object]]) -> str:
    identity = {
        "schema_version": SCHEMA_VERSION,
        "source_workbook_sha256": source_sha256,
        "entries": entries,
    }
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def _row_map_document(
    *,
    source_sha256: str,
    dataset_fingerprint: str,
    entries: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_workbook_sha256": source_sha256,
        "dataset_fingerprint": dataset_fingerprint,
        "endpoint": ENDPOINT,
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "dtype": DTYPE,
        "instruction_policy": INSTRUCTION_POLICY,
        "vector_validation": _VECTOR_VALIDATION,
        "shape": [len(entries), DIMENSIONS],
        "entries": entries,
    }


def _publish_artifacts(
    *,
    artifact_directory: Path,
    expected_row_map: dict[str, object],
    vectors: list[np.ndarray],
) -> EmbeddingArtifacts:
    temporary_directory: Path | None = None
    try:
        artifact_directory.parent.mkdir(parents=True, exist_ok=True)
        temporary_directory = Path(
            tempfile.mkdtemp(
                prefix=f".{artifact_directory.name}.",
                dir=artifact_directory.parent,
            )
        )
        embeddings_path = temporary_directory / "embeddings.f32"
        shape = tuple(expected_row_map["shape"])
        if vectors:
            memory_map = np.memmap(
                embeddings_path, dtype=np.float32, mode="w+", shape=shape
            )
            for row, vector in enumerate(vectors):
                memory_map[row] = vector
            memory_map.flush()
            del memory_map
        else:
            embeddings_path.touch()

        row_map_path = temporary_directory / "row-map.json"
        _write_json_file(row_map_path, expected_row_map)
        _validate_artifact_files(
            embeddings_path=embeddings_path,
            row_map=expected_row_map,
        )
        try:
            os.replace(temporary_directory, artifact_directory)
        except FileExistsError:
            return _reuse_artifacts(artifact_directory, expected_row_map)
    except EmbeddingError:
        raise
    except OSError as exc:
        raise EmbeddingError(f"could not persist embedding artifacts: {exc}") from exc
    finally:
        if temporary_directory is not None and temporary_directory.exists():
            shutil.rmtree(temporary_directory, ignore_errors=True)

    return _artifact_result(artifact_directory, expected_row_map, reused=False)


def _reuse_artifacts(
    artifact_directory: Path, expected_row_map: dict[str, object]
) -> EmbeddingArtifacts:
    if not artifact_directory.is_dir():
        raise EmbeddingError(
            f"embedding artifact collision is not a directory: '{artifact_directory}'"
        )
    row_map_path = artifact_directory / "row-map.json"
    embeddings_path = artifact_directory / "embeddings.f32"
    try:
        existing_row_map = json.loads(row_map_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EmbeddingError(
            f"could not read existing embedding artifact '{row_map_path}': {exc}"
        ) from exc
    if existing_row_map != expected_row_map:
        raise EmbeddingError(
            f"incompatible embedding artifact collision at '{artifact_directory}'"
        )
    _validate_artifact_files(
        embeddings_path=embeddings_path,
        row_map=existing_row_map,
    )
    return _artifact_result(artifact_directory, expected_row_map, reused=True)


def _validate_artifact_files(
    *, embeddings_path: Path, row_map: dict[str, object]
) -> None:
    shape_value = row_map.get("shape")
    if (
        not isinstance(shape_value, list)
        or len(shape_value) != 2
        or shape_value[1] != DIMENSIONS
        or isinstance(shape_value[0], bool)
        or not isinstance(shape_value[0], int)
        or shape_value[0] < 0
    ):
        raise EmbeddingError("embedding row map contains an invalid shape")
    shape = (shape_value[0], DIMENSIONS)
    expected_bytes = shape[0] * DIMENSIONS * np.dtype(np.float32).itemsize
    try:
        actual_bytes = embeddings_path.stat().st_size
    except OSError as exc:
        raise EmbeddingError(
            f"could not inspect embedding memory map '{embeddings_path}': {exc}"
        ) from exc
    if actual_bytes != expected_bytes:
        raise EmbeddingError(
            f"embedding memory map size mismatch: expected {expected_bytes} bytes, "
            f"got {actual_bytes}"
        )
    if shape[0] == 0:
        return
    try:
        memory_map = np.memmap(embeddings_path, dtype=np.float32, mode="r", shape=shape)
        finite = bool(np.isfinite(memory_map).all())
        norms = np.linalg.norm(memory_map, axis=1)
        unit = bool(np.all(np.isclose(norms, 1.0, rtol=NORM_RTOL, atol=NORM_ATOL)))
        del memory_map
    except (OSError, ValueError) as exc:
        raise EmbeddingError(
            f"could not validate embedding memory map '{embeddings_path}': {exc}"
        ) from exc
    if not finite:
        raise EmbeddingError("embedding memory map contains non-finite values")
    if not unit:
        raise EmbeddingError("embedding memory map contains a non-unit vector")


def _artifact_result(
    directory: Path, row_map: dict[str, object], *, reused: bool
) -> EmbeddingArtifacts:
    shape = row_map["shape"]
    return EmbeddingArtifacts(
        directory=directory,
        embeddings_path=directory / "embeddings.f32",
        row_map_path=directory / "row-map.json",
        dataset_fingerprint=str(row_map["dataset_fingerprint"]),
        shape=(shape[0], shape[1]),
        reused=reused,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise EmbeddingError(
            f"could not fingerprint source workbook '{path}': {exc}"
        ) from exc
    return digest.hexdigest()


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


def _write_json_file(path: Path, payload: dict[str, object]) -> None:
    try:
        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        raise EmbeddingError(
            f"could not write embedding row map '{path}': {exc}"
        ) from exc


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
