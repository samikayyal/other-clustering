# Spec 05 — Run Planning, Budget, and Fingerprinting

**Status:** Planned
**Dependencies:** Spec 02, Spec 03, Spec 04
**Implementation order:** 05 of 11

## Outcome

Before semantic work begins, the application produces a deterministic request/cost plan, verifies provider capability, creates a run identity, and records compatibility hashes. Any structural, capability, or conservative budget failure stops before paid calls.

## Preflight sequence

For `estimate`, `preview`, `run`, and compatible `resume` paths:

1. Parse and validate the workbook and TOML contract.
2. Run deterministic preprocessing and collect eligible unique variants, choice anchors, counts, languages, token sizes, redaction warnings, and cleanup summaries.
3. Canonicalize configuration, model profiles, exact prompt/instruction text, cleanup/redaction rules, supported language set, and package/runtime metadata.
4. Hash workbook content, normalized configuration, profiles, prompts, package versions, cleanup policy, and redaction policy. Record `embedding_instruction_sha256` separately.
5. Create a run ID and run-local checkpoint/output paths.
6. Ask both selected providers to verify the configured model ID, endpoint route, embedding dimension, structured-schema behavior, and capability/pricing metadata.
7. Build a conservative request plan for embeddings, existing-choice verifiers, promoted-cluster labels, composite reviews, retries, and the 20% retry reserve.
8. Compare the upper-bound estimate with the hard per-run budget.
9. Refuse to continue if required pricing metadata is absent or the estimate exceeds the budget.

## Cost and request planning rules

- Count one embedding operation per unique eligible variant plus every choice anchor.
- Count the worst-case vector-qualified existing-choice verification items.
- Count promoted-cluster labeling and screened composite-review calls separately.
- Include configured retry limits and a 20% retry reserve in the conservative estimate.
- Do not silently skip a required verifier because candidate volume is high. If the configured verification cap cannot cover a candidate within budget, leave it explicitly review-required/unresolved rather than assigning from a vector score alone.
- Record estimated and actual usage/cost separately; no provider call may occur before budget approval.
- `estimate` makes no paid semantic calls. Provider capability checks for estimate must use local profile metadata or an explicitly non-paid capability path.

## Fingerprint and compatibility contract

The compatibility fingerprint must change when any of these change:

- input workbook content;
- canonical TOML configuration;
- provider identity, endpoint, exact model ID, model parameters, or pricing profile;
- exact embedding/generation prompts or schemas;
- embedding dimension, dtype, normalization, or instruction;
- deterministic normalization, Unicode/emoji data, non-semantic, or redaction rules;
- package/runtime metadata that affects serialized behavior.

Resume and cache reuse must reject incompatible hashes. Hosted-model output variance may still exist when all hashes match and must be reported rather than hidden.

## Implementation tasks

1. Define canonical serialization and hash utilities with stable key/order behavior.
2. Create `RequestPlan`, `CostEstimate`, `CapabilityReport`, and preflight result models.
3. Implement request-count calculations from unique variants, anchors, cluster bounds, verification caps, retries, and reserve.
4. Implement run ID/checkpoint directory creation without writing credentials or raw provider payloads.
5. Implement preflight decision results and safe diagnostics.
6. Expose `estimate` output with counts, units, assumptions, and budget comparison.

## Tests

- Equal canonical inputs produce equal hashes and request plans.
- Any compatibility input change invalidates the expected hash, including instruction-only changes.
- Cost estimates include embeddings, verifier/label/composite calls, retries, and the retry reserve.
- Missing pricing metadata prevents a paid run.
- Budget overrun makes zero paid calls and returns the budget-rejection category.
- Candidate overflow becomes explicit review-required/unresolved rather than vector-only assignment.
- Provider capability failure stops preflight and writes safe diagnostics.
- Run IDs/checkpoint paths are created deterministically enough for tests while remaining unique in production.
- No credential or raw unredacted answer text appears in request plans, hash diagnostics, or manifests.

## Acceptance criteria

- `estimate` reports a reproducible local plan and never makes a paid semantic call.
- `run` cannot enter embedding/generation stages until validation, capability, and budget preflight pass.
- The manifest/checkpoint contract records all hashes required for later resume compatibility.
- Changing the embedding instruction invalidates both compatible embedding reuse and resume.

## Non-goals

- Executing embedding or generation calls, clustering, assignment, or writing the final workbook.
