# Spec 09 — Assignment and Audit Artifacts

**Status:** Planned
**Dependencies:** Spec 05, Spec 06, Spec 07, Spec 08
**Implementation order:** 09 of 11

## Outcome

The pipeline maps every source answer to exactly one explicit final assignment/status and writes a new six-sheet audit workbook plus a complete JSON manifest. Analysts can inspect raw local evidence, redacted provider-bound text, category decisions, unresolved reasons, and review samples without changing the input workbook.

## Exactly-one-output contract

Every `answer_id` must appear exactly once in `Assignments`, including:

- `assigned_existing`;
- `assigned_new`;
- `rare_candidate`;
- `unresolved_low_confidence`;
- `unresolved_ambiguous`;
- `unresolved_composite`;
- `unresolved_category_cap`;
- `input_too_long`;
- `unresolved_language` only after an attempted original-language semantic path and explicit semantic/review failure;
- `nonsemantic_marker`;
- `blank`;
- `provider_error`.

No row may disappear because it is blank, excluded from semantic calls, rare, noisy, ambiguous, composite, or affected by an individual provider failure.

## Result workbook

Create a new XLSX; never modify the input. Use these exact sheets. Every source-originated string, including formula-like strings beginning with `=`, `+`, `-`, or `@`, must be written as an XLSX text cell and never reinterpreted as a formula.

1. `Summary`
   - run status, question, provider/model IDs, counts, cost/budget, coverage, unresolved rate, redaction totals, language distribution, category totals, thresholds, warnings, and review instructions;
2. `Assignments`
   - `answer_id`, raw answer, variant ID, language hint/detection/confidence, redacted original-language analysis text, cleanup/removal summary, final status, primary category ID/type/label, confidence, composite flag, secondary suggestions, unresolved reason, review-sample flag, blank analyst-review columns, and all local passthrough metadata;
3. `Unique Variants`
   - variant ID, normalized form, row count, language fields, cleanup/redaction summaries, source token count, embedding model/dimension/dtype/instruction identifiers, memmap row, cache key, primary result, and confidence;
4. `Categories`
   - existing/new category ID and type, supplied existing-choice text, English/Arabic labels/descriptions, label-generation status, expanded and unique counts, membership statistics, original-language examples, anchor relationship, and `proposed_for_review`;
5. `Choice Matches`
   - ranked existing-choice candidates, cosine similarities, margins, structured verifier verdicts, evidence, and final disposition;
6. `Unresolved and Errors`
   - every unresolved answer/variant, pipeline stage, reason code, retry count, provider error category, and suggested analyst action.

Generated labels are bilingual evidence-grounded summaries. Existing choice text remains as supplied and is not silently translated.

## Review sample

Mark a deterministic sample of up to 500 rows in `Assignments`, stratified across:

- large and small promoted categories;
- existing-choice assignments;
- rare candidates;
- noise/unresolved answers;
- composite answers;
- frequent and rare variants;
- represented languages and detector-confidence groups.

Provide blank analyst columns for correctness, preferred category, category coherence, and notes. V1 writes these columns but does not ingest edits.

## Manifest contract

Write a versioned JSON manifest containing:

- run ID, schema version, status, timestamps, and stage statuses;
- input, configuration, prompt, profile, and output hashes;
- selected providers and exact model IDs/routes;
- model parameters, embedding dimension, dtype, normalization, and thresholds;
- Python, dependency, and `uv` versions;
- canonical ordering and seed rules;
- Lingua mode, restricted language set including `unknown`, and detection-after-deduplication policy;
- expansion cap and `min(occurrence_count, expansion_cap)` rule;
- counts at every pipeline stage;
- token/request usage, estimated cost, actual recorded cost, and budget;
- token-counting method ID, source/endpoint/request shape, tokenizer/model version, complete-request serialization hash, batch-counting policy, total-input limit, operation-specific output limits, structured-output billing policy, failure/retry billing policy, pricing unit/currency/rates/version/publication/effective dates/source, fallback estimator ID/formula, and disclosed fallback assumptions;
- redaction-rule hash and counts without credentials;
- original-language-only policy, language distribution, detector warnings, instruction identifier, and instruction SHA-256;
- vector path, shape, dtype, normalization, row map, flush/checksum status;
- clustering parameters, quality metrics, warnings, cache paths/counts;
- failure/circuit-breaker details, category-cap diagnostic status, and provisional-output reason where applicable;
- plain-language warning that the cache is persistent plaintext and may contain sensitive redacted survey content.

## Implementation tasks

1. Build a final assignment merger from variant outcomes back to all source rows.
2. Validate exactly-one-output traceability before writing.
3. Implement six-sheet workbook creation with safe string/formula handling and analyst columns.
4. Implement deterministic review-sample selection and strata accounting.
5. Implement versioned manifest serialization, output hashes, and artifact references.
6. Ensure manifest/workbook status distinguishes successful completion, category-cap provisional output, incomplete output, embedding-failure output without a result workbook, and diagnostic failure.

## Tests

- Every input `answer_id` appears exactly once, including all explicit edge statuses.
- Duplicate variants map to multiple source rows without duplicate semantic decisions.
- Six sheet names and required columns are exact and round-trip through `openpyxl`.
- Raw answer is preserved locally and redacted analysis text is distinct.
- Source-originated strings beginning with formula-like prefixes remain literal text on output round-trip.
- Passthrough metadata is copied unchanged only to local assignment output.
- Review sample is deterministic, capped at 500, stratified, and marked correctly.
- Bilingual fields are complete or carry a visible labeling error.
- Manifest contains required hashes, counts, model/profile details, token/pricing/serialization metadata, vector metadata, cost, warnings, category-cap status, and no credentials.
- Output hash/checksum changes when output content changes.
- A 100,000-row fixture can complete the workbook/manifest round trip within configured resource limits.

## Acceptance criteria

- A completed pipeline emits the six-sheet result workbook and JSON manifest, or emits a clearly marked provisional/incomplete diagnostic artifact with unresolved/error records. A failed embedding stage emits a safe manifest/log but no six-sheet workbook and no incomplete canonical vector artifact.
- Exactly-one-output traceability is validated before success is reported.
- Analysts can understand why each row was assigned, left unresolved, excluded from semantic calls, or proposed for review.
- No output artifact claims to have ingested analyst edits in v1.

## Non-goals

- Updating the source workbook, official choices, persistent category registries, or analyst feedback.
