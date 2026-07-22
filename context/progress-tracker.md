# Progress Tracker

## Current Phase

Feature 01 workbook ingestion and CLI implemented, including Google Sheets link input and the Data-only answer boundary; Feature 02 is next.

## Completed Work

- Defined the default cluster proposal gate as `3` distinct exact answer texts, with the threshold configurable as `discovery.min_unique_answer_texts`.
- Defined semantic-overlap handling: the system proposes a merge and the analyst must confirm it; an approved merge has one bilingual label, one workbook-wide value, and one combined member set.
- Defined the simple CLI/configuration contract: `--input`, `--output`, optional `--config`, and opt-in `--overwrite`, with CLI > TOML > environment > built-in precedence.
- Defined separate-output behavior: in-place source modification is invalid, and an existing output requires explicit overwrite authorization.
- Defined workbook answer handling: numeric answer cells are treated as empty, skipped, and reported as source-cell warnings; exact duplicate answer text is processed once per question and fanned out to every row-level answer mapping.
- Removed all `Work`-tab logic from ingestion: `Work` is not required, validated, read, or used for row/cell mapping, and the domain records expose only exact `Data` source locations. Full suite remains green at 50 passing tests.
- Deferred the web framework, browser UI approach, review-state storage, and local/hosted deployment choice until Feature 06 implementation.
- Implemented the `other-cluster` CLI with `--input`, `--output`, `--config`, and opt-in `--overwrite` handling, including the documented exit-code contract.
- Implemented TOML, environment, and optional `.env` resolution with CLI > TOML > environment > built-in precedence and unknown-key validation.
- Implemented read-only `.xlsx` workbook validation and extraction for `Survey`, `Code`, and `Data`, using `Code.list_name` as the primary question key and matching normalized `Survey.name` metadata, including exact source row/cell locations and exclusion of Code value `-96`.
- Implemented bilingual-label fallback during ingestion: a blank or whitespace-only `label:english` or `label:arabic` value inherits the other label for both `Survey` question metadata and `Code` choices; both blank labels produce a row-aware workbook-contract error.
- Implemented respondent-level answer records plus per-question exact-text deduplication for later provider stages; hidden rows are included, numeric cells are skipped with warnings, and formula, merged, and error answer cells fail validation.
- Added regression coverage confirming required workbook headers are resolved by name regardless of column order and that no coding-destination sheet is needed.
- Added row-aware workbook diagnostics: applicable validation errors identify the worksheet row or exact cell, while path and missing-sheet errors omit a row when none exists.
- Made row diagnostics explicit in rendered messages, for example `Code!D8 (row 8)`, so Excel coordinates are not the only indication of the failing row.
- Added openpyxl/python-dotenv runtime dependencies and focused tests covering the Feature 01 configuration, ingestion, deduplication, and CLI contracts.
- Applied a Brooks-Lint PR review: split the `_extract_dataset`/`_extract_answers` monoliths into named single-responsibility helpers (`_require_sheets`, `_raise_if_issues`, `_build_questions`, `_scan_row_answers`, `_claim_data_key`, `_build_answer_record`, `_cell_location`) with behavior unchanged, and hardened the workbook-validation gate with parametrized rejection tests (missing sheet, missing/duplicate/non-text headers, blank required label, missing Survey metadata for a Code list, duplicate question ID, non-integer choice value, merged and error answer cells) that each assert the source workbook is left byte-for-byte unmodified. Suite at 25 passing tests.
- Added regression tests for one-sided Survey and Code label fallback and for rejecting both labels blank, with the source workbook remaining byte-for-byte unchanged on validation failure. Suite at 30 passing tests.
- Normalized a trailing `_other` suffix from `Code.list_name` only when matching question metadata in `Survey.name`; original Code IDs remain unchanged for `Data` extraction. Added regression coverage for the normalized lookup. Suite now has 31 passing tests.
- Changed workbook header validation to ignore unexpected headers on every supported sheet while continuing to reject missing or duplicate required headers. Added regression coverage for extra headers including `Code.list_name_other`.
- Added native Google Sheets link input. Supported links are downloaded through the XLSX export endpoint to a uniquely named `.xlsx` file under `./.temp/`, then removed by `finally` cleanup after successful ingestion or any expected failure. Added configuration, downloader, and CLI cleanup regression coverage.
- Hardened the Google Sheets temporary-file boundary: blocked or unwritable `.temp` paths now produce the clean download-failure exit code, and cleanup errors are attached to rather than masking the primary download or ingestion failure. Added blocked-path and cleanup-preservation regression coverage.
- Expanded Survey metadata lookup with ordered deterministic identifier rules: a trailing `_other` targets its suffix-free parent; a trailing `_exp` prefers its exact ID and falls back to the suffix-free ID; and each base prefers exact spelling before restoring a missing underscore before terminal digits. The first existing candidate wins; unresolved names remain errors and are never fuzzy-matched. Added regression coverage for the observed land-degradation, improved-seeds, severe-shocks, and farm-style exact `_exp` behavior, candidate precedence, and the valid `zero_livestock_exp` rejection. Full suite: 41 passing tests.
- Changed numeric `Data` answer cells to empty-cell behavior with source-cell warnings on the CLI; added ingestion and CLI regression coverage. Numeric cells are excluded from respondent and processing answer records while other workbook-contract failures remain fatal.
- Centralized workbook issues and warnings in the mutable `WorkbookDiagnostics` domain model so extraction helpers share one diagnostics object instead of receiving separate collections.

