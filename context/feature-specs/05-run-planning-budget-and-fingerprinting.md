# Spec 05 — Run Planning, Budget, and Fingerprinting

**Status:** Planned
**Dependencies:** Spec 02, Spec 03, Spec 04
**Implementation order:** 05 of 11

## Outcome

Before semantic work begins, the application produces a deterministic local request/cost plan and a run fingerprint. Only `run` loads credentials and performs live provider capability checks. Any structural, capability, or conservative budget failure stops before paid calls; local commands do not create production run state.

## Command boundaries and run preflight

`validate` parses and validates the workbook/configuration locally without requiring credential values, making provider calls, creating a paid request plan, or creating production run state.

`estimate` runs validation and deterministic preprocessing, counts the complete serialized requests using pinned local token/pricing metadata, and reports a conservative cost estimate. It makes no provider calls and creates no production run state. Until the readiness gate is satisfied, its result is explicitly provisional and cannot authorize a hard-budget run.

`preview` runs a bounded deterministic sample and reports normalization, redaction, deduplication, language, and input-quality diagnostics. It makes no embeddings or Gemini calls and creates no production run state.

### `run`

1. Parse and validate the workbook and TOML contract locally.
2. Run deterministic preprocessing and collect eligible unique variants, mandatory choice anchors, counts, languages, complete serialized request sizes, redaction warnings, and cleanup summaries.
3. Canonicalize configuration, model profiles, exact prompt/instruction/schema text, cleanup/redaction rules, supported language set, the researched token-counting policy, pricing metadata, and package/runtime metadata.
4. Hash workbook content, normalized configuration, profiles, prompts/schemas, package versions, cleanup policy, redaction policy, token-counting/serialization policy, and pricing publication/effective metadata. Record `embedding_instruction_sha256` separately.
5. Create the run ID and run-artifact directory. Only `run` may create production run state.
6. Load credentials and ask both selected providers to verify the configured model ID, endpoint route, embedding dimension, structured-schema behavior, and live capability.
7. For Google, use the authenticated free `countTokens` endpoint on each complete canonical structured request during run preflight; for Nebius, use the documented fallback until the successful embedding response supplies `usage.prompt_tokens`. Build a conservative request plan for embeddings, existing-choice verifiers, promoted-cluster labels, composite reviews, retries, maximum operation-specific output tokens, and the configured retry reserve.
8. Compare the upper-bound estimate with the hard per-run budget.
9. Refuse to begin semantic calls if required pricing/token metadata is absent, credentials are missing, live capability checks fail, or the estimate exceeds the budget.

## Token-counting and pricing research result

The detailed provider research is recorded in [`context/provider-token-billing.md`](../provider-token-billing.md), with an official-source URL and retrieval/update date for each material claim. The result is:

- Nebius embeddings use successful `/v1/embeddings` response `usage.prompt_tokens` as the authoritative post-call count. No standalone official embedding counter was found. Nebius rate limits are dynamic and must be captured from response headers; the selected model's public numeric price and failed-request billing rule still require an authenticated account/catalog snapshot.
- Google generation uses authenticated `POST https://generativelanguage.googleapis.com/v1beta/{model=models/*}:countTokens` over the complete canonical `GenerateContentRequest`. Google states that count calls are not billed and do not count against inference quota. The selected Standard `gemini-3.5-flash` pricing snapshot is `$1.50` per 1M input tokens and `$9.00` per 1M output tokens including thinking tokens, with the page last updated 2026-07-09 UTC.
- Structured-output schemas are counted as request input and generated JSON/thinking tokens as output under the normal Gemini rates; there is no separate structured-output tariff in the selected pricing profile.
- The application output caps are `256` tokens for existing-choice verification, `512` for promoted-cluster bilingual labeling, and `512` for composite review. These are conservative application limits below Google's published `65,536` model maximum and are fingerprinted profile fields.
- When an official counter is unavailable, the disclosed provisional fallback is `max(1, ceil(len(canonical_request_utf8_bytes) / 2))`, including the complete serialized request. The fallback is not tokenizer-authoritative and cannot by itself make the hard-budget calculation implementation-ready.

### Hard-budget readiness status

The research gate is documented, but the hard-budget calculation is **not implementation-ready**. A paid run remains blocked until the authenticated Nebius price snapshot, Nebius failure-billing answer, live model/array-input capability confirmation, and the synthetic Google count-versus-usage fixture are recorded. Any estimate produced earlier is provisional, carries the fallback and pricing status, and cannot authorize a hard-budget run.

## Cost and request planning rules

