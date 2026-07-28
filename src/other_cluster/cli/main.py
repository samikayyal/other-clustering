"""The ``other-cluster`` analysis and analyst-review commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from ..category_discovery import discover_categories
from ..category_labeling import label_discovered_clusters
from ..config import resolve_settings
from ..embeddings import embed_dataset
from ..errors import (
    AnalystReviewError,
    CategoryDiscoveryError,
    CategoryLabelingError,
    ConfigurationError,
    EmbeddingError,
    ExistingChoiceAssignmentError,
    ExtractionOutputError,
    InputDownloadError,
    ReviewPackageError,
    WorkbookContractError,
)
from ..existing_choice_assignment import assign_existing_choices
from ..extraction_export import write_extracted_csv
from ..input_sources import materialize_input
from ..review_package import write_review_package
from ..review_webapp import run_review_app
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


def build_review_parser() -> argparse.ArgumentParser:
    """Build the local Feature 06 review-server argument parser."""

    parser = argparse.ArgumentParser(
        prog="other-cluster review",
        description="Review one immutable analysis package in the local web app.",
    )
    parser.add_argument(
        "--review-package",
        required=True,
        type=Path,
        metavar="REVIEW_JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run ingestion and return the contract-defined process exit code."""

    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments[:1] == ["review"]:
        args = build_review_parser().parse_args(arguments[1:])
        try:
            run_review_app(args.review_package)
        except AnalystReviewError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    args = build_parser().parse_args(arguments)
    load_dotenv(Path.cwd() / ".env")
    api_key = os.getenv("NEBIUS_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")

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
            embeddings = embed_dataset(
                dataset,
                api_key=api_key,
                cache_root=Path.cwd() / "embedding_cache",
            )
            assignments = assign_existing_choices(
                dataset,
                embeddings,
                api_key=gemini_api_key,
            )
            discovery = discover_categories(
                dataset,
                embeddings,
                assignments,
                pca_components=settings.pca_components,
                min_unique_answer_texts=settings.min_unique_answer_texts,
                membership_probability_threshold=settings.membership_probability_threshold,
                merge_cosine_similarity_threshold=settings.merge_cosine_similarity_threshold,
            )
            labeling = label_discovered_clusters(
                dataset,
                discovery,
                api_key=gemini_api_key,
            )
            review_package = write_review_package(
                dataset,
                assignments,
                discovery,
                labeling,
                input_source=settings.input_source,
                source_path=input_path,
                output_directory=Path.cwd() / "review_packages",
            )
            summary = dataset.to_summary(output_path=settings.output_path)
            summary["status"] = "review_package_prepared"
            summary["extracted_csv"] = str(extracted_csv_path)
            summary["embedding_shape"] = list(embeddings.shape)
            summary["existing_choice_assignment_count"] = len(assignments.assignments)
            summary["unassigned_answer_count"] = len(assignments.unassigned_answer_ids)
            summary["proposed_cluster_count"] = len(discovery.proposed_clusters)
            summary["unresolved_discovery_answer_count"] = len(
                discovery.unresolved_answer_ids
            )
            summary["merge_suggestion_count"] = len(discovery.merge_suggestions)
            summary["labeled_category_count"] = len(labeling.proposed_categories)
            summary["rejected_label_cluster_count"] = sum(
                decision.decision == "reject" for decision in labeling.decisions
            )
            summary["review_package"] = str(review_package.package_path)
            summary["analysis_run_id"] = review_package.analysis_run_id
            summary["source_workbook_sha256"] = review_package.source_sha256
            summary["review_item_counts"] = review_package.item_counts
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
    except ExistingChoiceAssignmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except CategoryDiscoveryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except CategoryLabelingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ReviewPackageError as exc:
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
