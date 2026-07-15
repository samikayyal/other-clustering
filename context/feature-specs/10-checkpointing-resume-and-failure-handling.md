# Spec 10 — Checkpointing, Resume, and Failure Handling

**Status:** Planned
**Dependencies:** Spec 05, Spec 06, Spec 09
**Implementation order:** 10 of 11

## Outcome

Long-running semantic runs can recover from individual failures or process interruption without losing audit state, mixing providers/models, duplicating bulk vectors, or silently changing the semantic contract. Persistent cache operations are inspectable and confirmation-protected.

## Cache policy

- Keep provider cache separate from result workbooks and run artifacts.
- Store complete redacted requests/responses for generation and small diagnostic calls.
- For bulk embeddings, store redacted request metadata, response metadata, vector row range, checksum, and usage; store actual vectors only in the canonical `float32` memmap.
- Never cache unredacted answers, passthrough metadata, credentials, or a second full JSON vector matrix.
- Retain cache files indefinitely until explicit manual purge; no automatic expiry in v1.
- Add the cache directory to generated `.gitignore` defaults and warn if any cache file is tracked.
- Use structured logs that contain operational context but no raw unredacted answer text or credentials.

## Checkpoint contract

Checkpoint after meaningful stages, at minimum:

- validated/fingerprinted;
- preprocessed/deduplicated;
- provider preflight and budget approved;
- embeddings/memmap complete and verified;
- existing-choice matching complete;
- discovery complete;
- labeling/composite review complete;
- assignment/workbook/manifest complete.

Each checkpoint records stage status, compatibility hashes, provider/model profiles, artifact paths, checksums, counts, and safe error details. Writes should be atomic so a partial checkpoint is never treated as complete.

## Resume rules

`resume --run-id RUN_ID --output-dir DIR` may continue only when all required hashes and profiles match:

- input workbook;
- canonical configuration;
- providers, endpoints, exact model IDs, and model parameters;
- embedding dimension, dtype, normalization, instruction and instruction SHA-256;
- generation schemas/prompts;
- normalization, Unicode/emoji, non-semantic, and redaction rules;
- package/runtime compatibility metadata required by the manifest.

Resume must reject incompatible state rather than silently recomputing with a new provider/model or merging incompatible vectors. Validate memmap shape, dtype, normalization, row map, flush state, and checksum before reuse. Recover only confirmed vector rows.

## Failure behavior

- Structural input/configuration errors fail before provider calls.
- Budget overrun fails before paid calls.
- Individual malformed/failed embedding, judgment, or labeling requests retry according to policy, become explicit unresolved/error records after exhaustion, and allow the run to continue.
- Stop for systemic provider failure after 20 consecutive failures or more than 5% failures after at least 100 calls.
- On systemic stop, flush the manifest, cache metadata, unresolved records, memmap/checksum state, and checkpoint before exiting.
- Distinguish retryable transport/rate-limit errors, malformed structured output, invalid model/capability errors, and non-retryable contract errors.
- Surface unavoidable hosted-model variance instead of claiming byte-identical results.

## Cache commands

The implementation must support:

- `cache inspect`: report counts, sizes, providers, models, and run IDs without printing payload bodies;
- `cache purge --run-id RUN_ID` or `cache purge --before DATE`: preview deletion and require explicit confirmation before removing persistent payloads.

## Implementation tasks

1. Implement atomic checkpoint serialization and stage transitions.
2. Implement compatibility validation and safe resume diagnostics.
3. Implement cache file naming, checksums, metadata-only bulk embedding entries, and purge confirmation.
4. Implement circuit-breaker counters and threshold evaluation.
5. Implement interruption/systemic-failure cleanup and artifact flushing.
6. Add tracked-cache warnings and secret/raw-text exclusion checks.

## Tests

- Individual provider failures retry, become unresolved, and allow later rows/stages to continue.
- Circuit breakers trigger at 20 consecutive failures and at more than 5% after 100 calls.
- Systemic stop leaves a readable checkpoint, manifest, unresolved records, cache metadata, and valid vector state.
- Resume succeeds with identical hashes and fails with any changed input/config/profile/model/endpoint/dimension/instruction/redaction contract.
- Memmap shape/dtype/checksum/row-map validation prevents unsafe reuse.
- Cache inspect never prints payload bodies.
- Cache purge requires confirmation and deletes only the requested run/date scope.
- Cache payloads contain no credentials, raw unredacted text, or duplicate bulk JSON vectors.
- Repeated resume does not duplicate confirmed vector rows or final assignments.

## Acceptance criteria

- An interrupted compatible run resumes from the last completed checkpoint without provider mixing.
- An incompatible run stops with a specific safe reason and does not alter existing artifacts.
- Systemic failure leaves enough evidence for diagnosis and later resume.
- Cache operations are explicit, auditable, and consistent with the plaintext-retention policy.

## Non-goals

- Automatic cache expiry, production access-control hardening, distributed execution, provider failover, or changing the v1 storage contract.
