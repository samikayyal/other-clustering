"""The ``other-cluster`` CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from ..category_discovery import discover_categories
from ..cluster_classification import classify_clusters
from ..config import resolve_settings
from ..embeddings import embed_discovery_dataset
from ..errors import (
    CategoryDiscoveryError,
    ClusterClassificationError,
    ConfigurationError,
    EmbeddingError,
    GroundTruthError,
    InputDownloadError,
    ReviewFileError,
    WorkbookContractError,
)
from ..ground_truth_evaluation import (
    evaluate_ground_truth_file,
    format_ground_truth_evaluation,
)
from ..input_sources import materialize_input
from ..review_evaluation import evaluate_review_file, format_evaluation
from ..review_file import write_review_file
from ..review_webapp import run_review_app
from ..workbook import ingest_workbook


def build_parser() -> argparse.ArgumentParser:
    """Build the public command parser."""

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
    evaluate = subparsers.add_parser(
        "evaluate",
        help="print clustering and Gemini classification metrics for one review JSON file",
    )
    evaluate.add_argument(
        "--review-file",
        required=True,
        type=Path,
        metavar="REVIEW_JSON",
    )
    evaluate.add_argument(
        "--ground-truth",
        type=str,
        metavar="XLSX_OR_GOOGLE_SHEET",
        help="compare clustering to hand-coded Work-tab _C1 values",
    )
    return parser


def _print_progress(message: str) -> None:
    """Print live analyze progress without contaminating the JSON stdout result."""

    print(f"[analyze] {message}", file=sys.stderr, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one CLI command and return its process exit code."""

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "evaluate":
        try:
            if args.ground_truth:
                evaluation = evaluate_ground_truth_file(
                    args.review_file, args.ground_truth
                )
            else:
                evaluations = evaluate_review_file(args.review_file)
        except (GroundTruthError, InputDownloadError, ReviewFileError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.ground_truth:
            print(
                format_ground_truth_evaluation(
                    evaluation,
                    review_file=str(args.review_file),
                    ground_truth=args.ground_truth,
                )
            )
        else:
            print(format_evaluation(evaluations, review_file=str(args.review_file)))
        return 0
    if args.command == "review":
        try:
            run_review_app(args.review_file)
        except (GroundTruthError, InputDownloadError, ReviewFileError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    _print_progress("starting")
    load_dotenv(Path.cwd() / ".env")
    try:
        settings = resolve_settings(input_path=args.input_path)
        _print_progress(f"input source resolved; source={settings.input_source}")
        _print_progress("input: materializing source")
        with materialize_input(settings.input_source) as input_path:
            _print_progress(
                f"input ready; path={input_path}; bytes={input_path.stat().st_size}"
            )
            _print_progress("ingestion: reading and validating workbook")
            dataset = ingest_workbook(input_path, progress=_print_progress)
            answer_counts = Counter(answer.question_id for answer in dataset.answers)
            canonical_counts = Counter(
                answer.question_id for answer in dataset.processing_answers
            )
            duplicate_occurrences = len(dataset.answers) - len(
                dataset.processing_answers
            )
            _print_progress(
                "ingestion: complete; "
                f"questions={len(dataset.questions)}; "
                f"answers={len(dataset.answers)}; "
                f"canonical_answers={len(dataset.processing_answers)}; "
                f"duplicate_occurrences={duplicate_occurrences}; "
                f"warnings={len(dataset.warnings)}"
            )
            for question in dataset.questions:
                _print_progress(
                    "ingestion: question "
                    f"'{question.question_id}'; "
                    f"answers={answer_counts[question.question_id]}; "
                    f"canonical_answers={canonical_counts[question.question_id]}; "
                    f"existing_choices={len(question.choices)}"
                )

            _print_progress("embedding: resolving semantic discovery vectors")
            discovery_embeddings = embed_discovery_dataset(
                dataset,
                api_key=os.getenv("NEBIUS_API_KEY"),
                progress=_print_progress,
            )
            _print_progress("discovery: clustering canonical answers by question")
            discovery = discover_categories(
                dataset,
                embeddings=discovery_embeddings,
                progress=_print_progress,
            )
            discovery_statuses = Counter(point.status for point in discovery.points)
            _print_progress(
                "discovery: result received; "
                f"proposal_eligible_clusters={len(discovery.proposed_clusters)}; "
                f"unresolved={len(discovery.unresolved_processing_ids)}; "
                f"statuses={dict(sorted(discovery_statuses.items()))}"
            )

            _print_progress("classification: classifying eligible clusters with Gemini")
            classification = classify_clusters(
                dataset,
                discovery,
                api_key=os.getenv("GEMINI_API_KEY"),
                progress=_print_progress,
            )
            classification_decisions = Counter(
                proposal.decision for proposal in classification.proposals
            )
            _print_progress(
                "classification: result received; "
                f"clusters={len(classification.proposals)}; "
                f"decisions={dict(sorted(classification_decisions.items()))}; "
                f"provider_errors={classification.provider_error_count}; "
                f"warnings={len(classification.warnings)}"
            )

            _print_progress("review: validating and writing review JSON")
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
                **review_file.counts,
            }
            _print_progress(
                "review: created; "
                f"path={review_file.review_file_path}; "
                f"counts={dict(sorted(review_file.counts.items()))}"
            )
    except ConfigurationError as exc:
        _print_progress(f"failed during configuration; error={exc}")
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
        _print_progress(f"failed; error={exc}")
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in dataset.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for warning in classification.warnings:
        print(f"warning: {warning['message']}", file=sys.stderr)
    _print_progress("complete; final summary JSON follows on stdout")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
