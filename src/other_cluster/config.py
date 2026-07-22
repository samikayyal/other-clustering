"""CLI and non-secret configuration resolution for ``other-cluster``."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from .errors import ConfigurationError
from .input_sources import is_google_sheets_url

_DEFAULT_CONFIG_NAME = "other-cluster.toml"
_DEFAULT_MIN_UNIQUE_ANSWER_TEXTS = 3
_CONFIG_KEYS = {"input", "output", "overwrite", "discovery"}
_DISCOVERY_CONFIG_KEYS = {"min_unique_answer_texts"}
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class RunSettings:
    """Resolved settings required to start a Feature 01 ingestion run."""

    input_path: Path | None
    output_path: Path
    input_source: str
    config_path: Path | None = None
    overwrite: bool = False
    min_unique_answer_texts: int = _DEFAULT_MIN_UNIQUE_ANSWER_TEXTS
    temp_dir: Path = Path(".temp")


def resolve_settings(
    *,
    input_path: str | Path | None = None,
    output_path: str | Path | None = None,
    config_path: str | Path | None = None,
    overwrite: bool | None = None,
    cwd: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> RunSettings:
    """Resolve settings using CLI > TOML > environment > built-in defaults.

    ``None`` is used for CLI values that were not supplied, which lets the
    caller distinguish an omitted ``--overwrite`` flag from an explicit value
    supplied by a direct Python caller.
    """

    base_dir = Path.cwd() if cwd is None else Path(cwd)
    base_dir = base_dir.expanduser().resolve()
    environment = _load_environment(base_dir, environ)

    selected_config, config_is_explicit = _select_config_path(
        config_path=config_path,
        environment=environment,
        base_dir=base_dir,
    )
    config_values = _read_config(selected_config, explicit=config_is_explicit)

    resolved_input = _select_value(
        cli_value=input_path,
        config_values=config_values,
        config_key="input",
        environment=environment,
        environment_key="OTHER_CLUSTER_INPUT",
    )
    resolved_output = _select_value(
        cli_value=output_path,
        config_values=config_values,
        config_key="output",
        environment=environment,
        environment_key="OTHER_CLUSTER_OUTPUT",
    )

    resolved_overwrite = _resolve_bool(
        cli_value=overwrite,
        config_values=config_values,
        config_key="overwrite",
        environment=environment,
        environment_key="OTHER_CLUSTER_OVERWRITE",
        default=False,
    )
    resolved_min_unique = _resolve_positive_int(
        cli_value=None,
        config_values=config_values,
        config_key="min_unique_answer_texts",
        environment=environment,
        environment_key="OTHER_CLUSTER_DISCOVERY_MIN_UNIQUE_ANSWER_TEXTS",
        default=_DEFAULT_MIN_UNIQUE_ANSWER_TEXTS,
    )

    input_source, normalized_input = _resolve_input_source(
        resolved_input, base_dir=base_dir
    )
    normalized_output = _resolve_required_path(
        resolved_output, setting_name="output", base_dir=base_dir
    )
    _validate_paths(
        input_path=normalized_input,
        output_path=normalized_output,
        overwrite=resolved_overwrite,
    )

    return RunSettings(
        input_path=normalized_input,
        output_path=normalized_output,
        input_source=input_source,
        config_path=selected_config,
        overwrite=resolved_overwrite,
        min_unique_answer_texts=resolved_min_unique,
        temp_dir=(base_dir / ".temp").resolve(),
    )


def _load_environment(
    base_dir: Path, environ: Mapping[str, str] | None
) -> dict[str, str]:
    if environ is not None:
        return dict(environ)

    values: dict[str, str] = {}
    dotenv_path = base_dir / ".env"
    if dotenv_path.is_file():
        try:
            values.update(
                {
                    key: value
                    for key, value in dotenv_values(dotenv_path).items()
                    if value is not None
                }
            )
        except OSError as exc:
            raise ConfigurationError(
                f"could not read optional environment file '{dotenv_path}': {exc}"
            ) from exc
    values.update(os.environ)
    return values


def _select_config_path(
    *,
    config_path: str | Path | None,
    environment: Mapping[str, str],
    base_dir: Path,
) -> tuple[Path | None, bool]:
    if config_path is not None:
        return _normalize_path(config_path, "config", base_dir), True

    configured_path = environment.get("OTHER_CLUSTER_CONFIG")
    if configured_path is not None:
        return _normalize_path(configured_path, "config", base_dir), True

    default_path = (base_dir / _DEFAULT_CONFIG_NAME).resolve()
    if default_path.is_file():
        return default_path, False
    return None, False


def _read_config(path: Path | None, *, explicit: bool) -> dict[str, object]:
    if path is None:
        return {}
    if not path.exists():
        if explicit:
            raise ConfigurationError(f"config file does not exist: '{path}'")
        return {}
    if not path.is_file():
        raise ConfigurationError(f"config path is not a file: '{path}'")

    try:
        with path.open("rb") as config_file:
            values = tomllib.load(config_file)
    except OSError as exc:
        raise ConfigurationError(f"could not read config file '{path}': {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            f"could not parse config file '{path}': {exc}"
        ) from exc

    unknown_top_level = sorted(set(values) - _CONFIG_KEYS)
    if unknown_top_level:
        names = ", ".join(unknown_top_level)
        raise ConfigurationError(f"unknown TOML key(s): {names}")

    discovery = values.get("discovery")
    if discovery is not None:
        if not isinstance(discovery, dict):
            raise ConfigurationError("TOML key 'discovery' must be a table")
        unknown_discovery = sorted(set(discovery) - _DISCOVERY_CONFIG_KEYS)
        if unknown_discovery:
            names = ", ".join(unknown_discovery)
            raise ConfigurationError(f"unknown TOML key(s): discovery.{names}")

    return values


def _select_value(
    *,
    cli_value: object,
    config_values: Mapping[str, object],
    config_key: str,
    environment: Mapping[str, str],
    environment_key: str,
) -> object:
    if cli_value is not None:
        return cli_value
    if config_key in config_values:
        return config_values[config_key]
    if config_key == "min_unique_answer_texts":
        discovery = config_values.get("discovery")
        if isinstance(discovery, dict):
            return discovery.get(config_key)
    if environment_key in environment:
        return environment[environment_key]
    return None


def _resolve_bool(
    *,
    cli_value: bool | None,
    config_values: Mapping[str, object],
    config_key: str,
    environment: Mapping[str, str],
    environment_key: str,
    default: bool,
) -> bool:
    value = _select_value(
        cli_value=cli_value,
        config_values=config_values,
        config_key=config_key,
        environment=environment,
        environment_key=environment_key,
    )
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    source = "TOML or environment"
    raise ConfigurationError(f"{config_key} must be a boolean in {source}")


def _resolve_positive_int(
    *,
    cli_value: int | None,
    config_values: Mapping[str, object],
    config_key: str,
    environment: Mapping[str, str],
    environment_key: str,
    default: int,
) -> int:
    value = _select_value(
        cli_value=cli_value,
        config_values=config_values,
        config_key=config_key,
        environment=environment,
        environment_key=environment_key,
    )
    if value is None:
        return default
    if isinstance(value, bool):
        raise ConfigurationError(f"{config_key} must be a positive integer")
    try:
        parsed = int(value)  # type: ignore
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{config_key} must be a positive integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ConfigurationError(f"{config_key} must be a positive integer")
    if parsed <= 0:
        raise ConfigurationError(f"{config_key} must be a positive integer")
    return parsed


def _resolve_required_path(value: object, *, setting_name: str, base_dir: Path) -> Path:
    if value is None:
        raise ConfigurationError(
            f"{setting_name} path is required; supply --{setting_name}, TOML, or its environment variable"
        )
    if not isinstance(value, (str, Path)):
        raise ConfigurationError(f"{setting_name} path must be a string")
    if isinstance(value, str) and not value.strip():
        raise ConfigurationError(f"{setting_name} path must not be empty")
    return _normalize_path(value, setting_name, base_dir)


def _resolve_input_source(value: object, *, base_dir: Path) -> tuple[str, Path | None]:
    if value is None:
        raise ConfigurationError(
            "input path is required; supply --input, TOML, or its environment variable"
        )
    if not isinstance(value, (str, Path)):
        raise ConfigurationError("input must be a path or Google Sheets URL")
    if isinstance(value, str) and not value.strip():
        raise ConfigurationError("input path must not be empty")

    source = str(value).strip() if isinstance(value, str) else str(value)
    if is_google_sheets_url(source):
        return source, None

    path = _normalize_path(value, "input", base_dir)
    return str(path), path


def _normalize_path(value: str | Path, setting_name: str, base_dir: Path) -> Path:
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        return path.resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid {setting_name} path: {value!r}") from exc


def _validate_paths(
    *, input_path: Path | None, output_path: Path, overwrite: bool
) -> None:
    if input_path is not None:
        if input_path.suffix.lower() != ".xlsx":
            raise ConfigurationError(
                f"input path must be an .xlsx file: '{input_path}'"
            )
        if not input_path.exists():
            raise ConfigurationError(f"input workbook does not exist: '{input_path}'")
        if not input_path.is_file():
            raise ConfigurationError(f"input path is not a file: '{input_path}'")
        if input_path == output_path:
            raise ConfigurationError(
                "input and output paths must refer to different files"
            )
    if output_path.exists() and output_path.is_dir():
        raise ConfigurationError(f"output path is a directory: '{output_path}'")
    if output_path.exists() and not overwrite:
        raise ConfigurationError(
            f"output file already exists; pass --overwrite to replace it: '{output_path}'"
        )
    if not output_path.parent.exists():
        raise ConfigurationError(
            f"output directory does not exist: '{output_path.parent}'"
        )
    if not output_path.parent.is_dir():
        raise ConfigurationError(
            f"output parent is not a directory: '{output_path.parent}'"
        )
