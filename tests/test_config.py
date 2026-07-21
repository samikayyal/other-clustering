from __future__ import annotations

from pathlib import Path

import pytest

from other_cluster.config import resolve_settings
from other_cluster.errors import ConfigurationError

from ._fixtures import create_workbook


def test_cli_values_override_toml_and_environment(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    cli_output = tmp_path / "cli-output.xlsx"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'input = "config-input.xlsx"\n'
        'output = "config-output.xlsx"\n'
        "overwrite = false\n"
        "[discovery]\n"
        "min_unique_answer_texts = 5\n",
        encoding="utf-8",
    )

    settings = resolve_settings(
        input_path=input_path,
        output_path=cli_output,
        config_path=config_path,
        overwrite=True,
        cwd=tmp_path,
        environ={
            "OTHER_CLUSTER_INPUT": "environment-input.xlsx",
            "OTHER_CLUSTER_OUTPUT": "environment-output.xlsx",
            "OTHER_CLUSTER_OVERWRITE": "false",
            "OTHER_CLUSTER_DISCOVERY_MIN_UNIQUE_ANSWER_TEXTS": "9",
        },
    )

    assert settings.input_path == input_path.resolve()
    assert settings.output_path == cli_output.resolve()
    assert settings.overwrite is True
    assert settings.min_unique_answer_texts == 5
    assert settings.config_path == config_path.resolve()


def test_environment_values_override_built_in_defaults(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    output_path = tmp_path / "output.xlsx"

    settings = resolve_settings(
        cwd=tmp_path,
        environ={
            "OTHER_CLUSTER_INPUT": str(input_path),
            "OTHER_CLUSTER_OUTPUT": str(output_path),
            "OTHER_CLUSTER_OVERWRITE": "yes",
            "OTHER_CLUSTER_DISCOVERY_MIN_UNIQUE_ANSWER_TEXTS": "8",
        },
    )

    assert settings.input_path == input_path.resolve()
    assert settings.output_path == output_path.resolve()
    assert settings.overwrite is True
    assert settings.min_unique_answer_texts == 8


def test_default_config_file_is_optional_and_can_supply_paths(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "configured.xlsx")
    (tmp_path / "other-cluster.toml").write_text(
        f'input = "{input_path.name}"\noutput = "output.xlsx"\n',
        encoding="utf-8",
    )

    settings = resolve_settings(cwd=tmp_path, environ={})

    assert settings.input_path == input_path.resolve()
    assert settings.output_path == (tmp_path / "output.xlsx").resolve()
    assert settings.config_path == (tmp_path / "other-cluster.toml").resolve()


def test_unknown_toml_keys_are_configuration_errors(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("unexpected = true\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="unknown TOML key"):
        resolve_settings(
            config_path=config_path,
            cwd=tmp_path,
            environ={},
        )


def test_existing_output_requires_overwrite(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")
    output_path = tmp_path / "output.xlsx"
    output_path.write_bytes(b"existing")

    with pytest.raises(ConfigurationError, match="--overwrite"):
        resolve_settings(
            input_path=input_path,
            output_path=output_path,
            cwd=tmp_path,
            environ={},
        )

    settings = resolve_settings(
        input_path=input_path,
        output_path=output_path,
        overwrite=True,
        cwd=tmp_path,
        environ={},
    )
    assert settings.overwrite is True


def test_input_and_output_must_be_different(tmp_path: Path) -> None:
    input_path = create_workbook(tmp_path / "input.xlsx")

    with pytest.raises(ConfigurationError, match="different files"):
        resolve_settings(
            input_path=input_path,
            output_path=input_path,
            cwd=tmp_path,
            environ={},
        )
