from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from other_cluster.cli.main import main
from other_cluster.errors import (
    CategoryDiscoveryError,
    EmbeddingError,
    ExistingChoiceAssignmentError,
    InputDownloadError,
)

from ._fixtures import create_workbook


@pytest.fixture(autouse=True)
def stub_embedding_stage(tmp_path: Path, monkeypatch):
    def fake_embed(dataset, **kwargs):
        return SimpleNamespace(
            shape=(len(dataset.processing_answers), 4096),
        )

    monkeypatch.setattr("other_cluster.cli.main.embed_dataset", fake_embed)
    return fake_embed


@pytest.fixture(autouse=True)
def stub_existing_choice_assignment_stage(monkeypatch):
    def fake_assign(dataset, embeddings, **kwargs):
        return SimpleNamespace(
            assignments=(),
            unassigned_answer_ids=tuple(answer.answer_id for answer in dataset.answers),
        )

    monkeypatch.setattr("other_cluster.cli.main.assign_existing_choices", fake_assign)
    return fake_assign


@pytest.fixture(autouse=True)
def stub_category_discovery_stage(monkeypatch):
    def fake_discovery(dataset, embeddings, assignments, **kwargs):
        return SimpleNamespace(
            proposed_clusters=(),
            unresolved_answer_ids=(),
            merge_suggestions=(),
        )

    monkeypatch.setattr("other_cluster.cli.main.discover_categories", fake_discovery)
    return fake_discovery


def test_cli_ingests_workbook_and_returns_json_summary(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = create_workbook(tmp_path / "input.xlsx")
    output_path = tmp_path / "output.xlsx"

    exit_code = main(["--input", str(input_path), "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    summary = json.loads(captured.out)
    assert summary == {
        "answer_count": 3,
        "embedding_shape": [2, 4096],
        "existing_choice_assignment_count": 0,
        "extracted_csv": str(tmp_path / "extracted_data" / "input_extracted.csv"),
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "processing_answer_count": 2,
        "question_count": 1,
        "merge_suggestion_count": 0,
        "proposed_cluster_count": 0,
        "status": "categories_discovered",
        "unassigned_answer_count": 3,
        "unresolved_discovery_answer_count": 0,
    }
    assert not output_path.exists()
    assert captured.err == ""


def test_cli_warns_and_succeeds_for_numeric_answer_cells(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = create_workbook(tmp_path / "input.xlsx", answers=[123])
    output_path = tmp_path / "output.xlsx"

    exit_code = main(["--input", str(input_path), "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["answer_count"] == 0
    assert (
        captured.err
        == "warning: Data!D2 (row 2) contains a numeric answer; treating it as an empty cell\n"
    )


def test_cli_returns_configuration_exit_code_for_unresolved_paths(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "path is required" in captured.err


def test_cli_downloads_google_sheets_input_and_cleans_temp_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    source_workbook = create_workbook(tmp_path / "source.xlsx")
    output_path = tmp_path / "output.xlsx"
    input_url = "https://docs.google.com/spreadsheets/d/abc123/edit"

    def fake_download(source: str, destination: str | Path) -> str:
        assert source == input_url
        Path(destination).write_bytes(source_workbook.read_bytes())
        return "Actual Google Sheet Name.xlsx"

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )

    exit_code = main(["--input", input_url, "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    summary = json.loads(captured.out)
    assert summary["input"] == input_url
    assert summary["extracted_csv"] == str(
        tmp_path / "extracted_data" / "actual_google_sheet_name_extracted.csv"
    )
    assert list((tmp_path / ".temp").glob("*.xlsx")) == []
    assert captured.err == ""


def test_cli_returns_download_exit_code_and_cleans_temp_file_on_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    input_url = "https://docs.google.com/spreadsheets/d/abc123/edit"

    def failing_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"partial")
        raise InputDownloadError("network unavailable")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", failing_download
    )

    exit_code = main(["--input", input_url, "--output", str(tmp_path / "output.xlsx")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "network unavailable" in captured.err
    assert list((tmp_path / ".temp").glob("*.xlsx")) == []


def test_cli_returns_download_exit_code_when_temp_path_is_blocked(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    input_url = "https://docs.google.com/spreadsheets/d/abc123/edit"
    blocked_temp_path = tmp_path / ".temp"
    blocked_temp_path.write_text("not a directory", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["--input", input_url, "--output", str(tmp_path / "output.xlsx")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "could not prepare temporary Google Sheets input" in captured.err
    assert "Traceback" not in captured.err
    assert blocked_temp_path.read_text(encoding="utf-8") == "not a directory"


def test_cli_returns_provider_exit_code_for_embedding_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = create_workbook(tmp_path / "input.xlsx")

    def fail_embedding(*args, **kwargs):
        raise EmbeddingError("provider unavailable")

    monkeypatch.setattr("other_cluster.cli.main.embed_dataset", fail_embedding)

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output",
            str(tmp_path / "output.xlsx"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "error: provider unavailable\n"


def test_cli_loads_nebius_api_key_from_optional_dotenv(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "NEBIUS_API_KEY=dotenv-secret\n",
        encoding="utf-8",
    )
    input_path = create_workbook(tmp_path / "input.xlsx")
    captured_key: list[str | None] = []

    def capture_embedding(dataset, **kwargs):
        captured_key.append(kwargs["api_key"])
        return SimpleNamespace(
            shape=(len(dataset.processing_answers), 4096),
        )

    monkeypatch.setattr("other_cluster.cli.main.embed_dataset", capture_embedding)

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output",
            str(tmp_path / "output.xlsx"),
        ]
    )

    assert exit_code == 0
    assert captured_key == ["dotenv-secret"]
    assert json.loads(capsys.readouterr().out)["status"] == "categories_discovered"


def test_cli_loads_gemini_api_key_from_optional_dotenv(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=dotenv-gemini-secret\n",
        encoding="utf-8",
    )
    input_path = create_workbook(tmp_path / "input.xlsx")
    captured_key: list[str | None] = []

    def capture_assignment(dataset, embeddings, **kwargs):
        captured_key.append(kwargs["api_key"])
        return SimpleNamespace(
            assignments=(),
            unassigned_answer_ids=tuple(answer.answer_id for answer in dataset.answers),
        )

    monkeypatch.setattr(
        "other_cluster.cli.main.assign_existing_choices", capture_assignment
    )

    exit_code = main(
        ["--input", str(input_path), "--output", str(tmp_path / "output.xlsx")]
    )

    assert exit_code == 0
    assert captured_key == ["dotenv-gemini-secret"]
    assert json.loads(capsys.readouterr().out)["status"] == "categories_discovered"


def test_cli_returns_provider_exit_code_for_existing_choice_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = create_workbook(tmp_path / "input.xlsx")

    def fail_assignment(*args, **kwargs):
        raise ExistingChoiceAssignmentError("Gemini unavailable")

    monkeypatch.setattr(
        "other_cluster.cli.main.assign_existing_choices", fail_assignment
    )

    exit_code = main(
        ["--input", str(input_path), "--output", str(tmp_path / "output.xlsx")]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "error: Gemini unavailable\n"


def test_cli_returns_failure_exit_code_for_discovery_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = create_workbook(tmp_path / "input.xlsx")

    def fail_discovery(*args, **kwargs):
        raise CategoryDiscoveryError("invalid clustering evidence")

    monkeypatch.setattr("other_cluster.cli.main.discover_categories", fail_discovery)

    exit_code = main(
        ["--input", str(input_path), "--output", str(tmp_path / "output.xlsx")]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err == "error: invalid clustering evidence\n"
