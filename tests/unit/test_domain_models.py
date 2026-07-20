from other_cluster.domain import AnswerRecord, NormalizedVariant, PreprocessingStatus
from other_cluster.domain.models import (
    Assignment,
    BilingualCategoryLabel,
    ChoiceAnchor,
    ChoiceCandidate,
    ClusterCandidate,
    ExistingChoiceMatch,
    LanguageAssessment,
    ProviderRequestRecord,
    QuestionSpec,
    ReviewRecord,
    RunManifest,
)
from other_cluster.domain.statuses import (
    AssignmentStatus,
    ManifestStatus,
    MatchDisposition,
    ProviderOperation,
    ProviderOutcome,
    ReviewStatus,
)


def test_models_round_trip_and_preserve_string_ids():
    answer = AnswerRecord(
        answer_id="0012", raw_text="Original answer", passthrough_metadata={"wave": 1}
    )
    restored = AnswerRecord.model_validate_json(answer.model_dump_json())
    assert restored.answer_id == "0012"
    assert restored.passthrough_metadata == {"wave": 1}

    variant = NormalizedVariant(
        variant_id="variant-0012",
        normalized_text="normalized answer",
        occurrence_count=1,
        source_answer_ids=["0012"],
        status=PreprocessingStatus.ELIGIBLE,
    )
    assert variant.model_dump(mode="json")["source_answer_ids"] == ["0012"]
    assert (
        QuestionSpec(question_id="q-01", wording="Question?").model_dump()[
            "question_id"
        ]
        == "q-01"
    )


def test_remaining_domain_models_round_trip():
    models = [
        ChoiceAnchor(choice_id="c-01", label="Choice"),
        LanguageAssessment(detector_mode="restricted"),
        ProviderRequestRecord(
            provider="nebius",
            model="model",
            operation=ProviderOperation.EMBED,
            redaction_policy_id="r1",
            profile_id="p1",
            request_checksum="abc",
            outcome=ProviderOutcome.SUCCESS,
        ),
        ExistingChoiceMatch(
            variant_id="v-01",
            ranked_candidates=[ChoiceCandidate(choice_id="c-01", similarity=0.9)],
            disposition=MatchDisposition.ASSIGNED,
        ),
        ClusterCandidate(
            cluster_id="NEW-001",
            member_variant_ids=["v-01"],
            member_count=1,
            review_status=ReviewStatus.PENDING,
        ),
        BilingualCategoryLabel(
            label_en="Food",
            description_en="Food answers",
            label_ar="طعام",
            description_ar="إجابات الطعام",
            validation_status=ReviewStatus.PENDING,
        ),
        Assignment(answer_id="0012", status=AssignmentStatus.UNRESOLVED),
        ReviewRecord(answer_id="0012", sample_rank=1, sample_stratum="unresolved"),
        RunManifest(
            manifest_version="1", run_id="run-01", status=ManifestStatus.STARTED
        ),
    ]
    for model in models:
        assert type(model).model_validate_json(model.model_dump_json()) == model
