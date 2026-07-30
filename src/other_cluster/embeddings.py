"""Validated Nebius embeddings and exact-text SQLite cache."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from hashlib import sha256
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
CACHE_SCHEMA_VERSION = 2
NORM_RTOL = 1e-5
NORM_ATOL = 1e-6
DATABASE_NAME = "cache.sqlite3"

EMBEDDING_CONTRACT = sha256(
    f"{ENDPOINT}|{MODEL}|{DIMENSIONS}|{INSTRUCTION_POLICY}|{NORM_RTOL}|{NORM_ATOL}|no-renormalization".encode()
).hexdigest()
_TABLE_COLUMNS = ("text", "embedding_contract", "vector")
_EXPECTED_TABLE_INFO = (
    ("text", "TEXT", 1, 1),
    ("embedding_contract", "TEXT", 1, 2),
    ("vector", "BLOB", 1, 0),
)
_CREATE_TABLE = """
CREATE TABLE embeddings (
    text TEXT NOT NULL,
    embedding_contract TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (text, embedding_contract)
)
"""
_CREATE_METADATA = "CREATE TABLE cache_metadata (embedding_contract TEXT NOT NULL)"
_SELECT_VECTOR = "SELECT embedding_contract, vector FROM embeddings WHERE text = ? AND embedding_contract = ?"
_UPSERT_VECTORS = f"""
INSERT INTO embeddings ({", ".join(_TABLE_COLUMNS)})
VALUES ({", ".join("?" for _ in _TABLE_COLUMNS)})
ON CONFLICT (text, embedding_contract)
DO UPDATE SET vector = excluded.vector
"""


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
    progress: Callable[[str], None] | None = None,
) -> EmbeddingResult:
    """Embed canonical answers and retain aligned vectors for this process only."""

    if progress is not None:
        progress(
            f"embedding: starting; canonical_answers={len(dataset.processing_answers)}"
        )
    cache_path = Path(cache_root).resolve() / DATABASE_NAME
    vectors = _resolve_vectors(
        dataset.processing_answers,
        api_key=api_key,
        cache_path=cache_path,
        client=client,
        progress=progress,
    )
    vector_matrix = (
        np.stack(vectors).astype(np.float32, copy=False)
        if vectors
        else np.empty((0, DIMENSIONS), dtype=np.float32)
    )
    result = EmbeddingResult(
        vectors=vector_matrix,
        row_map=tuple(_row_map_entries(dataset)),
        shape=vector_matrix.shape,
    )
    if progress is not None:
        progress(f"embedding: complete; vectors={result.shape[0]}x{result.shape[1]}")
    return result


def _resolve_vectors(
    processing_answers: tuple[ProcessingAnswerRecord, ...],
    *,
    api_key: str | None,
    cache_path: Path,
    client: Any | None,
    progress: Callable[[str], None] | None,
) -> list[np.ndarray]:
    if not processing_answers:
        if progress is not None:
            progress("embedding: no canonical answers; cache and provider skipped")
        return []

    vectors_by_text: dict[str, np.ndarray] = {}
    missing: list[str] = []
    database = _open_existing_database(cache_path)
    try:
        for answer in processing_answers:
            if answer.text in vectors_by_text or answer.text in missing:
                continue
            if database is None:
                missing.append(answer.text)
                continue
            vector = _read_vector(database, answer.text)
            if vector is None:
                missing.append(answer.text)
            else:
                vectors_by_text[answer.text] = vector
    finally:
        if database is not None:
            database.close()

    if progress is not None:
        progress(
            "embedding: cache lookup complete; "
            f"unique_texts={len(vectors_by_text) + len(missing)}; "
            f"cache_hits={len(vectors_by_text)}; cache_misses={len(missing)}"
        )

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
                        cache_path=cache_path,
                        client=owned_client,
                        vectors_by_text=vectors_by_text,
                        cached_count=len(vectors_by_text),
                        progress=progress,
                    )
            except httpx.RequestError as exc:
                raise EmbeddingError(f"Nebius embedding request failed: {exc}") from exc
        else:
            _fetch_missing(
                missing,
                api_key=api_key,
                cache_path=cache_path,
                client=client,
                vectors_by_text=vectors_by_text,
                cached_count=len(vectors_by_text),
                progress=progress,
            )

    return [vectors_by_text[answer.text] for answer in processing_answers]


def _fetch_missing(
    missing: list[str],
    *,
    api_key: str,
    cache_path: Path,
    client: Any,
    vectors_by_text: dict[str, np.ndarray],
    cached_count: int,
    progress: Callable[[str], None] | None,
) -> None:
    total_batches = (len(missing) + BATCH_SIZE - 1) // BATCH_SIZE
    total_unique = cached_count + len(missing)
    for batch_index, offset in enumerate(range(0, len(missing), BATCH_SIZE), start=1):
        texts = missing[offset : offset + BATCH_SIZE]
        if progress is not None:
            progress(
                "embedding: requesting provider batch "
                f"{batch_index}/{total_batches}; items={len(texts)}; "
                f"ready={cached_count + offset}/{total_unique}"
            )
        vectors = _fetch_batch(texts, api_key=api_key, client=client)
        _persist_batch(cache_path, texts=texts, vectors=vectors)
        vectors_by_text.update(zip(texts, vectors, strict=True))
        if progress is not None:
            progress(
                "embedding: provider batch complete; "
                f"batch={batch_index}/{total_batches}; "
                f"fetched={offset + len(texts)}/{len(missing)}; "
                f"ready={cached_count + offset + len(texts)}/{total_unique}"
            )


def _fetch_batch(texts: list[str], *, api_key: str, client: Any) -> list[np.ndarray]:
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
        raise EmbeddingError("Nebius embedding response was not valid JSON") from exc
    return _parse_response(payload, requested_count=len(texts))


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
    return _validate_vector_array(vector, context=context)


def _validate_vector_array(vector: np.ndarray, *, context: str) -> np.ndarray:
    if vector.shape != (DIMENSIONS,):
        raise EmbeddingError(
            f"{context} embedding must contain {DIMENSIONS} values; got {vector.size}"
        )
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


def _open_existing_database(cache_path: Path) -> sqlite3.Connection | None:
    if not cache_path.exists():
        return None
    return _open_connection(cache_path, create=False)


def _open_connection(cache_path: Path, *, create: bool) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        if create:
            connection = sqlite3.connect(cache_path)
        else:
            connection = sqlite3.connect(f"{cache_path.as_uri()}?mode=rw", uri=True)
        _configure_connection(connection, cache_path)
        if create and connection.execute("PRAGMA user_version").fetchone()[0] == 0:
            _create_schema(connection, cache_path)
        else:
            _validate_schema(connection, cache_path)
        return connection
    except EmbeddingError:
        if connection is not None:
            connection.close()
        raise
    except (sqlite3.Error, OSError, ValueError) as exc:
        if connection is not None:
            connection.close()
        raise EmbeddingError(
            f"could not open compatible embedding cache database '{cache_path}': {exc}"
        ) from exc


def _configure_connection(connection: sqlite3.Connection, cache_path: Path) -> None:
    connection.execute("PRAGMA busy_timeout = 5000")
    journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
    if journal_mode is None or str(journal_mode[0]).lower() != "wal":
        actual = "missing" if journal_mode is None else journal_mode[0]
        raise EmbeddingError(
            f"embedding cache database '{cache_path}' did not accept WAL mode; got {actual!r}"
        )
    connection.execute("PRAGMA synchronous = FULL")


def _create_schema(connection: sqlite3.Connection, cache_path: Path) -> None:
    try:
        connection.execute("BEGIN")
        connection.execute(_CREATE_TABLE)
        connection.execute(_CREATE_METADATA)
        connection.execute(
            "INSERT INTO cache_metadata VALUES (?)", (EMBEDDING_CONTRACT,)
        )
        connection.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION}")
        connection.commit()
    except sqlite3.Error as exc:
        connection.rollback()
        raise EmbeddingError(
            f"could not initialize embedding cache database '{cache_path}': {exc}"
        ) from exc
    _validate_schema(connection, cache_path)


def _validate_schema(connection: sqlite3.Connection, cache_path: Path) -> None:
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
        table_info = connection.execute("PRAGMA table_info(embeddings)").fetchall()
        metadata = connection.execute(
            "SELECT embedding_contract FROM cache_metadata"
        ).fetchall()
    except sqlite3.Error as exc:
        raise EmbeddingError(
            f"could not inspect embedding cache database '{cache_path}': {exc}"
        ) from exc
    if version is None or version[0] != CACHE_SCHEMA_VERSION:
        actual = "missing" if version is None else version[0]
        raise EmbeddingError(
            f"embedding cache database '{cache_path}' uses contract/schema {actual!r}; delete embedding_cache and rebuild it"
        )
    actual_columns = tuple(
        (row[1], str(row[2]).upper(), row[3], row[5]) for row in table_info
    )
    if actual_columns != _EXPECTED_TABLE_INFO:
        raise EmbeddingError(
            f"embedding cache database '{cache_path}' has an incompatible contract; delete embedding_cache and rebuild it"
        )
    if metadata != [(EMBEDDING_CONTRACT,)]:
        raise EmbeddingError(
            f"embedding cache database '{cache_path}' has an incompatible contract; delete embedding_cache and rebuild it"
        )


def _read_vector(connection: sqlite3.Connection, text: str) -> np.ndarray | None:
    try:
        row = connection.execute(_SELECT_VECTOR, (text, EMBEDDING_CONTRACT)).fetchone()
    except sqlite3.Error as exc:
        raise EmbeddingError(f"could not read embedding cache entry: {exc}") from exc
    if row is None:
        return None
    if row[0] != EMBEDDING_CONTRACT:
        raise EmbeddingError("embedding cache entry identity does not match its lookup")
    blob = row[1]
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise EmbeddingError("embedding cache entry vector must be a BLOB")
    raw_vector = bytes(blob)
    expected_size = DIMENSIONS * np.dtype("<f4").itemsize
    if len(raw_vector) != expected_size:
        raise EmbeddingError(
            "embedding cache entry vector has invalid BLOB length; "
            f"expected {expected_size}, got {len(raw_vector)}"
        )
    vector = np.frombuffer(raw_vector, dtype="<f4").copy()
    return _validate_vector_array(vector, context="embedding cache entry")


def _persist_batch(
    cache_path: Path, *, texts: list[str], vectors: list[np.ndarray]
) -> None:
    connection: sqlite3.Connection | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        connection = _open_connection(cache_path, create=True)
        values = [
            (text, EMBEDDING_CONTRACT, _serialize_vector(vector))
            for text, vector in zip(texts, vectors, strict=True)
        ]
        connection.execute("BEGIN")
        connection.executemany(_UPSERT_VECTORS, values)
        connection.commit()
    except EmbeddingError:
        if connection is not None:
            connection.rollback()
        raise
    except (sqlite3.Error, OSError, ValueError) as exc:
        if connection is not None:
            connection.rollback()
        raise EmbeddingError(f"could not write embedding cache batch: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _serialize_vector(vector: np.ndarray) -> bytes:
    return np.ascontiguousarray(vector, dtype=np.dtype("<f4")).tobytes(order="C")


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
