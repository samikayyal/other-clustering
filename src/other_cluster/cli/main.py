"""The ``other-cluster`` ingestion and embedding command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from dotenv import dotenv_values

from ..config import resolve_settings
from ..embeddings import embed_dataset
from ..errors import (
    ConfigurationError,
    EmbeddingError,
    ExtractionOutputError,
    InputDownloadError,
    WorkbookContractError,
)
from ..extraction_export import write_extracted_csv
from ..input_sources import materialize_input
from ..workbook import ingest_workbook


def build_parser() -> argparse.ArgumentParser:
    """Build the public Feature 01 argument parser."""

    parser = argparse.ArgumentParser(
        prog="other-cluster",
        description="Validate, ingest, and embed a SurveyCTO Other-coding workbook.",
    )
    parser.add_argument("--input", dest="input_path", metavar="PATH")
    parser.add_argument("--output", dest="output_path", metavar="PATH")
    parser.add_argument("--config", dest="config_path", metavar="PATH")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=None,
        help="allow an existing output path (the input workbook is never modified)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run ingestion and return the contract-defined process exit code."""

    args = build_parser().parse_args(argv)
    try:
        settings = resolve_settings(
            input_path=args.input_path,
            output_path=args.output_path,
            config_path=args.config_path,
            overwrite=args.overwrite,
        )
        with materialize_input(
            settings.input_source, temp_dir=settings.temp_dir
        ) as input_path:
            dataset = ingest_workbook(input_path)
            extracted_csv_path = write_extracted_csv(
                dataset,
                output_directory=Path.cwd() / "extracted_data",
            )
            artifacts = embed_dataset(
                dataset,
                api_key=_nebius_api_key(Path.cwd()),
                artifact_root=Path.cwd() / "embedding_artifacts",
                cache_root=Path.cwd() / "embedding_cache",
            )
            summary = dataset.to_summary(output_path=settings.output_path)
            summary["status"] = "embedded"
            summary["extracted_csv"] = str(extracted_csv_path)
            summary["embedding_artifact"] = str(artifacts.embeddings_path)
            summary["embedding_row_map"] = str(artifacts.row_map_path)
            summary["embedding_shape"] = list(artifacts.shape)
            summary["embedding_artifact_reused"] = artifacts.reused
            if settings.input_path is None:
                summary["input"] = settings.input_source
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except InputDownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except WorkbookContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ExtractionOutputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except EmbeddingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in dataset.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _nebius_api_key(base_dir: Path) -> str | None:
    """Read the provider secret from process environment or optional ``.env``."""

    process_value = os.environ.get("NEBIUS_API_KEY")
    if process_value is not None:
        return process_value
    dotenv_path = base_dir / ".env"
    if not dotenv_path.is_file():
        return None
    try:
        value = dotenv_values(dotenv_path).get("NEBIUS_API_KEY")
    except OSError as exc:
        raise ConfigurationError(
            f"could not read optional environment file '{dotenv_path}': {exc}"
        ) from exc
    return value


if __name__ == "__main__":
    raise SystemExit(main())
