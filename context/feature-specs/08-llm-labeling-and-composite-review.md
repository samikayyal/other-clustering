# Spec 08 — LLM Labeling and Composite Review

**Status:** Planned
**Dependencies:** Spec 02b, Spec 04, Spec 06, Spec 07
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

Compare each promoted cluster’s stable medoid embedding to existing-choice anchors in the same vector space. Apply separately configurable cluster-level similarity and margin thresholds; take their initial defaults from the Spec 02b calibration record rather than assuming answer-level thresholds transfer unchanged. Reclassify to an existing choice only when the cluster-level vector gates and structured-verifier gates agree. Otherwise retain the candidate as a proposed new category. Do not use generated bilingual labels as vectors, mutate the input choice sheet, or create an official codebook update.

## Composite-answer review

Use two stages:

1. Local screening using punctuation/conjunction patterns, strong affinity to multiple categories, and small top-category margins.
2. Rank all existing-choice anchors and promoted-cluster medoids in the same vector space.
3. Retain at most the top three candidates that pass a separately calibrated composite-candidate floor.
4. Structured Gemini verification only for screened candidates and only with that bounded candidate set.

Assignment rules:

- Every answer has at most one primary category.
- A verified composite sets `composite = true`, returns at most one primary category, and retains up to two ranked secondary suggestions as advisory evidence.
- Every returned primary or secondary must belong to the supplied top-three candidate set; a category outside the set is invalid structured output.
- If no defensible primary category exists, use an explicit unresolved status rather than forcing a choice.
- A language-detector warning alone never creates `unresolved_language`; that status requires an attempted original-language semantic path and an explicit semantic/review failure.

## Structured response rules

- Use operation-specific schemas rather than free-form text.
- Validate every response locally and retry failures according to the configured policy and the batch retry semantics below.
- Convert persistent item-level failures into unresolved/error records with retry count and provider error category.
- Batch independent judgments where the provider schema permits, but never issue one Gemini call per raw answer row.
- Count label and composite calls separately at the Spec 05 labeling/composite budget checkpoint, and account batches and singleton retries at their actual request cost in continuous spend enforcement.

## Batch retry semantics

Batched structured calls use a two-level failure taxonomy; retry granularity is a spec contract, not an implementation choice:

- **Batch composition is deterministic:** items are sorted by their stable IDs (`variant_id`, cluster ID) before batching, and batch size is a recorded configuration value.
- **Correlation is by explicit ID:** every request item carries its stable ID, the schema requires the ID in each result item, and results are matched by ID — never by array position.
- **Response-level failure** (transport error, non-JSON response, unparseable envelope): retry the whole batch under the configured retry policy. No per-item results existed, so nothing is discarded or re-decided.
- **Item-level failure** (the envelope parses but specific items fail schema, ID, or candidate-set validation): accept the valid items' results immediately — a validly answered item is never re-asked, so its outcome cannot change on a hosted-model retry — and retry only the failed items as singletons or a failed-items-only batch. These retries are budgeted at their actual (singleton) request cost.
- **Accounting:** the manifest records batch sizes, response-level retry counts, and item-level retry counts separately, and exhausted items become unresolved/error records individually.

## Implementation tasks

1. Define cluster-label, existing-choice-verification, and composite-verification schemas.
2. Implement native Arabic-script validation and bilingual field completeness checks.
3. Implement evidence selection and bounded structured generation orchestration.
4. Implement medoid-based cluster reclassification and proposed-category status logic with separate cluster thresholds.
5. Implement deterministic composite screening, top-three candidate bounding, verifier result handling, candidate-set validation, and secondary suggestions.

## Tests

- Required four-field bilingual schema and missing-field rejection.
- Arabic-script validation rejects Latin transliteration-only output and language fallback.
- Generated text cannot introduce a concept absent from supplied cluster evidence in the acceptance fixture.
- Label failure leaves a visible category-level error and proposal, not a missing category.
- Existing-choice reclassification uses stable medoids and requires separately calibrated cluster vector gates plus structured agreement.
- Generated labels are never used as vector representations.
- Composite screen filters candidates before generation, ranks anchors and medoids together, sends at most three candidates, and unscreened rows do not receive composite calls.
- Verified composites receive zero or one candidate-set-valid primary plus at most two candidate-set-valid advisory secondary suggestions.
- No defensible primary category becomes unresolved rather than forced.
- Malformed/failed provider responses retry and then become explicit unresolved/error records.
- A response-level failure retries the whole batch; an item-level failure preserves the valid items' results unchanged and retries only the failed items, with correlation by explicit ID.
- Batch composition is deterministic under input reordering, and manifest counters separate response-level from item-level retries.

## Acceptance criteria

- Every promoted cluster has either valid English/Arabic label and description fields or a visible labeling error.
- Every generated category remains proposed for analyst review.
- No answer is assigned to an existing choice or new category from an LLM response that fails local schema/language validation.
- Composite behavior is auditable through screen reason, verifier result, primary category, secondary suggestions, and unresolved reason where applicable.

## Non-goals

- Translation, automatic codebook mutation, analyst-feedback ingestion, category merging, or final XLSX/manifest assembly.
