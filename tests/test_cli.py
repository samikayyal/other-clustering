from __future__ import annotations

import json
from pathlib import Path

from other_cluster.cli.main import main

from ._fixtures import create_workbook


def test_cli_ingests_workbook_and_returns_json_summary(tmp_path: Path, capsys) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    output_path = tmp_path / "output.xlsx"

    exit_code = main(["--input", str(input_path), "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    summary = json.loads(captured.out)
    assert summary == {
        "answer_count": 3,
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "processing_answer_count": 2,
        "question_count": 1,
        "status": "ingested",
    }
    assert not output_path.exists()
    assert captured.err == ""


def test_cli_returns_configuration_exit_code_for_unresolved_paths(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "path is required" in captured.err