## Open Questions

The remaining open questions are recorded in the applicable architecture and feature-specification files.

## Architecture Decisions

- **Cluster proposal evidence:** A cluster is proposal-eligible when it contains at least three distinct exact original answer texts by default. The setting is configurable.
- **Semantic overlap:** The system detects overlap and proposes merges; only explicit analyst confirmation authorizes a merge. A confirmed merge becomes one category, label pair, value, and member set.
- **CLI and output safety:** Input and output paths are resolved from CLI, TOML, environment, and defaults in that order. The source and output must be different paths, and overwrite is opt-in.
- **Answer validation and deduplication:** Numeric `Data` answer cells are treated as empty and skipped, with a source-cell warning printed by the CLI. Exact duplicate text is deduplicated within each question for provider/computation work, with decisions and results fanned out through stable row-level answer and source-cell mappings.
- **Web application:** Framework, browser UI, review-state storage, and deployment model remain intentionally deferred until Feature 06 implementation.
- **Question extraction key:** `Code.list_name` is the primary question key; normalized matching `Survey.name` supplies the bilingual metadata, and unmatched Survey rows are ignored.
- **Survey metadata lookup:** For the `Survey.name` lookup only, a trailing `_other` targets its suffix-free parent, a trailing `_exp` prefers exact then suffix-free, and each base prefers exact spelling before restoring an underscore before terminal digits. The first existing candidate wins; no match fails and identifiers are never fuzzy-matched. The original Code list name remains authoritative for the `Data` answer column.
- **Bilingual label fallback:** For each Survey question or Code choice, a blank or whitespace-only English or Arabic label is replaced with the other nonblank label; both blank labels are invalid and stop ingestion.
- **Header order:** Required headers are position-independent on `Survey`, `Code`, and `Data`; no coding-destination tab or triplet order is part of the contract.
- **Fixed-header casing:** Fixed schema headers are matched case-insensitively to support SurveyCTO exports such as `Label:Arabic`; dynamic question IDs remain case-sensitive.
- **Unexpected headers:** Headers outside the required contract are ignored on `Survey`, `Code`, and `Data`; other sheets are outside extraction and do not affect validation.
- **Feature 01 workbook boundary:** Ingestion opens workbooks with formulas visible (`data_only=False`), validates the required three-sheet contract without saving, extracts Data rows by their stable `KEY`, and exposes immutable row-level source-cell references for later review/output work.
- **Google Sheets input lifecycle:** Native `docs.google.com/spreadsheets/d/...` links are converted to the XLSX export endpoint and materialized as uniquely named temporary files under the current working directory's `.temp` directory. Only the file created for the current run is deleted, in a `finally` block, after success or failure; local input paths are untouched.
