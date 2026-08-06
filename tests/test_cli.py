from __future__ import annotations

import json
from pathlib import Path

import pytest

from other_cluster.cli.main import main
from other_cluster.domain import ClusterClassificationResult, ClusterProposal
from other_cluster.review_file import load_review_file

from ._fixtures import create_workbook, discovery_embeddings


def test_legacy_analysis_flags_are_removed() -> None:
    with pytest.raises(SystemExit):
        main(["--input", "input.xlsx", "--output", "output.xlsx"])


def test_module_launcher_is_available() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "other_cluster", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "analyze" in result.stdout


def test_review_passes_optional_ground_truth_to_webapp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, str | None]] = []
    monkeypatch.setattr(
        "other_cluster.cli.main.run_review_app",
        lambda review_path, ground_truth: calls.append((review_path, ground_truth)),
    )

    review_path = tmp_path / "review.json"
    assert (
        main(
            [
                "review",
                "--review-file",
                str(review_path),
                "--ground-truth",
                "coded.gsheet",
            ]
        )
        == 0
    )
    assert calls == [(review_path, "coded.gsheet")]


def test_analyze_creates_one_review_file_and_no_csv_or_workbook_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    source = create_workbook(tmp_path / "Input Workbook.xlsx", answers=["a", "b", "c"])
    monkeypatch.chdir(tmp_path)

    def fake_cluster(features, **kwargs):
        return [0] * len(features), [1.0] * len(features)

    monkeypatch.setattr("other_cluster.category_discovery._cluster", fake_cluster)
    monkeypatch.setattr(
        "other_cluster.cli.main.embed_discovery_dataset",
        lambda dataset, **kwargs: discovery_embeddings(dataset),
    )

    def fake_classify(dataset, discovery, **kwargs):
        cluster = discovery.proposed_clusters[0]
        return ClusterClassificationResult(
            (
                ClusterProposal(
                    cluster_id=cluster.cluster_id,
                    question_id=cluster.question_id,
                    decision="reject_cluster",
                    selected_choice_value=None,
                    english_label=None,
                    arabic_label=None,
                    rejection_reason="mixed_meanings",
                ),
            )
        )

    monkeypatch.setattr("other_cluster.cli.main.classify_clusters", fake_classify)
    result = main(["analyze", "--input", str(source)])
    assert result == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert "[analyze] ingestion: data rows scanned; rows=1/3" in captured.err
    assert "[analyze] ingestion: complete; questions=1; answers=3" in captured.err
    assert "[analyze] discovery: question 1/1 'B5_other' complete" in captured.err
    assert "[analyze] review: created;" in captured.err
    assert captured.err.endswith(
        "[analyze] complete; final summary JSON follows on stdout\n"
    )
    review_path = Path(summary["review_file"])
    assert review_path.exists()
    assert load_review_file(review_path)["status"] == "in_review"
    assert summary["gemini_request_count"] == 1
    assert not (tmp_path / "extracted_data").exists()
    assert not (tmp_path / "coded-output.xlsx").exists()


def test_analyze_with_one_canonical_answer_does_not_require_provider_keys(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source = create_workbook(tmp_path / "rare.xlsx", answers=["a", "a"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("other_cluster.cli.main.os.getenv", lambda name: None)
    assert main(["analyze", "--input", str(source)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["gemini_request_count"] == 0
