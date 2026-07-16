# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 0 — Context decomposition and implementation planning

## Current Goal

- Complete the implementation handoff and begin the first vertical slice: project foundation, packaging, domain contracts, and the `other-cluster` CLI entry point.

## Completed

- Locked `other-cluster` as the canonical project, package, and CLI name.
- Locked the `src/other_cluster/` package layout, `openpyxl` workbook boundary, standard-library `argparse` CLI, and `httpx` provider transport.
- Locked the v1 provider split: Nebius `Qwen/Qwen3-Embedding-8B` for 4096-dimensional `float32` original-language embeddings and direct Google `gemini-3.5-flash` for structured generation.
- Locked the initial pilot language scope to Arabic, including dialectal Arabic, and English.
- Created the context overview, architecture, code standards, progress tracker, and ordered feature specifications.
- Removed interrupted-run continuation and checkpoint-file behavior from v1; run IDs, stage statuses, manifests, logs, caches, and atomic artifact writes remain run-scoped diagnostics.
- Locked command boundaries: `validate`, `estimate`, and `preview` are local and create no production run state; only `run` loads credentials, performs live capability checks, and creates a run-artifact directory.
- Locked the required-choice pipeline: every input has at least one valid choice, and discovery runs only for substantive variants not assigned conservatively to an existing choice.
- Locked anchor-first embedding with temporary memmap publication: any exhausted embedding failure stops the run and cannot publish an incomplete vector artifact or result workbook.
- Locked medoid-based cluster representation, bounded top-three composite candidates, candidate-set validation, and separately calibrated cluster-level gates.
- Locked strict XLSX semantic strings, formulas rejected across all input sheets, reserved output-column names, literal formula-like output strings, and primitive passthrough metadata.
- Locked category-cap diagnostic behavior and separate JSON gold-fixture evaluation with the approved metric definitions and 95% Wilson intervals.
- Researched and documented the official token-counting, batching, structured-output billing, retry/failure billing, pricing, output-limit, tokenizer-version, and fallback contracts for the selected Nebius and Google profiles in `context/provider-token-billing.md`; the exact method and pricing version are now required fingerprint fields.

## In Progress

- Planning contract revision is complete; application implementation has not started.

## Next Up

- Implement Spec 01: project foundation, package metadata, domain contracts, typed errors, and the CLI help surface.

## Open Questions

- Add `GEMINI_API_KEY` to the local environment and run a synthetic direct Gemini structured-output smoke test.
- Capture an authenticated Nebius organization price-catalog snapshot for `Qwen/Qwen3-Embedding-8B`, including numeric rate, exact unit/currency, and effective/publication timestamp.
- Obtain an explicit Nebius billing answer for failed, timed-out, rate-limited, malformed, and retried embedding requests, or approve the documented conservative policy that treats unknown failures as potentially billable.
- Recheck the live Nebius model catalog, limits, endpoint requirements, requested 4096 dimensions, and accepted multi-item input form before advertising the profile as supported.
- Run a synthetic Google `countTokens` versus `generateContent` fixture using the complete structured request to verify schema/configuration counting and usage reconciliation.
- Keep hard-budget calculation marked not implementation-ready until those provider/account evidence items and the fallback-acceptance decision are fingerprinted.
- Pin the exact compatible dependency versions and capture them in `uv.lock`.
- Pin the exact Unicode/emoji data used by deterministic cleanup and define the configured working-memory ceiling for PCA/HDBSCAN.
- Create the seeded, manually labeled Arabic-and-English gold fixture before tuning matching thresholds; broader languages can be added when real data supports them.
- Confirm the researched pricing metadata and the hard per-run budget used by the first pilot configuration.

## Architecture Decisions

- One prepared XLSX workbook and one survey question per run; the source workbook is never modified.
- `uv` is the only dependency and execution workflow; Python 3.13 is the runtime baseline.
- `other-cluster` is the canonical package and console command.
- `src/other_cluster/` owns the application, with inward dependencies centered on typed domain contracts.
- `openpyxl` handles workbook I/O; standard-library `argparse` handles the CLI; `httpx` handles direct provider HTTP transport.
- V1 has no interrupted-run continuation or checkpoint files; only the `run` command creates run IDs and production run-artifact directories, and the manifest records stage statuses for audit.
- Every run requires at least one existing choice; choice-free discovery is not a v1 behavior branch.
- Nebius is the sole embedding provider and Google Gemini is the sole generation provider in v1; provider identities and credentials remain separate.
- No translation, transliteration, language-dependent representation switch, local model, web UI, survey integration, write-back, or analyst-feedback ingestion in v1.
- Original-language embeddings use fixed `Qwen/Qwen3-Embedding-8B`, 4096 dimensions, `float32`, L2 normalization, one fixed instruction, and a canonical NumPy memmap.
- Choice anchors are embedded first into a temporary memmap; any embedding failure after retries terminates the run before canonical publication.
- Promoted clusters use stable medoid embeddings for vector comparison; composite review sends at most three candidates and accepts at most one primary plus two advisory secondaries from that set.
- More than 50 promoted new categories produces a provisional diagnostic output, preserves existing-choice assignments, marks affected new-cluster members `unresolved_category_cap`, and skips labeling/composite review.
- New categories are proposals for analyst review; existing-choice assignments require vector and structured-verifier agreement.
- Persistent cache contents are plaintext redacted payloads/metadata and remain until explicit manual purge; bulk vectors are stored only in the memmap.
- Nebius preflight uses response `usage.prompt_tokens` for authoritative reconciliation; Google preflight uses the authenticated full-request `countTokens` endpoint and actual generation usage metadata.
- The provisional counter-outage fallback is `max(1, ceil(len(canonical_request_utf8_bytes) / 2))`; it is disclosed and fingerprinted but does not authorize a hard-budget run by itself.
- Google uses Standard direct pricing for v1 (`$1.50` input and `$9.00` output per 1M tokens, output including thinking) and application output caps of 256/512/512 tokens for verifier/labeler/composite operations.
- Hard-budget approval is blocked until the authenticated Nebius price/failure-billing snapshot, live model capability evidence, and Google count-versus-usage fixture are recorded.

## Session Notes
