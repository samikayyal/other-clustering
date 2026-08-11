"""Local-only Flask application for review artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from .errors import ReviewConflictError, ReviewFileError
from .review_file import (
    apply_and_save_review_command,
    load_review_file,
)
from .review_progress import project_review_progress


def create_review_app(
    review_file_path: Path,
    *,
    working_directory: Path | None = None,
) -> Flask:
    """Create the single-file local analyst review application."""

    path = Path(review_file_path).expanduser().resolve()
    # Fail before starting a browser server so schema-version-1 artifacts and
    # malformed files receive the explicit new-analysis message.
    load_review_file(path)
    root = (working_directory or Path.cwd()).resolve()
    app = Flask(__name__)
    app.config.update(
        REVIEW_FILE_PATH=path,
        WORKING_DIRECTORY=root,
    )

    @app.get("/")
    def index():
        document = load_review_file(path)
        read_only = document["schema_version"] == 3 or document["status"] == "complete"
        return render_template(
            "review.html",
            review=document,
            review_progress=_review_progress(document),
            review_file_path=str(path),
            read_only=read_only,
            legacy=document["schema_version"] == 3,
        )

    @app.get("/api/state")
    def state():
        document = load_review_file(path)
        return jsonify(
            {
                "review": document,
                "progress": _review_progress(document),
                "review_file": str(path),
                "read_only": document["schema_version"] == 3
                or document["status"] == "complete",
            }
        )

    @app.post("/api/commands")
    def command():
        document = apply_and_save_review_command(path, _json_object())
        return jsonify(
            {
                "review": document,
                "progress": project_review_progress(document),
                "review_file": str(path),
            }
        )

    @app.errorhandler(ReviewConflictError)
    def review_conflict(exc: ReviewConflictError):
        return jsonify({"error": str(exc)}), 409

    @app.errorhandler(ReviewFileError)
    def review_error(exc: ReviewFileError):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 400
        return render_template("review_error.html", message=str(exc)), 400

    return app


def run_review_app(review_file_path: Path) -> None:
    """Run the fixed local-only review server."""

    app = create_review_app(review_file_path)
    app.run(host="127.0.0.1", port=5000, debug=False)


def _json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ReviewFileError("request body must be one JSON object")
    return payload


def _review_progress(document: dict[str, Any]) -> dict[str, Any] | None:
    if document["schema_version"] != 4:
        return None
    return project_review_progress(document)
