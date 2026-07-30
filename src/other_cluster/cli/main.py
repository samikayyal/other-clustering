"""The two-command ``other-cluster`` CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from ..category_discovery import discover_categories
from ..cluster_classification import classify_clusters
from ..config import resolve_settings
from ..embeddings import embed_dataset
from ..errors import (
    CategoryDiscoveryError,
    ClusterClassificationError,
    ConfigurationError,
    EmbeddingError,
    InputDownloadError,
    ReviewFileError,
    WorkbookContractError,
)
from ..input_sources import materialize_input
from ..review_file import write_review_file
from ..review_webapp import run_review_app
from ..workbook import ingest_workbook


def build_parser() -> argparse.ArgumentParser:
    """Build the public two-command argument parser."""

    parser = argparse.ArgumentParser(
        prog="other-cluster",
        description="Discover and review question-scoped categories for survey Other answers.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser(
        "analyze",
        help="ingest, embed, cluster, classify, and create one review JSON file",
    )
    analyze.add_argument(
        "--input",
        required=True,
        dest="input_path",
        metavar="PATH_OR_GOOGLE_SHEETS_URL",
    )
    review = subparsers.add_parser(
        "review",
        help="open one review JSON file in the local browser application",
    )
    review.add_argument(
        "--review-file",
        required=True,
        type=Path,
        metavar="REVIEW_JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one CLI command and return its process exit code."""

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "review":
        try:
            run_review_app(args.review_file)
        except ReviewFileError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    load_dotenv(Path.cwd() / ".env")
    try:
        settings = resolve_settings(input_path=args.input_path)
        with materialize_input(settings.input_source) as input_path:
            dataset = ingest_workbook(input_path)
            embeddings = embed_dataset(
                dataset,
                api_key=os.getenv("NEBIUS_API_KEY"),
                cache_root=Path.cwd() / "embedding_cache",
            )
            discovery = discover_categories(dataset, embeddings)
            classification = classify_clusters(
                dataset,
                discovery,
                api_key=os.getenv("GEMINI_API_KEY"),
            )
            review_file = write_review_file(
                dataset,
                discovery,
                classification,
                input_source=settings.input_source,
                source_path=input_path,
                output_directory=Path.cwd() / "reviews",
            )
            summary = {
                "status": "in_review",
                "input": settings.input_source,
                "review_file": str(review_file.review_file_path),
                "analysis_run_id": review_file.analysis_run_id,
                "source_workbook_sha256": review_file.source_sha256,
                "question_count": len(dataset.questions),
                "answer_count": len(dataset.answers),
                "canonical_answer_count": len(dataset.processing_answers),
                "embedding_shape": list(embeddings.shape),
                **review_file.counts,
            }
    except ConfigurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (
        InputDownloadError,
        WorkbookContractError,
        EmbeddingError,
        CategoryDiscoveryError,
        ClusterClassificationError,
        ReviewFileError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in dataset.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for warning in classification.warnings:
        print(f"warning: {warning['message']}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
