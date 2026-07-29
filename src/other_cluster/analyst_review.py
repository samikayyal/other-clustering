"""Thin analyst-review boundary over the single authoritative V1 file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .review_file import (
    apply_review_edits,
    complete_and_save_review_file,
    complete_review_document,
    load_review_file,
    save_review_file,
    update_and_save_review_file,
    validate_review_file,
)


def load_review(path: str | Path) -> dict[str, Any]:
    """Load one schema-version-2 review file."""

    return load_review_file(path)


def update_review(path: str | Path, payload: object) -> dict[str, Any]:
    """Apply editable analyst fields and atomically save the same file."""

    return update_and_save_review_file(path, payload)


def complete_review(path: str | Path, payload: object) -> dict[str, Any]:
    """Apply editable fields, allocate values, and atomically mark complete."""

    return complete_and_save_review_file(path, payload)


__all__ = [
    "apply_review_edits",
    "complete_review",
    "complete_review_document",
    "load_review",
    "load_review_file",
    "save_review_file",
    "update_review",
    "validate_review_file",
]
