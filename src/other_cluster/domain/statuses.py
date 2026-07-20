"""Explicit statuses used by domain contracts."""

from enum import StrEnum


class PreprocessingStatus(StrEnum):
    ELIGIBLE = "eligible"
    BLANK = "blank"
    NON_SEMANTIC = "non_semantic"


class ProviderOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class ProviderOperation(StrEnum):
    EMBED = "embed"
    VERIFY_EXISTING_CHOICE = "verify_existing_choice"
    LABEL_CATEGORY = "label_category"
    REVIEW_COMPOSITE = "review_composite"


class MatchDisposition(StrEnum):
    ASSIGNED = "assigned"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AssignmentStatus(StrEnum):
    ASSIGNED = "assigned"
    UNRESOLVED = "unresolved"


class ManifestStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
