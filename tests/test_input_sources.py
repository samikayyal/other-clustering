from __future__ import annotations

import os
from email.message import Message
from io import BytesIO
from pathlib import Path

import pytest

from other_cluster.errors import InputDownloadError
from other_cluster.input_sources import (
    download_google_sheet,
    google_sheets_export_url,
    materialize_input,
)


GOOGLE_SHEETS_URL = (
    "https://docs.google.com/spreadsheets/d/abc123_-9/edit?gid=15457928#gid=15457928"
)


@pytest.fixture(autouse=True)
def _instant_cleanup_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep cleanup retries from sleeping between attempts during tests."""

    monkeypatch.setattr("other_cluster.input_sources._CLEANUP_RETRY_DELAY_SECONDS", 0)


def test_google_sheets_link_is_converted_to_xlsx_export_url() -> None:
    assert google_sheets_export_url(GOOGLE_SHEETS_URL) == (
        "https://docs.google.com/spreadsheets/d/abc123_-9/export?format=xlsx"
    )


def test_download_google_sheet_requests_xlsx_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[tuple[str, int]] = []

    class FakeResponse(BytesIO):
        status = 200

        def __init__(self, content: bytes) -> None:
            super().__init__(content)
            self.headers = Message()
            self.headers["Content-Disposition"] = (
                'attachment; filename="Actual Sheet Name.xlsx"'
            )

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def fake_urlopen(request, *, timeout: int) -> FakeResponse:
        requests.append((request.full_url, timeout))
        return FakeResponse(b"xlsx bytes")

    monkeypatch.setattr("other_cluster.input_sources.urlopen", fake_urlopen)
    destination = tmp_path / "download.xlsx"

    filename = download_google_sheet(GOOGLE_SHEETS_URL, destination)

    assert destination.read_bytes() == b"xlsx bytes"
    assert filename == "Actual Sheet Name.xlsx"
    assert requests == [
        (
            "https://docs.google.com/spreadsheets/d/abc123_-9/export?format=xlsx",
            30,
        )
    ]


def test_materialize_input_downloads_xlsx_and_removes_it_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / ".temp"
    downloaded_bytes = b"downloaded workbook"

    def fake_download(source: str, destination: str | Path) -> str:
        assert source == GOOGLE_SHEETS_URL
        Path(destination).write_bytes(downloaded_bytes)
        return "Actual Sheet Name.xlsx"

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )

    with materialize_input(GOOGLE_SHEETS_URL, temp_dir=temp_dir) as input_path:
        assert input_path.parent.parent == temp_dir.resolve()
        assert input_path.name == "Actual Sheet Name.xlsx"
        assert input_path.suffix == ".xlsx"
        assert input_path.read_bytes() == downloaded_bytes

    assert list(temp_dir.iterdir()) == []


def test_materialize_input_removes_partial_download_after_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / ".temp"

    def failing_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"partial")
        raise InputDownloadError("download failed")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", failing_download
    )

    with pytest.raises(InputDownloadError, match="download failed"):
        with materialize_input(GOOGLE_SHEETS_URL, temp_dir=temp_dir):
            pass

    assert list(temp_dir.iterdir()) == []


def test_materialize_input_removes_download_after_ingestion_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / ".temp"

    def fake_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"downloaded")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )

    with pytest.raises(RuntimeError, match="ingestion failed"):
        with materialize_input(GOOGLE_SHEETS_URL, temp_dir=temp_dir) as input_path:
            assert input_path.exists()
            raise RuntimeError("ingestion failed")

    assert list(temp_dir.iterdir()) == []


def test_materialize_input_cleanup_failure_does_not_mask_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / ".temp"

    def fake_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"downloaded")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )
    original_unlink = Path.unlink

    def failing_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path.parent.name.startswith("google-sheet-"):
            raise OSError("file is locked")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(InputDownloadError, match="primary error") as error:
        with materialize_input(GOOGLE_SHEETS_URL, temp_dir=temp_dir):
            raise InputDownloadError("primary error")

    assert any("file is locked" in note for note in error.value.__notes__)


def test_materialize_input_warns_instead_of_failing_a_successful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    temp_dir = tmp_path / ".temp"

    def fake_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"downloaded")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )
    original_rmdir = Path.rmdir

    def failing_rmdir(path: Path) -> None:
        if path.name.startswith("google-sheet-"):
            raise PermissionError("[WinError 5] Access is denied")
        original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", failing_rmdir)

    with materialize_input(GOOGLE_SHEETS_URL, temp_dir=temp_dir) as input_path:
        assert input_path.exists()

    assert "Access is denied" in capsys.readouterr().err


def test_materialize_input_cleanup_survives_a_transient_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    temp_dir = tmp_path / ".temp"

    def fake_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"downloaded")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )
    original_rmdir = Path.rmdir
    attempts = 0

    def briefly_failing_rmdir(path: Path) -> None:
        nonlocal attempts
        if path.name.startswith("google-sheet-"):
            attempts += 1
            if attempts < 3:
                raise PermissionError("[WinError 5] Access is denied")
        original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", briefly_failing_rmdir)

    with materialize_input(GOOGLE_SHEETS_URL, temp_dir=temp_dir):
        pass

    assert attempts == 3
    assert list(temp_dir.iterdir()) == []
    assert capsys.readouterr().err == ""


def test_materialize_input_sweeps_empty_directories_left_by_earlier_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / ".temp"
    temp_dir.mkdir()
    stale = temp_dir / "google-sheet-stale"
    stale.mkdir()
    os.utime(stale, (0, 0))
    recent = temp_dir / "google-sheet-recent"
    recent.mkdir()
    unrelated = temp_dir / "keep-me"
    unrelated.mkdir()
    os.utime(unrelated, (0, 0))

    def fake_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"downloaded")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )

    with materialize_input(GOOGLE_SHEETS_URL, temp_dir=temp_dir):
        pass

    assert not stale.exists()
    assert recent.exists()
    assert unrelated.exists()


def test_materialize_input_yields_local_paths_without_creating_temp_files(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.xlsx"
    input_path.write_bytes(b"local workbook")
    temp_dir = tmp_path / ".temp"

    with materialize_input(input_path, temp_dir=temp_dir) as resolved_path:
        assert resolved_path == input_path.resolve()

    assert not temp_dir.exists()
