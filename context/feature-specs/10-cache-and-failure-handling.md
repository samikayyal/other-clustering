# Spec 10 — Cache and Failure Handling

**Status:** Planned
**Dependencies:** Spec 05, Spec 06, Spec 09
**Implementation order:** 10 of 11

## Outcome

The application records provider request/cache metadata, writes run artifacts atomically, and handles provider failures without corrupting the semantic contract. Persistent cache operations are inspectable and confirmation-protected. V1 does not continue an interrupted run; a new invocation starts a new run.

## Cache policy

- Keep provider cache separate from result workbooks and run artifacts.
- Store complete redacted requests/responses for generation and small diagnostic calls.
- For bulk embeddings, store redacted request metadata, response metadata, planned vector row range, checksum, and usage; store actual vectors only in the complete canonical `float32` memmap.
- Never cache unredacted answers, passthrough metadata, credentials, or a second full JSON vector matrix.
- Retain cache files indefinitely until explicit manual purge; no automatic expiry in v1.
- Add the cache directory to generated `.gitignore` defaults and warn if any cache file is tracked.
- Use structured logs that contain operational context but no raw unredacted answer text or credentials.

## Stage status and atomic writes

Record stage status in the run manifest after meaningful stages, at minimum:

- validated/fingerprinted;
- preprocessed/deduplicated;
- provider preflight and budget approved;
- embeddings/memmap complete and verified;
- existing-choice matching complete;
- discovery complete;
- labeling/composite review complete;
- assignment/workbook/manifest complete.

The manifest records stage status, semantic-contract hashes, provider/model profiles, artifact paths, checksums, counts, and safe error details. Manifest, cache, log, and result writes are atomic where practical; a partial write is never treated as a completed run. These records are diagnostic only and are not used to continue a later invocation.

## Failure behavior

- Structural input/configuration errors fail before provider calls.
- Budget overrun fails before paid calls.
- After bounded retries, any embedding failure—including an anchor failure, answer-batch failure, malformed response, wrong dimension, non-finite value, or invalid normalization—stops the run. The temporary memmap is closed and removed, the incomplete canonical vector artifact is never published, and a safe manifest/log records completed requests, recorded cost, retries, and the error category. No six-sheet result workbook is written.
- Individual malformed/failed Gemini judgment or labeling requests retry according to policy, become explicit unresolved/error records after exhaustion, and allow later eligible items to continue.
- Stop non-embedding semantic work for systemic provider failure after 20 consecutive failures or more than 5% failures after at least 100 calls.
- On systemic stop or interruption, atomically write the manifest, cache metadata, unresolved records, and any verified artifact state before exiting; never report the run as successful.
- Distinguish retryable transport/rate-limit errors, malformed structured output, invalid model/capability errors, and non-retryable contract errors.
- Surface unavoidable hosted-model variance instead of claiming byte-identical results.

## Cache commands

The implementation must support:

- `cache inspect`: report counts, sizes, providers, models, and run IDs without printing payload bodies;
- `cache purge --run-id RUN_ID` or `cache purge --before DATE`: preview deletion and require explicit confirmation before removing persistent payloads.

## Implementation tasks

1. Implement atomic manifest stage-status serialization and failure transitions.
2. Implement cache file naming, checksums, metadata-only bulk embedding entries, and purge confirmation.
3. Implement anchor-first embedding failure cleanup, temporary-memmap removal, and canonical-artifact publish guards.
4. Implement circuit-breaker counters and threshold evaluation for non-embedding semantic work.
5. Implement interruption/systemic-failure artifact flushing without continuation logic.
6. Add tracked-cache warnings and secret/raw-text exclusion checks.

## Tests

- Embedding failures retry and then terminate the run with no incomplete canonical vector artifact or six-sheet workbook.
- Individual Gemini provider failures retry, become unresolved, and allow later eligible items to continue.
- Circuit breakers trigger at 20 consecutive failures and at more than 5% after 100 calls.
- Systemic stop leaves a readable manifest, unresolved records, cache metadata, and only complete/verified vector state.
- Memmap shape/dtype/checksum/row-map validation prevents publication of unsafe vector artifacts.
- Cache inspect never prints payload bodies.
- Cache purge requires confirmation and deletes only the requested run/date scope.
- Cache payloads contain no credentials, raw unredacted text, or duplicate bulk JSON vectors.
- An interrupted run is marked incomplete/diagnostic and a subsequent invocation starts a distinct run without mixing artifacts.

## Acceptance criteria

- An interrupted or systemically failed run leaves enough evidence for diagnosis, never reports success, and does not publish incomplete canonical vectors.
- Cache operations are explicit, auditable, and consistent with the plaintext-retention policy.

## Non-goals

- Automatic cache expiry, production access-control hardening, distributed execution, provider failover, or changing the v1 storage contract.
