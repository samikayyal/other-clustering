from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from other_cluster import embeddings
from other_cluster.embeddings import (
    BATCH_SIZE,
    CACHE_SCHEMA_VERSION,
    DATABASE_NAME,
    DIMENSIONS,
    ENDPOINT,
    INSTRUCTION_POLICY,
    MODEL,
    NORM_ATOL,
    NORM_RTOL,
    EmbeddingResult,
    embed_dataset,
)
from other_cluster.errors import EmbeddingError
from other_cluster.workbook import ingest_workbook

from ._fixtures import create_workbook


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        json_error: ValueError | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error
        self.request = httpx.Request("POST", ENDPOINT)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "provider error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected provider request")
        return self.responses.pop(0)


def _unit_vector(first: float = 1.0, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * (DIMENSIONS - 2))]


def _response(*vectors: list[float], reverse: bool = False) -> FakeResponse:
    items = [
        {"index": index, "embedding": vector} for index, vector in enumerate(vectors)
    ]
    if reverse:
        items.reverse()
    return FakeResponse({"data": items})


def _cache_path(tmp_path: Path, cache_name: str = "cache") -> Path:
    return tmp_path / cache_name / DATABASE_NAME


def _embed(
    input_path: Path,
    tmp_path: Path,
    client: FakeClient,
    *,
    cache_name: str = "cache",
    api_key: str | None = "secret",
) -> EmbeddingResult:
    return embed_dataset(
        ingest_workbook(input_path),
        api_key=api_key,
        cache_root=tmp_path / cache_name,
        client=client,
    )


def _identity(text: str) -> tuple[object, ...]:
    return (
        text,
        ENDPOINT,
        MODEL,
        DIMENSIONS,
        INSTRUCTION_POLICY,
        1,
        NORM_RTOL,
        NORM_ATOL,
        0,
    )


def _cache_connection(tmp_path: Path, cache_name: str = "cache") -> sqlite3.Connection:
    return sqlite3.connect(_cache_path(tmp_path, cache_name))


