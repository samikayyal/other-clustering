"""Pydantic records shared across application boundaries."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, Field

from other_cluster.domain.statuses import (
    AssignmentStatus,
    ManifestStatus,
    MatchDisposition,
    PreprocessingStatus,
    ProviderOperation,
    ProviderOutcome,
    ReviewStatus,
)

PrimitiveValue: TypeAlias = str | int | float | bool | None


class QuestionSpec(BaseModel):
    question_id: str
    wording: str


class ChoiceAnchor(BaseModel):
    choice_id: str
    label: str
    description: str | None = None
    examples: list[str] = Field(default_factory=list)


class AnswerRecord(BaseModel):
    answer_id: str
    raw_text: str
    language_hint: str | None = None
    passthrough_metadata: dict[str, PrimitiveValue] = Field(default_factory=dict)


class NormalizedVariant(BaseModel):
    variant_id: str
    normalized_text: str
    occurrence_count: int = Field(ge=1)
    source_answer_ids: list[str] = Field(min_length=1)
    status: PreprocessingStatus


class LanguageAssessment(BaseModel):
    source_hint: str | None = None
    detected_language: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    detector_mode: str
    warning: str | None = None


class ProviderRequestRecord(BaseModel):
    provider: str
    model: str
    operation: ProviderOperation
    redaction_policy_id: str
    profile_id: str
    request_checksum: str
    usage: dict[str, int] = Field(default_factory=dict)
    outcome: ProviderOutcome


class ChoiceCandidate(BaseModel):
    choice_id: str
    similarity: float


class ExistingChoiceMatch(BaseModel):
    variant_id: str
    ranked_candidates: list[ChoiceCandidate] = Field(default_factory=list)
    margin: float | None = None
    verifier_result: bool | None = None
    disposition: MatchDisposition


class ClusterCandidate(BaseModel):
    cluster_id: str
    member_variant_ids: list[str] = Field(min_length=1)
    member_count: int = Field(ge=1)
    membership_probability: float | None = Field(default=None, ge=0, le=1)
    examples: list[str] = Field(default_factory=list)
    review_status: ReviewStatus


class BilingualCategoryLabel(BaseModel):
    label_en: str
    description_en: str
    label_ar: str
    description_ar: str
    validation_status: ReviewStatus


class Assignment(BaseModel):
    answer_id: str
    status: AssignmentStatus
    primary_category_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    is_composite: bool = False
    secondary_category_ids: list[str] = Field(default_factory=list)
    unresolved_reason: str | None = None


class ReviewRecord(BaseModel):
    answer_id: str
    sample_rank: int = Field(ge=1)
    sample_stratum: str
    analyst_decision: str | None = None
    analyst_notes: str | None = None


class RunManifest(BaseModel):
    manifest_version: str
    run_id: str
    status: ManifestStatus
    input_checksum: str | None = None
    configuration_checksum: str | None = None
