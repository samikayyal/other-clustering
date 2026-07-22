"""The Feature 01 ``other-cluster`` command."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from ..config import resolve_settings
from ..errors import ConfigurationError, InputDownloadError, WorkbookContractError
from ..input_sources import materialize_input
from ..workbook import ingest_workbook


def build_parser() -> argparse.ArgumentParser:
    """Build the public Feature 01 argument parser."""

    parser = argparse.ArgumentParser(
        prog="other-cluster",
        description="Validate and ingest a SurveyCTO Other-coding workbook.",
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
            summary = dataset.to_summary(output_path=settings.output_path)
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


if __name__ == "__main__":
    raise SystemExit(main())