def test_original_text_request_index_mapping_row_alignment_and_sqlite_blob(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(
        tmp_path / "input.xlsx",
        answers=["لهجة أردنية", "لهجة أردنية", "English answer"],
    )
    arabic_vector = _unit_vector()
    english_vector = _unit_vector(0.6, 0.8)
    client = FakeClient([_response(arabic_vector, english_vector, reverse=True)])

    artifacts = _embed(input_path, tmp_path, client)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == ENDPOINT
    assert call["headers"] == {"Authorization": "Bearer secret"}
    assert call["json"] == {
        "model": MODEL,
        "input": ["لهجة أردنية", "English answer"],
        "encoding_format": "float",
        "dimensions": DIMENSIONS,
    }
    np.testing.assert_array_equal(
        artifacts.vectors[0], np.asarray(arabic_vector, dtype=np.float32)
    )
    np.testing.assert_array_equal(
        artifacts.vectors[1], np.asarray(english_vector, dtype=np.float32)
    )
    assert artifacts.vectors.dtype == np.float32
    assert artifacts.shape == (2, DIMENSIONS)
    assert artifacts.row_map[0]["text"] == "لهجة أردنية"
    assert artifacts.row_map[0]["answer_ids"] == ["B5_other:2", "B5_other:3"]
    assert artifacts.row_map[0]["source_locations"] == [
        {
            "answer_id": "B5_other:2",
            "respondent_key": "respondent-1",
            "sheet": "Data",
            "row": 2,
            "column": 4,
            "coordinate": "D2",
        },
        {
            "answer_id": "B5_other:3",
            "respondent_key": "respondent-2",
            "sheet": "Data",
            "row": 3,
            "column": 4,
            "coordinate": "D3",
        },
    ]

    cache_path = _cache_path(tmp_path)
    assert cache_path.is_file()
    assert not list(cache_path.parent.rglob("*.json"))
    assert not [path for path in cache_path.parent.iterdir() if path.is_dir()]
    connection = _cache_connection(tmp_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone() == (
            CACHE_SCHEMA_VERSION,
        )
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        rows = connection.execute(
            "SELECT text, endpoint, model, dimensions, instruction_policy, "
            "validation_finite, norm_rtol, norm_atol, application_renormalization, vector "
            "FROM embeddings ORDER BY text"
        ).fetchall()
    finally:
        connection.close()
    assert [tuple(row[:-1]) for row in rows] == [
        _identity("English answer"),
        _identity("لهجة أردنية"),
    ]
    assert rows[0][-1] == np.asarray(english_vector, dtype="<f4").tobytes(order="C")
    assert rows[1][-1] == np.asarray(arabic_vector, dtype="<f4").tobytes(order="C")

    configured = embeddings._open_existing_database(cache_path)
    assert configured is not None
    try:
        assert configured.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert configured.execute("PRAGMA synchronous").fetchone() == (2,)
    finally:
        configured.close()


def test_requests_are_limited_to_batches_of_32(tmp_path: Path) -> None:
    answers = [f"answer {index}" for index in range(BATCH_SIZE + 1)]
    input_path = create_workbook(tmp_path / "input.xlsx", answers=answers)
    client = FakeClient(
        [
            _response(*[_unit_vector() for _ in range(BATCH_SIZE)]),
            _response(_unit_vector(0.6, 0.8)),
        ]
    )

    artifacts = _embed(input_path, tmp_path, client)

    assert [len(call["json"]["input"]) for call in client.calls] == [32, 1]
    assert artifacts.shape == (33, DIMENSIONS)


def test_exact_text_cache_is_reused_without_an_api_key(tmp_path: Path) -> None:
    input_path = create_workbook(
        tmp_path / "input.xlsx", answers=["same text", "another text"]
    )
    first = _embed(
        input_path,
        tmp_path,
        FakeClient([_response(_unit_vector(), _unit_vector(0.6, 0.8))]),
    )

    no_calls = FakeClient([])
    second = _embed(input_path, tmp_path, no_calls, api_key=None)

    assert no_calls.calls == []
    np.testing.assert_array_equal(first.vectors, second.vectors)


def test_different_identity_rows_are_cache_misses_and_coexist(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    _embed(input_path, tmp_path, FakeClient([_response(_unit_vector())]))
    connection = _cache_connection(tmp_path)
    try:
        connection.execute("UPDATE embeddings SET model = 'another-model'")
        connection.commit()
    finally:
        connection.close()

    client = FakeClient([_response(_unit_vector(0.6, 0.8))])
    artifacts = _embed(input_path, tmp_path, client)

    assert len(client.calls) == 1
    np.testing.assert_array_equal(
        artifacts.vectors[0], np.asarray(_unit_vector(0.6, 0.8), dtype=np.float32)
    )
    connection = _cache_connection(tmp_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM embeddings").fetchone() == (2,)
    finally:
        connection.close()


def test_embedding_does_not_reread_the_source_workbook(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    dataset = ingest_workbook(input_path)
    input_path.unlink()

    artifacts = embed_dataset(
        dataset,
        api_key="secret",
        cache_root=tmp_path / "cache",
        client=FakeClient([_response(_unit_vector())]),
    )

    assert artifacts.shape == (1, DIMENSIONS)
    assert artifacts.row_map[0]["text"] == "answer"


def test_embedding_keeps_results_in_memory_without_run_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    artifacts = embed_dataset(
        ingest_workbook(input_path),
        api_key="secret",
        client=FakeClient([_response(_unit_vector())]),
    )

    assert artifacts.vectors.shape == (1, DIMENSIONS)
    assert not (tmp_path / "embedding_artifacts").exists()
    assert not list(tmp_path.rglob("*.f32"))
    assert not list(tmp_path.rglob("row-map.json"))


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"data": [{"index": 0, "embedding": [1.0]}]}, "must contain 4096 values"),
        (
            {"data": [{"index": 0, "embedding": _unit_vector(0.0, 0.0)}]},
            "must be unit length",
        ),
        (
            {
                "data": [
                    {
                        "index": 0,
                        "embedding": [float("nan"), *([0.0] * (DIMENSIONS - 1))],
                    }
                ]
            },
            "must be finite",
        ),
        (
            {
                "data": [
                    {"index": 0, "embedding": _unit_vector()},
                    {"index": 0, "embedding": _unit_vector()},
                ]
            },
            "duplicate index 0",
        ),
        ({"data": [{"index": 1, "embedding": _unit_vector()}]}, "indices do not match"),
    ],
)
def test_invalid_provider_response_stops_without_database(
    tmp_path: Path, payload: object, match: str
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    with pytest.raises(EmbeddingError, match=match):
        _embed(input_path, tmp_path, FakeClient([FakeResponse(payload)]))

    assert not _cache_path(tmp_path).exists()


def test_completed_batch_remains_committed_after_later_provider_batch_fails(
    tmp_path: Path,
) -> None:
    answers = [f"answer {index}" for index in range(BATCH_SIZE + 1)]
    input_path = create_workbook(tmp_path / "input.xlsx", answers=answers)
    client = FakeClient(
        [
            _response(*[_unit_vector() for _ in range(BATCH_SIZE)]),
            FakeResponse({"data": []}),
        ]
    )

    with pytest.raises(EmbeddingError, match="indices do not match"):
        _embed(input_path, tmp_path, client)

    connection = _cache_connection(tmp_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM embeddings").fetchone() == (
            BATCH_SIZE,
        )
    finally:
        connection.close()


def test_database_write_failure_rolls_back_entire_completed_batch(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["first", "second"])
    seed_path = create_workbook(tmp_path / "seed.xlsx", answers=["seed"])
    _embed(seed_path, tmp_path, FakeClient([_response(_unit_vector())]))
    connection = _cache_connection(tmp_path)
    try:
        connection.execute("DELETE FROM embeddings")
        connection.execute(
            "CREATE TRIGGER reject_vectors BEFORE INSERT ON embeddings "
            "BEGIN SELECT RAISE(ABORT, 'write refused'); END"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(EmbeddingError, match="write refused"):
        _embed(
            input_path,
            tmp_path,
            FakeClient([_response(_unit_vector(), _unit_vector(0.6, 0.8))]),
        )

    connection = _cache_connection(tmp_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM embeddings").fetchone() == (0,)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda connection: connection.execute("PRAGMA user_version = 99"),
            "unsupported schema version",
        ),
        (
            lambda connection: (
                connection.execute("DROP TABLE embeddings"),
                connection.execute("CREATE TABLE embeddings (text TEXT NOT NULL)"),
            ),
            "incompatible embeddings table",
        ),
    ],
)
def test_incompatible_database_stops_before_provider(
    tmp_path: Path, mutate: Any, match: str
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    _embed(input_path, tmp_path, FakeClient([_response(_unit_vector())]))
    connection = _cache_connection(tmp_path)
    try:
        mutate(connection)
        connection.commit()
    finally:
        connection.close()

    client = FakeClient([])
    with pytest.raises(EmbeddingError, match=match):
        _embed(input_path, tmp_path, client)
    assert client.calls == []


@pytest.mark.parametrize(
    ("vector", "match"),
    [
        ("not-a-blob", "must be a BLOB"),
        (b"too short", "invalid BLOB length"),
        (
            np.asarray([np.nan, *([0.0] * (DIMENSIONS - 1))], dtype="<f4").tobytes(),
            "not finite",
        ),
        (
            np.zeros(DIMENSIONS, dtype="<f4").tobytes(),
            "must be unit length",
        ),
    ],
    ids=["non-blob", "wrong-length", "non-finite", "non-unit"],
)
def test_corrupt_matched_vector_stops_without_provider(
    tmp_path: Path, vector: object, match: str
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    _embed(input_path, tmp_path, FakeClient([_response(_unit_vector())]))
    connection = _cache_connection(tmp_path)
    try:
        connection.execute("UPDATE embeddings SET vector = ?", (vector,))
        connection.commit()
    finally:
        connection.close()

    client = FakeClient([])
    with pytest.raises(EmbeddingError, match=match):
        _embed(input_path, tmp_path, client)
    assert client.calls == []


def test_corrupt_database_stops_before_provider(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    cache_path = _cache_path(tmp_path)
    cache_path.parent.mkdir()
    cache_path.write_bytes(b"not a SQLite database")

    client = FakeClient([])
    with pytest.raises(EmbeddingError, match="could not open compatible"):
        _embed(input_path, tmp_path, client)
    assert client.calls == []


def test_empty_dataset_returns_zero_rows_without_database_or_provider(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=[None])

    artifacts = _embed(input_path, tmp_path, FakeClient([]), api_key=None)

    assert artifacts.shape == (0, DIMENSIONS)
    assert artifacts.vectors.shape == (0, DIMENSIONS)
    assert artifacts.row_map == ()
    assert not _cache_path(tmp_path).exists()


def test_missing_api_key_fails_only_when_uncached_answers_need_provider(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    with pytest.raises(EmbeddingError, match="NEBIUS_API_KEY is required"):
        _embed(input_path, tmp_path, FakeClient([]), api_key=None)

    assert not _cache_path(tmp_path).exists()


def test_http_and_json_failures_do_not_create_a_database(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    with pytest.raises(EmbeddingError, match="HTTP 503"):
        _embed(
            input_path,
            tmp_path,
            FakeClient([FakeResponse({}, status_code=503)]),
        )
    assert not _cache_path(tmp_path).exists()

    with pytest.raises(EmbeddingError, match="not valid JSON"):
        _embed(
            input_path,
            tmp_path,
            FakeClient([FakeResponse({}, json_error=ValueError("bad json"))]),
        )
    assert not _cache_path(tmp_path).exists()
