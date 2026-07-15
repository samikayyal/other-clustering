# Spec 08 — LLM Labeling and Composite Review

**Status:** Planned
**Dependencies:** Spec 04, Spec 06, Spec 07
**Implementation order:** 08 of 11

## Outcome

Promoted new clusters receive evidence-grounded bilingual labels through direct Google Gemini, clusters are conservatively compared with existing choices, and screened multi-concept answers receive structured composite verification. No generated label mutates the input workbook or official choice list.

## Bilingual category labeling

For every promoted cluster:

- Send only redacted representative examples, medoids, boundary evidence, question context, and required anchor context.
- Request all four fields: `label_en`, `description_en`, `label_ar`, and `description_ar`.
- Require concise evidence-grounded summaries that introduce no concept absent from cluster members.
- Validate that English fields are English-oriented and Arabic fields contain native Arabic script; Latin transliteration is invalid.
- Treat labels as parallel bilingual category summaries, not translations of individual stored answers.
- If labeling fails after retries, keep the category proposed with an explicit labeling error rather than silently substituting or dropping it.
- Mark all discovered labels `proposed_for_review`.

## Existing-choice relationship

Compare each promoted cluster to existing choices using the same conservative vector and structured-verifier gates as Spec 06. Reclassify to an existing choice only when both gates agree. Otherwise retain the candidate as a proposed new category. Do not mutate the input choice sheet or create an official codebook update.

## Composite-answer review

Use two stages:

1. Local screening using punctuation/conjunction patterns, strong affinity to multiple categories, and small top-category margins.
2. Structured Gemini verification only for screened candidates.

Assignment rules:

- Every answer has at most one primary category.
- A verified composite sets `composite = true` and retains ranked secondary suggestions as advisory evidence.
- If no defensible primary category exists, use an explicit unresolved status rather than forcing a choice.
- A language-detector warning alone never creates `unresolved_language`; that status requires an attempted original-language semantic path and an explicit semantic/review failure.

## Structured response rules

- Use operation-specific schemas rather than free-form text.
- Validate every response locally and retry malformed responses according to the configured policy.
- Convert persistent item-level failures into unresolved/error records with retry count and provider error category.
- Batch independent judgments where the provider schema permits, but never issue one Gemini call per raw answer row.
- Count label and composite calls separately in the preflight budget.

## Implementation tasks

1. Define cluster-label, existing-choice-verification, and composite-verification schemas.
2. Implement native Arabic-script validation and bilingual field completeness checks.
3. Implement evidence selection and bounded structured generation orchestration.
4. Implement cluster reclassification and proposed-category status logic.
5. Implement deterministic composite screening, verifier result handling, and secondary suggestions.

## Tests

- Required four-field bilingual schema and missing-field rejection.
- Arabic-script validation rejects Latin transliteration-only output and language fallback.
- Generated text cannot introduce a concept absent from supplied cluster evidence in the acceptance fixture.
- Label failure leaves a visible category-level error and proposal, not a missing category.
- Existing-choice reclassification requires both vector and structured agreement.
- Composite screen filters candidates before generation; unscreened rows do not receive composite calls.
- Verified composites receive one primary category plus ranked secondary suggestions.
- No defensible primary category becomes unresolved rather than forced.
- Malformed/failed provider responses retry and then become explicit unresolved/error records.

## Acceptance criteria

- Every promoted cluster has either valid English/Arabic label and description fields or a visible labeling error.
- Every generated category remains proposed for analyst review.
- No answer is assigned to an existing choice or new category from an LLM response that fails local schema/language validation.
- Composite behavior is auditable through screen reason, verifier result, primary category, secondary suggestions, and unresolved reason where applicable.

## Non-goals

- Translation, automatic codebook mutation, analyst-feedback ingestion, category merging, or final XLSX/manifest assembly.
