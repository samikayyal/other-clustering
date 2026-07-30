from __future__ import annotations

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
    downloaded_bytes = b"downloaded workbook"

    def fake_download(source: str, destination: str | Path) -> str:
        assert source == GOOGLE_SHEETS_URL
        Path(destination).write_bytes(downloaded_bytes)
        return "Actual Sheet Name.xlsx"

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )

    with materialize_input(GOOGLE_SHEETS_URL) as input_path:
        assert input_path.parent.name.startswith("google-sheet-")
        assert input_path.name == "Actual Sheet Name.xlsx"
        assert input_path.suffix == ".xlsx"
        assert input_path.read_bytes() == downloaded_bytes

    assert not input_path.parent.exists()


def test_materialize_input_removes_partial_download_after_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def failing_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"partial")
        raise InputDownloadError("download failed")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", failing_download
    )

    with pytest.raises(InputDownloadError, match="download failed"):
        with materialize_input(GOOGLE_SHEETS_URL):
            pass


def test_materialize_input_removes_download_after_ingestion_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def fake_download(source: str, destination: str | Path) -> None:
        Path(destination).write_bytes(b"downloaded")

    monkeypatch.setattr(
        "other_cluster.input_sources.download_google_sheet", fake_download
    )

    with pytest.raises(RuntimeError, match="ingestion failed"):
        with materialize_input(GOOGLE_SHEETS_URL) as input_path:
            assert input_path.exists()
            raise RuntimeError("ingestion failed")


def test_materialize_input_cleanup_failure_does_not_mask_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

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
        with materialize_input(GOOGLE_SHEETS_URL):
            raise InputDownloadError("primary error")

    assert any("file is locked" in note for note in error.value.__notes__)


def test_materialize_input_warns_instead_of_failing_a_successful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:

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

    with materialize_input(GOOGLE_SHEETS_URL) as input_path:
        assert input_path.exists()

    assert "Access is denied" in capsys.readouterr().err


def test_materialize_input_cleanup_survives_a_transient_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:

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

    with materialize_input(GOOGLE_SHEETS_URL):
        pass

    assert attempts == 3
    assert capsys.readouterr().err == ""


def test_materialize_input_yields_local_paths_without_creating_temp_files(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.xlsx"
    input_path.write_bytes(b"local workbook")
    with materialize_input(input_path) as resolved_path:
        assert resolved_path == input_path.resolve()
