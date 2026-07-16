# Spec 06 — Embeddings and Existing-Choice Matching

**Status:** Planned
**Dependencies:** Spec 03, Spec 04, Spec 05
**Implementation order:** 06 of 11

## Outcome

Eligible unique variants and existing-choice anchors are embedded in the same fixed original-language vector space. The application persists vectors in a canonical 4096-dimensional `float32` memmap and produces conservative existing-choice candidates that require both vector gates and structured Gemini verification before automatic assignment.

## Fixed embedding contract

Use Nebius `Qwen/Qwen3-Embedding-8B` for every eligible answer variant and choice anchor. The v1 instruction is:

```text
Task: represent this survey text for semantic clustering and category matching.
Preserve the meaning in the supplied language.
Do not translate, summarize, infer personal attributes, or add concepts.

Survey question:
{redacted_question_text}

Text:
{redacted_text}
```

Rules:

- Use the exact same instruction policy for every language and run unless the profile changes.
- Do not append detector labels, transliterations, language hints, or provider-specific tags.
- Serialize choice anchors from the redacted question, label, optional description, and newline-delimited examples under the same context.
- Embed the complete redacted answer. Do not application-truncate, chunk, summarize, or silently rewrite it.
- Count the complete serialized embedding input: fixed instruction, separators, redacted question, redacted answer or anchor, descriptions, and examples. Use the authenticated Nebius model/profile input capacity when available; otherwise apply the disclosed UTF-8 fallback and mark the estimate provisional. Do not hardcode an unverified input ceiling.
- If an individual answer exceeds the limit, record `input_too_long` locally and do not send it to the provider. An oversize question or choice anchor is a run-level input contract error because it prevents consistent matching for every answer.
- Preserve Arabic—including dialectal Arabic—and English in the supplied script; no translation or language-specific representation switch is allowed.

## Vector artifact contract

- Store answer-variant and choice-anchor vectors in one temporary run-local NumPy memmap with shape `(vector_count, 4096)` and dtype `float32`; atomically publish the canonical memmap only after every planned vector is present and verified.
- L2-normalize vectors and validate finite values, shape, dtype, and norm tolerance before persistence.
- Maintain a deterministic sidecar row map keyed by `variant_id` or `choice_id`.
- Record model ID, dimension, dtype, normalization, instruction identifier/SHA-256, row map, cache key, flush/checksum state, and source token count.
- Embed all mandatory choice anchors first. Then embed answer variants into the temporary memmap. If any anchor, answer batch, response shape, dimension, finite-value, or normalization check fails after bounded retries, stop the run, close and remove the incomplete temporary memmap, write a safe failure manifest/log with request counts, recorded cost, retries, and error category, and do not write the six-sheet result workbook.
- Flush and close the verified memmap before PCA/clustering or stage completion. Do not materialize a second full JSON vector matrix in cache, and do not implement missing-vector bitmaps or answer-level embedding recovery.
- Report the vector artifact’s byte size, checksum, shape, dtype, and peak memory diagnostics.

## Existing-choice matching

1. Embed all choice anchors in the same provider/profile/instruction space as answer variants before answer variants.
2. Calculate cosine similarity from each eligible unique variant to every existing choice.
3. Rank candidates and calculate the top-two margin.
4. Apply configurable initial gates: `similarity_min = 0.80` and `margin_min = 0.08`.
5. Send only vector-qualified unique variants to Gemini in bounded structured batches.
6. Automatically assign an existing `choice_id` only when Gemini returns an affirmative `match`, cites evidence from the answer and choice definition, and does not mark the answer composite or ambiguous.
7. Retain ranked suggestions and dispositions for all other variants without forcing an existing-choice assignment.

Use explicit statuses such as `assigned_existing`, `ambiguous_existing`, `no_existing_match`, and `existing_match_error`. Thresholds remain configurable and must be calibrated against the manually labeled gold fixture before the pilot.

## Implementation tasks

1. Implement exact answer/anchor serialization, complete-request token counting, and instruction hashing.
2. Implement anchor-first batched embedding orchestration and response validation with bounded retries.
3. Implement temporary memory-mapped vector creation, row map persistence, atomic publish, flush/checksum, and failure cleanup.
4. Implement cosine ranking, similarity/margin gates, and candidate records.
5. Implement bounded structured verifier calls through the provider interface.
6. Expose choice-match evidence for the `Choice Matches` and `Assignments` sheets.

## Tests

- Exact instruction and anchor serialization, including redacted question context.
- Original-language invariant and absence of translation/language labels in requests.
- 4096 length, `float32` dtype, L2 normalization, finite-value validation, and memmap row identity.
- Complete serialized-request token count, provider-profile input-capacity boundary or disclosed provisional fallback, `input_too_long` answer status, run-level oversize question/anchor rejection, and no truncation/chunking.
- Choice anchors are embedded before answer variants, and any exhausted embedding failure stops the run with no incomplete canonical vector artifact or six-sheet workbook.
- Duplicate variants embedded once and mapped back to every source row.
- Similarity and margin threshold gates, top-two ranking, and weak-match preservation.
- Structured verifier evidence, affirmative-match requirement, composite/ambiguous rejection, malformed-response retry, and item-level unresolved outcome.
- Instruction hash and serialization-policy changes change vector-cache identity.
- Memmap checksum, shape/dtype, flush, atomic publish, and incomplete-temporary-file cleanup behavior.

## Acceptance criteria

- A valid run produces one canonical vector row for every unique eligible answer variant sent to the provider and every choice anchor, with deterministic row mapping. Locally oversize answers remain explicit `input_too_long` outcomes.
- No automatic existing-choice assignment is made from vector similarity alone.
- Existing-choice matches remain traceable to similarity, margin, verifier verdict, and evidence.
- Vector artifacts are bounded by the configured memmap/working-memory design, atomically published, and validated before downstream use.

## Non-goals

- Discovering new categories, generating labels, composite screening, final source-row assignment, or output workbook generation.
