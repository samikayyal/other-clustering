# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 0 — Context decomposition and implementation planning

## Current Goal

- Complete the implementation handoff and begin the first vertical slice: project foundation, packaging, domain contracts, and the `other-cluster` CLI entry point.

## Completed


## In Progress

- Planning contract revision is complete; application implementation has not started.

## Next Up

- Implement Spec 01: project foundation, package metadata, domain contracts, typed errors, and the CLI help surface.

## Open Questions

- Add `GEMINI_API_KEY` to the local environment and run a synthetic direct Gemini structured-output smoke test.
- Capture an authenticated Nebius organization price-catalog snapshot for `Qwen/Qwen3-Embedding-8B`, including numeric rate, exact unit/currency, and effective/publication timestamp.
- Obtain an explicit Nebius billing answer for failed, timed-out, rate-limited, malformed, and retried embedding requests, or approve the documented conservative policy that treats unknown failures as potentially billable.
- Recheck the live Nebius model catalog, limits, endpoint requirements, requested 4096 dimensions, and accepted multi-item input form before advertising the profile as supported.
- Run a synthetic Google `countTokens` versus `generateContent` fixture using the complete structured request to verify schema/configuration counting, usage reconciliation, and the pinned thinking configuration (thinking disabled, JSON completes within the output caps, observed `maxOutputTokens`/thinking-budget interaction).
- Keep hard-budget calculation marked not implementation-ready until those provider/account evidence items and the fallback-acceptance decision are fingerprinted.
- Pin the exact compatible dependency versions and capture them in `uv.lock`.
- Pin the exact Unicode/emoji data used by deterministic cleanup and define the configured working-memory ceiling for PCA/HDBSCAN.
- Complete the Spec 02b gold fixture and instruction-calibration experiment before Spec 06 freezes the embedding instruction and the Spec 06–08 threshold defaults; broader languages can be added when real data supports them.
- Confirm the researched pricing metadata and the hard per-run budget used by the first pilot configuration.

## Architecture Decisions

- One prepared XLSX workbook and one survey question per run; the source workbook is never modified.
- `uv` is the only dependency and execution workflow; Python 3.13 is the runtime baseline.
- `other-cluster` is the canonical package and console command.
- `src/other_cluster/` owns the application, with inward dependencies centered on typed domain contracts.
- `openpyxl` handles workbook I/O; standard-library `argparse` handles the CLI; `httpx` handles direct provider HTTP transport.
- V1 has no interrupted-run continuation or checkpoint files; only the `run` command creates run IDs and production run-artifact directories, and the manifest records stage statuses for audit. The single narrow exception is the embedding salvage artifact: on exhausted embedding failure, verified vector rows are published keyed by the embedding fingerprint, and a later run with an exactly matching fingerprint may adopt those rows and embed only the remainder — vectors only, no pipeline-state continuation.
- Every run requires at least one existing choice; choice-free discovery is not a v1 behavior branch.
- Nebius is the sole embedding provider and Google Gemini is the sole generation provider in v1; provider identities and credentials remain separate.
- No translation, transliteration, language-dependent representation switch, local model, web UI, survey integration, write-back, or analyst-feedback ingestion in v1.
- Original-language embeddings use fixed `Qwen/Qwen3-Embedding-8B`, 4096 dimensions, `float32`, L2 normalization, one fixed instruction, and a canonical NumPy memmap.
- Choice anchors are embedded first into a temporary memmap; any embedding failure after retries terminates the run before canonical publication, publishing the salvage artifact of verified rows on the way out.
- Promoted clusters use stable medoid embeddings for vector comparison; composite review sends at most three candidates and accepts at most one primary plus two advisory secondaries from that set.
- More than 50 promoted new categories produces a provisional diagnostic output, preserves existing-choice assignments, marks affected new-cluster members `unresolved_category_cap`, and skips labeling/composite review.
- New categories are proposals for analyst review; existing-choice assignments require vector and structured-verifier agreement.
- Persistent cache contents are plaintext redacted payloads/metadata and remain until explicit manual purge; bulk vectors are stored only in the memmap.
- Nebius preflight uses response `usage.prompt_tokens` for authoritative reconciliation; Google preflight uses the authenticated full-request `countTokens` endpoint and actual generation usage metadata.
- The provisional counter-outage fallback is `max(1, ceil(len(canonical_request_utf8_bytes) / 2))`; it is disclosed and fingerprinted but does not authorize a hard-budget run by itself.
- Google uses Standard direct pricing for v1 (`$1.50` input and `$9.00` output per 1M tokens, output including thinking) and application output caps of 256/512/512 tokens for verifier/labeler/composite operations, valid only under the pinned thinking configuration.
- Gemini thinking configuration is pinned, mandatory, and fingerprinted: `thinking_mode`/`thinking_budget_tokens` are profile fields, v1 disables thinking (`thinking_budget_tokens = 0`) for all operations, and unexpected nonzero thinking usage is treated as a provider-contract violation.
- The hard per-run budget is enforced as a runtime invariant: the preflight gate uses a realistic-assumption estimate with printed assumptions (worst case reported as a diagnostic only), staged `countTokens` checkpoints run before the verification and labeling/composite stages on the real request sets, and continuous spend tracking stops paid dispatch at exhaustion via the safe-stop machinery with `unresolved_budget` items and the `budget_exhausted_midrun` exit category. Under scarcity, embeddings and existing-choice verification take precedence over discovery/labeling/composite.
- Variant identity uses a tiered language-conservative grouping key (safe tier always on: tatweel, digit-class unification, tashkeel; aggressive tier configurable, default on: hamza/alef seat, taa marbuta, alef maqsura); stored raw/normalized/redacted text is never rewritten, each group embeds a deterministic representative surface form, and the grouping policy hash is a fingerprint input.
- Digit-sensitive redaction rules must cover ASCII, Arabic-Indic, and Extended Arabic-Indic digit classes; the digit-class policy is part of the redaction policy hash.
- Batched structured-generation retries follow a fixed taxonomy: response-level failures retry the whole batch, item-level failures preserve valid results and retry only failed items (correlated by explicit stable IDs, never array position), with separate manifest counters.
- The gold fixture and embedding-instruction calibration (Spec 02b) precede implementation of Specs 06–08: the embedding instruction and all vector-gate defaults must trace to the calibration record before they are frozen into the fingerprint.
- Hard-budget approval is blocked until the authenticated Nebius price/failure-billing snapshot, live model capability evidence, and Google count-versus-usage fixture (including thinking-configuration verification) are recorded.

## Session Notes
