from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from other_cluster.cli.main import main
from other_cluster.category_labeling import label_discovered_clusters
from other_cluster.domain import (
    CategoryDiscoveryResult,
    DiscoveredCluster,
    DiscoveryPointResult,
    ExistingChoiceAssignmentResult,
    ExistingChoiceVerification,
)
from other_cluster.errors import (
    CategoryDiscoveryError,
    EmbeddingError,
    ExistingChoiceAssignmentError,
    InputDownloadError,
)
from other_cluster.review_package import write_review_package

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


@pytest.fixture(autouse=True)
def stub_category_labeling_stage(monkeypatch):
    def fake_labeling(dataset, discovery, **kwargs):
        return SimpleNamespace(decisions=(), proposed_categories=())

    monkeypatch.setattr(
        "other_cluster.cli.main.label_discovered_clusters", fake_labeling
    )
    return fake_labeling


@pytest.fixture(autouse=True)
def stub_review_package_stage(monkeypatch, tmp_path):
    def fake_review_package(dataset, assignments, discovery, labeling, **kwargs):
        return SimpleNamespace(
            package_path=tmp_path / "review_packages" / "package_review.json",
            analysis_run_id="123e4567-e89b-42d3-a456-426614174000",
            source_sha256="a" * 64,
            item_counts={
                "answers": len(dataset.processing_answers),
                "questions": len(dataset.questions),
            },
        )

    monkeypatch.setattr(
        "other_cluster.cli.main.write_review_package", fake_review_package
    )
    return fake_review_package


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
        "analysis_run_id": "123e4567-e89b-42d3-a456-426614174000",
        "embedding_shape": [2, 4096],
        "existing_choice_assignment_count": 0,
        "extracted_csv": str(tmp_path / "extracted_data" / "input_extracted.csv"),
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "processing_answer_count": 2,
        "question_count": 1,
        "merge_suggestion_count": 0,
        "labeled_category_count": 0,
        "proposed_cluster_count": 0,
        "rejected_label_cluster_count": 0,
        "review_item_counts": {"answers": 2, "questions": 1},
        "review_package": str(tmp_path / "review_packages" / "package_review.json"),
        "source_workbook_sha256": "a" * 64,
        "status": "review_package_prepared",
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


def test_cli_starts_local_review_mode_for_explicit_package(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    package_path = tmp_path / "review.json"
    package_path.write_text("{}", encoding="utf-8")
    captured_paths: list[Path] = []
    monkeypatch.setattr(
        "other_cluster.cli.main.run_review_app",
        lambda path: captured_paths.append(path),
    )

    exit_code = main(["review", "--review-package", str(package_path)])

    assert exit_code == 0
    assert captured_paths == [package_path]
    assert capsys.readouterr().out == ""


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
    assert json.loads(capsys.readouterr().out)["status"] == "review_package_prepared"


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
    assert json.loads(capsys.readouterr().out)["status"] == "review_package_prepared"


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


def test_cli_writes_real_feature_05_review_package_without_mutating_source(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    input_path = create_workbook(tmp_path / "input.xlsx", answers=["a", "b", "c"])
    before = input_path.read_bytes()

    def no_match_assignments(dataset, embeddings, **kwargs):
        return ExistingChoiceAssignmentResult(
            verifications=tuple(
                ExistingChoiceVerification(
                    processing_id=item.processing_id,
                    question_id=item.question_id,
                    status="no_match",
                    selected_choice_value=None,
                    provider_evaluated=True,
                )
                for item in dataset.processing_answers
            ),
            assignments=(),
            unassigned_answer_ids=tuple(
                answer_id
                for item in dataset.processing_answers
                for answer_id in item.answer_ids
            ),
        )

    def accepted_cluster_discovery(dataset, embeddings, assignments, **kwargs):
        cluster_id = "B5_other:cluster:0"
        processing = tuple(dataset.processing_answers)
        return CategoryDiscoveryResult(
            reductions=(),
            points=tuple(
                DiscoveryPointResult(
                    processing_id=item.processing_id,
                    question_id=item.question_id,
                    answer_ids=item.answer_ids,
                    occurrence_count=item.occurrence_count,
                    raw_cluster_label=0,
                    membership_probability=0.9,
                    status="accepted_cluster",
                    cluster_id=cluster_id,
                )
                for item in processing
            ),
            proposed_clusters=(
                DiscoveredCluster(
                    cluster_id=cluster_id,
                    question_id="B5_other",
                    raw_cluster_label=0,
                    processing_ids=tuple(item.processing_id for item in processing),
                    answer_ids=tuple(
                        answer_id
                        for item in processing
                        for answer_id in item.answer_ids
                    ),
                ),
            ),
            unresolved_answer_ids=(),
            merge_suggestions=(),
        )

    def label_with_mocked_gemini(dataset, discovery, **kwargs):
        client = SimpleNamespace(
            interactions=SimpleNamespace(
                create=lambda **request: SimpleNamespace(
                    output_text=json.dumps(
                        {
                            "decision": "label",
                            "english_label": "Local Origins",
                            "arabic_label": "اصول محلية",
                            "rejection_reason": None,
                        },
                        ensure_ascii=False,
                    )
                )
            )
        )
        return label_discovered_clusters(
            dataset, discovery, api_key=kwargs["api_key"], client=client
        )

    monkeypatch.setattr(
        "other_cluster.cli.main.assign_existing_choices", no_match_assignments
    )
    monkeypatch.setattr(
        "other_cluster.cli.main.discover_categories", accepted_cluster_discovery
    )
    monkeypatch.setattr(
        "other_cluster.cli.main.label_discovered_clusters", label_with_mocked_gemini
    )
    monkeypatch.setattr(
        "other_cluster.cli.main.write_review_package", write_review_package
    )

    exit_code = main(
        ["--input", str(input_path), "--output", str(tmp_path / "output.xlsx")]
    )

    summary = json.loads(capsys.readouterr().out)
    package_path = Path(summary["review_package"])
    package = json.loads(package_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["status"] == "review_package_prepared"
    assert summary["labeled_category_count"] == 1
    assert summary["review_item_counts"] == {
        "answers": 3,
        "proposed_categories": 1,
        "questions": 1,
    }
    assert package["source_workbook"]["sha256"] == summary["source_workbook_sha256"]
    category = package["questions"][0]["proposed_categories"][0]
    assert category["review_item_id"] == "proposed_category:B5_other:cluster:0"
    assert category["proposed_value"] == 101
    assert category["english_label"] == "Local Origins"
    assert category["arabic_label"] == "اصول محلية"
    assert len(category["member_processing_ids"]) == 3
    assert input_path.read_bytes() == before
