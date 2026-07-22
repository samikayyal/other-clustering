"""Resolve local workbook paths and materialize Google Sheets inputs."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .errors import InputDownloadError

_GOOGLE_SHEETS_HOST = "docs.google.com"
_GOOGLE_SHEETS_PATH = re.compile(
    r"^/spreadsheets/(?:u/\d+/)?d/(?P<spreadsheet_id>[A-Za-z0-9_-]+)(?:/|$)"
)
_DOWNLOAD_TIMEOUT_SECONDS = 30


def google_sheets_export_url(source: str) -> str | None:
    """Return the XLSX export URL for a native Google Sheets link."""

    try:
        parsed = urlsplit(source.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.hostname is None or parsed.hostname.casefold() != _GOOGLE_SHEETS_HOST:
        return None

    match = _GOOGLE_SHEETS_PATH.match(parsed.path)
    if match is None:
        return None
    spreadsheet_id = match.group("spreadsheet_id")
    return (
        f"https://{_GOOGLE_SHEETS_HOST}/spreadsheets/d/"
        f"{spreadsheet_id}/export?format=xlsx"
    )


def is_google_sheets_url(source: object) -> bool:
    """Return whether ``source`` is a supported native Google Sheets link."""

    return isinstance(source, str) and google_sheets_export_url(source) is not None


@contextmanager
def materialize_input(
    input_source: str | Path, *, temp_dir: str | Path
) -> Iterator[Path]:
    """Yield a local XLSX path and clean up any downloaded file afterward."""

    source = str(input_source)
    if not is_google_sheets_url(source):
        yield Path(input_source).expanduser().resolve()
        return

    temporary_path: Path | None = None
    try:
        directory = Path(temp_dir).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="google-sheet-",
            suffix=".xlsx",
            dir=directory,
        )
        temporary_path = Path(temporary_name)
        os.close(descriptor)
    except (OSError, RuntimeError) as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                exc.add_note(
                    f"could not remove partially allocated temporary file: {cleanup_exc}"
                )
        raise InputDownloadError(
            f"could not prepare temporary Google Sheets input: {exc}"
        ) from exc

    assert temporary_path is not None
    try:
        download_google_sheet(source, temporary_path)
        yield temporary_path
    finally:
        primary_exception = sys.exc_info()[1]
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            if primary_exception is None:
                raise InputDownloadError(
                    f"could not clean up temporary Google Sheets input "
                    f"'{temporary_path}': {cleanup_exc}"
                ) from cleanup_exc
            primary_exception.add_note(
                f"could not clean up temporary Google Sheets input "
                f"'{temporary_path}': {cleanup_exc}"
            )


def download_google_sheet(source: str, destination: str | Path) -> None:
    """Download a native Google Sheet as an XLSX file."""

    export_url = google_sheets_export_url(source)
    if export_url is None:
        raise InputDownloadError(
            "input must be a supported Google Sheets URL when downloading"
        )

    request = Request(
        export_url,
        headers={"User-Agent": "other-cluster/0.1"},
    )
    destination_path = Path(destination)
    try:
        with urlopen(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            if status is not None and status >= 400:
                raise InputDownloadError(
                    f"Google Sheets export returned HTTP status {status}"
                )
            with destination_path.open("wb") as output_file:
                shutil.copyfileobj(response, output_file)
    except InputDownloadError:
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise InputDownloadError(
            f"could not download Google Sheets input: {exc}"
        ) from exc
