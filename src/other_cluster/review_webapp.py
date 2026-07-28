"""Local-only Flask application for Feature 06 analyst review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from .analyst_review import (
    add_analyst_category,
    complete_review,
    load_or_create_draft,
    load_review_package,
    save_draft,
)
from .errors import AnalystReviewError


def create_review_app(
    review_package_path: Path,
    *,
    working_directory: Path | None = None,
) -> Flask:
    """Create the single-package local analyst review application."""

    root = (working_directory or Path.cwd()).resolve()
    loaded = load_review_package(review_package_path)
    state_directory = root / "review_state"
    approval_directory = root / "review_approvals"
    app = Flask(__name__)
    app.config.update(
        REVIEW_PACKAGE=loaded,
        REVIEW_STATE_DIRECTORY=state_directory,
        REVIEW_APPROVAL_DIRECTORY=approval_directory,
    )

    @app.get("/")
    def index():
        draft = load_or_create_draft(loaded, state_directory)
        return render_template(
            "review.html",
            package=loaded.package,
            draft=draft,
            package_path=str(loaded.path),
            package_sha256=loaded.sha256,
        )

    @app.get("/api/state")
    def state():
        return jsonify(
            {
                "package": loaded.package,
                "review_package_sha256": loaded.sha256,
                "draft": load_or_create_draft(loaded, state_directory),
            }
        )

    @app.put("/api/draft")
    def update_draft():
        payload = _json_object()
        saved, path = save_draft(loaded, payload, state_directory)
        return jsonify({"draft": saved, "draft_path": str(path)})

    @app.post("/api/categories")
    def create_category():
        payload = _json_object()
        if set(payload) != {
            "draft",
            "question_id",
            "english_label",
            "arabic_label",
            "origin",
            "component_cluster_ids",
            "member_processing_ids",
        }:
            raise AnalystReviewError("category request has an invalid schema")
        draft, category_id = add_analyst_category(
            loaded,
            payload["draft"],
            question_id=payload["question_id"],
            english_label=payload["english_label"],
            arabic_label=payload["arabic_label"],
            origin=payload["origin"],
            component_cluster_ids=payload["component_cluster_ids"],
            member_processing_ids=payload["member_processing_ids"],
        )
        saved, path = save_draft(loaded, draft, state_directory)
        return jsonify(
            {
                "draft": saved,
                "draft_path": str(path),
                "final_category_id": category_id,
            }
        )

    @app.post("/api/complete")
    def complete():
        payload = _json_object()
        saved, draft_destination = save_draft(loaded, payload, state_directory)
        approval, destination = complete_review(loaded, saved, approval_directory)
        return jsonify(
            {
                "approval": approval,
                "approval_path": str(destination),
                "draft_path": str(draft_destination),
            }
        )

    @app.errorhandler(AnalystReviewError)
    def review_error(exc: AnalystReviewError):
        if request.path.startswith("/api/"):
            return jsonify({"error": str(exc)}), 400
        return render_template("review_error.html", message=str(exc)), 400

    return app


def run_review_app(review_package_path: Path) -> None:
    """Run the fixed local-only review server."""

    app = create_review_app(review_package_path)
    app.run(host="127.0.0.1", port=5000, debug=False)


def _json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise AnalystReviewError("request body must be one JSON object")
    return payload
