# Progress Tracker

Update this file after every meaningful implementation change.

## Current Phase

- Phase 0 — Context decomposition and implementation planning

## Current Goal

- Complete the implementation handoff and begin the first vertical slice: project foundation, packaging, domain contracts, and the `other-cluster` CLI entry point.

## Completed

- Reviewed and retained the original `plan.md` as the source plan.
- Locked `other-cluster` as the canonical project, package, and CLI name.
- Locked the `src/other_cluster/` package layout, `openpyxl` workbook boundary, standard-library `argparse` CLI, and `httpx` provider transport.
- Locked the v1 provider split: Nebius `Qwen/Qwen3-Embedding-8B` for 2048-dimensional `float32` original-language embeddings and direct Google `gemini-3.5-flash` for structured generation.
- Locked the initial pilot language scope to Arabic, including dialectal Arabic, and English.
- Created the context overview, architecture, code standards, progress tracker, and ordered feature specifications.

## In Progress

- None yet; application implementation has not started.

## Next Up

- Implement Spec 01: project foundation, package metadata, domain contracts, typed errors, and the CLI help surface.

## Open Questions

- Add `GEMINI_API_KEY` to the local environment and run a synthetic direct Gemini structured-output smoke test.
- Recheck the live Nebius model catalog, limits, endpoint requirements, requested dimensions, and pricing before advertising the profile as supported.
- Pin the exact compatible dependency versions and capture them in `uv.lock`.
- Pin the exact Unicode/emoji data used by deterministic cleanup and define the configured working-memory ceiling for PCA/HDBSCAN.
- Create the seeded, manually labeled Arabic-and-English gold fixture before tuning matching thresholds; broader languages can be added when real data supports them.
- Confirm live pricing metadata and the hard per-run budget used by the first pilot configuration.

## Architecture Decisions

- One prepared XLSX workbook and one survey question per run; the source workbook is never modified.
- `uv` is the only dependency and execution workflow; Python 3.13 is the runtime baseline.
- `other-cluster` is the canonical package and console command.
- `src/other_cluster/` owns the application, with inward dependencies centered on typed domain contracts.
- `openpyxl` handles workbook I/O; standard-library `argparse` handles the CLI; `httpx` handles direct provider HTTP transport.
- Nebius is the sole embedding provider and Google Gemini is the sole generation provider in v1; provider identities and credentials remain separate.
- No translation, transliteration, language-dependent representation switch, local model, web UI, survey integration, write-back, or analyst-feedback ingestion in v1.
- Original-language embeddings use fixed `Qwen/Qwen3-Embedding-8B`, 2048 dimensions, `float32`, L2 normalization, one fixed instruction, and a canonical NumPy memmap.
- New categories are proposals for analyst review; existing-choice assignments require vector and structured-verifier agreement.
- Persistent cache contents are plaintext redacted payloads/metadata and remain until explicit manual purge; bulk vectors are stored only in the memmap.

## Session Notes

- The live repository is currently a minimal skeleton containing `plan.md`, `main.py`, `pyproject.toml`, `.python-version`, `.env`, `.gitignore`, and an empty `context/` directory.
- The current `.env` contains a Nebius key but no Google key; do not print or commit either secret.
- The original plan remains unchanged. The numbered specs are the implementation handoff and should be treated as the next source of execution order.
