from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from other_cluster.embeddings import (
    BATCH_SIZE,
    DIMENSIONS,
    ENDPOINT,
    MODEL,
    EmbeddingArtifacts,
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
                response=httpx.Response(
                    self.status_code,
                    request=self.request,
                ),
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


def _embed(
    input_path: Path,
    tmp_path: Path,
    client: FakeClient,
    *,
    artifact_name: str = "artifacts",
    cache_name: str = "cache",
    api_key: str | None = "secret",
) -> EmbeddingArtifacts:
    return embed_dataset(
        ingest_workbook(input_path),
        api_key=api_key,
        artifact_root=tmp_path / artifact_name,
        cache_root=tmp_path / cache_name,
        client=client,
    )


def test_original_text_request_index_mapping_and_row_alignment(
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

    vectors = np.memmap(
        artifacts.embeddings_path,
        dtype=np.float32,
        mode="r",
        shape=(2, DIMENSIONS),
    )
    np.testing.assert_array_equal(
        vectors[0], np.asarray(arabic_vector, dtype=np.float32)
    )
    np.testing.assert_array_equal(
        vectors[1], np.asarray(english_vector, dtype=np.float32)
    )
    assert vectors.dtype == np.float32
    del vectors

    row_map = json.loads(artifacts.row_map_path.read_text(encoding="utf-8"))
    assert row_map["shape"] == [2, DIMENSIONS]
    assert row_map["dtype"] == "float32"
    assert row_map["entries"][0]["text"] == "لهجة أردنية"
    assert row_map["entries"][0]["answer_ids"] == ["B5_other:2", "B5_other:3"]
    assert row_map["entries"][0]["source_locations"] == [
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


def test_requests_are_limited_to_batches_of_32(tmp_path: Path) -> None:
    answers = [f"answer {index}" for index in range(BATCH_SIZE + 1)]
    input_path = create_workbook(tmp_path / "input.xlsx", answers=answers)
    first_batch = _response(*[_unit_vector() for _ in range(BATCH_SIZE)])
    second_batch = _response(_unit_vector(0.6, 0.8))
    client = FakeClient([first_batch, second_batch])

    artifacts = _embed(input_path, tmp_path, client)

    assert [len(call["json"]["input"]) for call in client.calls] == [32, 1]
    assert artifacts.shape == (33, DIMENSIONS)


def test_exact_text_cache_is_reused_without_an_api_key(tmp_path: Path) -> None:
    input_path = create_workbook(
        tmp_path / "input.xlsx", answers=["same text", "another text"]
    )
    client = FakeClient([_response(_unit_vector(), _unit_vector(0.6, 0.8))])
    first = _embed(input_path, tmp_path, client)

    no_calls = FakeClient([])
    second = _embed(
        input_path,
        tmp_path,
        no_calls,
        artifact_name="second-artifacts",
        api_key=None,
    )

    assert no_calls.calls == []
    assert first.dataset_fingerprint == second.dataset_fingerprint
    first_vectors = np.memmap(
        first.embeddings_path, dtype=np.float32, mode="r", shape=first.shape
    )
    second_vectors = np.memmap(
        second.embeddings_path, dtype=np.float32, mode="r", shape=second.shape
    )
    np.testing.assert_array_equal(first_vectors, second_vectors)
    del first_vectors, second_vectors


def test_completed_artifact_is_reused_only_when_compatible(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    first = _embed(input_path, tmp_path, FakeClient([_response(_unit_vector())]))

    reused = _embed(
        input_path,
        tmp_path,
        FakeClient([]),
        api_key=None,
    )

    assert reused.directory == first.directory
    assert reused.reused is True

    row_map = json.loads(first.row_map_path.read_text(encoding="utf-8"))
    row_map["model"] = "incompatible"
    first.row_map_path.write_text(json.dumps(row_map), encoding="utf-8")
    with pytest.raises(EmbeddingError, match="incompatible embedding artifact"):
        _embed(input_path, tmp_path, FakeClient([]), api_key=None)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (
            {"data": [{"index": 0, "embedding": [1.0]}]},
            "must contain 4096 values",
        ),
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
        (
            {"data": [{"index": 1, "embedding": _unit_vector()}]},
            "indices do not match",
        ),
    ],
    ids=[
        "wrong-dimension",
        "zero-norm",
        "non-finite",
        "duplicate-index",
        "missing-and-unexpected-index",
    ],
)
def test_invalid_provider_response_stops_without_run_artifact(
    tmp_path: Path, payload: object, match: str
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    with pytest.raises(EmbeddingError, match=match):
        _embed(input_path, tmp_path, FakeClient([FakeResponse(payload)]))

    assert not (tmp_path / "artifacts").exists()


def test_valid_completed_batches_remain_cached_after_later_batch_fails(
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

    assert len(list((tmp_path / "cache").glob("*/*.json"))) == BATCH_SIZE
    assert not (tmp_path / "artifacts").exists()


def test_corrupt_cache_stops_instead_of_calling_provider(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    _embed(input_path, tmp_path, FakeClient([_response(_unit_vector())]))
    cache_path = next((tmp_path / "cache").glob("*/*.json"))
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["endpoint"] = "wrong"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EmbeddingError, match="cache entry is incompatible"):
        _embed(
            input_path,
            tmp_path,
            FakeClient([]),
            artifact_name="second-artifacts",
        )


def test_unwritable_artifact_boundary_is_reported_as_embedding_error(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])
    (tmp_path / "artifacts").write_text("blocked", encoding="utf-8")

    with pytest.raises(EmbeddingError, match="could not persist embedding artifacts"):
        _embed(input_path, tmp_path, FakeClient([_response(_unit_vector())]))


def test_empty_dataset_writes_zero_row_artifact_without_provider(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=[None])

    artifacts = _embed(
        input_path,
        tmp_path,
        FakeClient([]),
        api_key=None,
    )

    assert artifacts.shape == (0, DIMENSIONS)
    assert artifacts.embeddings_path.read_bytes() == b""
    row_map = json.loads(artifacts.row_map_path.read_text(encoding="utf-8"))
    assert row_map["entries"] == []


def test_missing_api_key_fails_only_when_uncached_answers_need_provider(
    tmp_path: Path,
) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    with pytest.raises(EmbeddingError, match="NEBIUS_API_KEY is required"):
        _embed(input_path, tmp_path, FakeClient([]), api_key=None)

    assert not (tmp_path / "artifacts").exists()


def test_http_and_json_failures_are_safe_embedding_errors(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["answer"])

    with pytest.raises(EmbeddingError, match="HTTP 503"):
        _embed(
            input_path,
            tmp_path,
            FakeClient([FakeResponse({}, status_code=503)]),
        )

    with pytest.raises(EmbeddingError, match="not valid JSON"):
        _embed(
            input_path,
            tmp_path,
            FakeClient([FakeResponse({}, json_error=ValueError("bad json"))]),
            artifact_name="second-artifacts",
        )
