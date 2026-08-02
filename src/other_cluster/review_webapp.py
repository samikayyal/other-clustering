"""Local-only Flask application for the schema-version-3 review file."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from .errors import ReviewFileError
from .ground_truth_evaluation import evaluate_ground_truth_file
from .review_file import (
    complete_and_save_review_file,
    load_review_file,
    update_and_save_review_file,
)


def create_review_app(
    review_file_path: Path,
    *,
    working_directory: Path | None = None,
    ground_truth_source: str | Path | None = None,
) -> Flask:
    """Create the single-file local analyst review application."""

    path = Path(review_file_path).expanduser().resolve()
    # Fail before starting a browser server so schema-version-1 artifacts and
    # malformed files receive the explicit new-analysis message.
    load_review_file(path)
    ground_truth_evaluation = (
        asdict(evaluate_ground_truth_file(path, ground_truth_source))
        if ground_truth_source is not None
        else None
    )
    root = (working_directory or Path.cwd()).resolve()
    app = Flask(__name__)
    app.config.update(
        REVIEW_FILE_PATH=path,
        WORKING_DIRECTORY=root,
        GROUND_TRUTH_EVALUATION=ground_truth_evaluation,
        GROUND_TRUTH_SOURCE=(
            str(ground_truth_source) if ground_truth_source is not None else None
        ),
    )

    @app.get("/")
    def index():
        document = load_review_file(path)
        return render_template(
            "review.html",
            review=document,
            review_file_path=str(path),
            read_only=document["status"] == "complete",
            ground_truth_evaluation=ground_truth_evaluation,
            ground_truth_source=app.config["GROUND_TRUTH_SOURCE"],
        )

    @app.get("/api/state")
    def state():
        document = load_review_file(path)
        return jsonify(
            {
                "review": document,
                "review_file": str(path),
                "read_only": document["status"] == "complete",
                "ground_truth_evaluation": ground_truth_evaluation,
                "ground_truth_source": app.config["GROUND_TRUTH_SOURCE"],
            }
        )

    @app.put("/api/review")
    def update():
        document = update_and_save_review_file(path, _json_object())
        return jsonify({"review": document, "review_file": str(path)})

    @app.post("/api/complete")
    def complete():
        document = complete_and_save_review_file(path, _json_object())
        return jsonify({"review": document, "review_file": str(path)})

    @app.errorhandler(ReviewFileError)
    def review_error(exc: ReviewFileError):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 400
        return render_template("review_error.html", message=str(exc)), 400

    return app


def run_review_app(
    review_file_path: Path, ground_truth_source: str | Path | None = None
) -> None:
    """Run the fixed local-only review server."""

    app = create_review_app(review_file_path, ground_truth_source=ground_truth_source)
    app.run(host="127.0.0.1", port=5000, debug=False)


def _json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ReviewFileError("request body must be one JSON object")
    return payload