- Count one embedding operation per unique eligible variant plus every choice anchor.
- Count the worst-case vector-qualified existing-choice verification items.
- Count promoted-cluster labeling and screened composite-review calls separately.
- Count the complete serialized embedding input, including fixed instruction, separators, redacted question, redacted answer or anchor, descriptions, and examples. Use Nebius response usage for reconciliation; use the disclosed UTF-8 fallback only when preflight counting is unavailable, and take the provider request limit/capability from the authenticated model check rather than from a hardcoded legacy value.
- Count each complete structured-generation request, including system instructions, schemas, tools, messages, and configuration, through the Google `countTokens` method during run preflight, or use a pinned count snapshot/local fallback for the offline `estimate` command. Add the operation-specific maximum output tokens. Any fallback use carries a visible provisional status.
- Include configured retry limits and a 20% retry reserve in the conservative estimate. Treat unknown Nebius failures and Google failures other than documented 400/500 responses as potentially billable; successful retries are new billable attempts.
- Do not silently skip a required verifier because candidate volume is high. If the configured verification cap cannot cover a candidate within budget, leave it explicitly review-required/unresolved rather than assigning from a vector score alone.
- Record estimated and actual usage/cost separately; no provider call may occur before budget approval.
- `estimate` makes no paid semantic calls. Provider capability checks for estimate must use local profile metadata or an explicitly non-paid capability path.

## Fingerprint contract

The run fingerprint must change when any of these change:

- input workbook content;
- canonical TOML configuration;
- provider identity, endpoint, exact model ID, model parameters, or pricing profile;
- exact embedding/generation prompts or schemas;
- embedding dimension, dtype, normalization, or instruction;
- deterministic normalization, Unicode/emoji data, non-semantic, or redaction rules;
- token-counting method, serialized-request policy, total-input limit, tokenizer/model version, pricing unit/version/publication date, and operation output limits;
- token-count source/endpoint/request shape, batch-counting policy, structured-output billing policy, failure/retry billing policy, fallback estimator ID/formula, and the pricing source/effective timestamp;
- package/runtime metadata that affects serialized behavior.

The manifest and provider-cache records retain these hashes and the selected profile/pricing metadata. They describe one run’s semantic contract; v1 does not implement interrupted-run continuation or compatible artifact reuse. Hosted-model output variance must still be reported rather than hidden.

## Implementation tasks

1. Define canonical serialization and hash utilities with stable key/order behavior, including request serialization hashes.
2. Create `RequestPlan`, `CostEstimate`, `CapabilityReport`, and preflight result models.
3. Add the provider token-counting/pricing research record from [`context/provider-token-billing.md`](../provider-token-billing.md), explicit fallback fields, and readiness blockers before implementing hard-budget enforcement.
4. Implement request-count calculations from unique variants, anchors, complete serialized inputs, cluster bounds, verification caps, operation output limits, retries, and reserve.
5. Implement run ID/run-artifact directory creation only for `run`, without writing credentials or raw provider payloads.
6. Implement local estimate output and run-only live capability/budget preflight with safe diagnostics.

## Tests

- Equal canonical inputs produce equal hashes and request plans.
- Any fingerprint input change changes the expected hash, including instruction, serialization, token-counting, and pricing-version changes.
- `validate`, `estimate`, and `preview` do not require credentials, make zero provider calls, and create no production run state.
- `run` requires credentials and live capability checks before any semantic call.
- Cost estimates include complete serialized inputs, embeddings, verifier/label/composite calls, operation output limits, retries, and the retry reserve.
- Missing, provisional, or unknown pricing/token/failure-billing metadata is visible and prevents a paid run when hard-budget enforcement cannot be trusted.
- The manifest fingerprints the exact counting method, endpoint/request shape, pricing version/source/effective date, batch policy, failure/retry billing policy, fallback estimator, and operation output limits.
- Budget overrun makes zero paid calls and returns the budget-rejection category.
- Candidate overflow becomes explicit review-required/unresolved rather than vector-only assignment.
- Provider capability failure stops preflight and writes safe diagnostics.
- Only `run` creates a run ID and production run-artifact directory.
- No credential or raw unredacted answer text appears in request plans, hash diagnostics, or manifests.

## Acceptance criteria

- `estimate` reports a reproducible local plan and never makes a paid semantic call.
- `preview` reports bounded local diagnostics and never makes an embedding or generation call.
- `run` cannot enter embedding/generation stages until validation, capability, and budget preflight pass.
- The run manifest records all semantic-contract, token-counting, serialization, pricing, and stage-status fields needed to audit the run.
- `run` cannot claim hard-budget approval while the Nebius authenticated price/failure-billing snapshot or required provider capability fixture is missing.
- Changing the embedding instruction changes the run fingerprint and vector-cache identity.

## Non-goals

- Executing embedding or generation calls, clustering, assignment, or writing the final workbook.
