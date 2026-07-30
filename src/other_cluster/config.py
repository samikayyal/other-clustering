"""Fixed V1 input boundary for the two-command CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .input_sources import is_google_sheets_url


@dataclass(frozen=True, slots=True)
class RunSettings:
    """Resolved source settings needed by one analysis run."""

    input_source: str


def resolve_settings(
    *, input_path: str | Path | None, cwd: str | Path | None = None
) -> RunSettings:
    """Validate the sole analysis input and return fixed V1 settings."""

    base_dir = (Path.cwd() if cwd is None else Path(cwd)).expanduser().resolve()
    if input_path is None:
        raise ConfigurationError("--input is required")
    if not isinstance(input_path, (str, Path)):
        raise ConfigurationError("--input must be an .xlsx path or Google Sheets URL")
    source = str(input_path).strip()
    if not source:
        raise ConfigurationError("--input must not be empty")
    if is_google_sheets_url(source):
        return RunSettings(
            input_source=source,
        )
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    try:
        normalized = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ConfigurationError(f"invalid --input path: {input_path!r}") from exc
    if normalized.suffix.casefold() != ".xlsx":
        raise ConfigurationError(f"input path must be an .xlsx file: '{normalized}'")
    if not normalized.exists():
        raise ConfigurationError(f"input workbook does not exist: '{normalized}'")
    if not normalized.is_file():
        raise ConfigurationError(f"input path is not a file: '{normalized}'")
    return RunSettings(
        input_source=str(normalized),
    )
