from __future__ import annotations

import json
from pathlib import Path

from other_cluster.cli.main import main
from other_cluster.errors import InputDownloadError

from ._fixtures import create_workbook


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
        "extracted_csv": str(tmp_path / "extracted_data" / "input_extracted.csv"),
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "processing_answer_count": 2,
        "question_count": 1,
        "status": "ingested",
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
