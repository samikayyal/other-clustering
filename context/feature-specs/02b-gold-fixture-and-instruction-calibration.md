# Spec 02b — Gold Fixture and Embedding-Instruction Calibration

**Status:** Planned
**Dependencies:** Spec 02 (workbook format only)
**Implementation order:** Parallel track. The fixture is a labeling exercise with no code dependencies beyond the Spec 02 template. It must be complete before Spec 06 freezes the embedding instruction, and before the Spec 06–08 similarity/margin/membership thresholds are frozen.

## Outcome

A seeded, manually labeled Arabic-plus-English gold fixture exists early in the project, and an embedding-instruction selection experiment chooses the v1 instruction and the initial vector-gate defaults from observed data — before the instruction becomes a fingerprint input that is expensive to change. Specs 06, 07, 08, and 11 consume this fixture; none of them create it.

## Gold fixture contract

Create a seeded, manually labeled fixture using the Spec 02 workbook format:

- Roughly 20–30 semantic intents with 3–5 human-labeled variants per intent.
- Include spelling errors, short answers, blanks/refusals, existing-choice matches, new-category cases, rare meanings, and multi-concept answers.
- Language scope: Arabic — including representative Modern Standard Arabic and dialectal Arabic answers — and English. Include Arabic orthographic variance (hamza/alef seat variants, taa marbuta/haa, tatweel, Arabic-Indic digits) so grouping-key and redaction behavior can be evaluated.
- Store truth in a separate JSON file keyed by `answer_id`; each row carries an expected disposition and, where applicable, a human-defined semantic `intent_id`.
- Do not create the gold set through automatic translation.
- Keep the gold file outside the production workbook contract and do not expose it as a public CLI input in v1.
- The fixture content must be synthetic or fully non-sensitive; it will be sent to live providers during calibration.

## Embedding-instruction selection experiment

Before the Spec 06 instruction is frozen into the fingerprint:

1. Serialize the fixture's answers and choice anchors under at least three candidate instruction templates:
   - question context included in every answer and anchor (the current Spec 06 draft);
   - no question context in any text;
   - question context in choice anchors only.
2. Embed each variant set through the live Nebius `Qwen/Qwen3-Embedding-8B` profile. This is a small, bounded, paid spend on non-sensitive data and requires credentials; record its cost.
3. For each candidate, measure and record:
   - within-intent versus cross-intent cosine similarity distributions;
   - answer-to-anchor ranking quality for the known existing-choice matches (top-1 accuracy and top-two margin distributions);
   - the baseline (cross-intent) similarity level, to detect shared-prefix compression of the cosine range.
4. Select the v1 instruction from the observed separation, and record the decision, the distributions, and the rejected candidates in a calibration record under `context/`.
5. Derive the initial defaults for `similarity_min`, `margin_min`, the Spec 07 membership-probability threshold, the Spec 08 cluster-level gates, and the composite-candidate floor from the observed distributions. Record each value with the distribution evidence behind it.

## Calibration caveat

A 20–30-intent fixture is a small calibration set; the derived thresholds are informed starting points, not statistically tight estimates. The calibration record must state this explicitly. The purpose of this spec is that no gate ships having never touched data, and that the instruction — the one input that is effectively irreversible once fingerprinted — is chosen from evidence.

## Deliverables

- Fixture workbook plus truth JSON, stored outside the production workbook contract.
- Calibration record: candidate instructions, similarity distributions, ranking metrics, selected instruction and its SHA-256, derived threshold defaults with evidence, spend record, and the small-sample caveat.
- Updated defaults referenced by Specs 06, 07, and 08.

## Acceptance criteria

- The fixture exists and satisfies the content contract above before Spec 06 implementation freezes the instruction text.
- The Spec 06 instruction hash matches the instruction selected here.
- Every vector-gate default in Specs 06–08 traces to the calibration record rather than to an assumed constant.
- Spec 11's pilot evaluation consumes this fixture unchanged (aside from additive rows) rather than creating a new one.

## Non-goals

- Application code, provider adapters, thresholds tuning automation, or any production run behavior. Broader language coverage is deferred until real data justifies it.
