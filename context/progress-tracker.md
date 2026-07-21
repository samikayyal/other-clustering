# Progress Tracker

## Current Phase

Feature 01 workbook ingestion and CLI implemented; Feature 02 is next.

## Completed Work

- Defined the default cluster proposal gate as `3` distinct exact answer texts, with the threshold configurable as `discovery.min_unique_answer_texts`.
- Defined semantic-overlap handling: the system proposes a merge and the analyst must confirm it; an approved merge has one bilingual label, one workbook-wide value, and one combined member set.
- Defined the simple CLI/configuration contract: `--input`, `--output`, optional `--config`, and opt-in `--overwrite`, with CLI > TOML > environment > built-in precedence.
- Defined separate-output behavior: in-place source modification is invalid, and an existing output requires explicit overwrite authorization.
- Defined workbook answer handling: numeric answer cells are invalid, while blank cells remain skipped; exact duplicate answer text is processed once per question and fanned out to every row-level answer mapping.
- Deferred the web framework, browser UI approach, review-state storage, and local/hosted deployment choice until Feature 06 implementation.
- Implemented the `other-cluster` CLI with `--input`, `--output`, `--config`, and opt-in `--overwrite` handling, including the documented exit-code contract.
- Implemented TOML, environment, and optional `.env` resolution with CLI > TOML > environment > built-in precedence and unknown-key validation.
- Implemented read-only `.xlsx` workbook validation and extraction for `Survey`, `Code`, `Data`, and `Work`, using `Code.list_name` as the primary question key and matching normalized `Survey.name` metadata, including exact row/cell locations, exclusion of Code value `-96`, and Work triplet ordering checks.
- Implemented bilingual-label fallback during ingestion: a blank or whitespace-only `label:english` or `label:arabic` value inherits the other label for both `Survey` question metadata and `Code` choices; both blank labels produce a row-aware workbook-contract error.
- Implemented respondent-level answer records plus per-question exact-text deduplication for later provider stages; hidden rows are included and unsupported numeric, formula, merged, and error answer cells fail validation.
- Added regression coverage confirming required workbook headers are resolved by name regardless of column order while `Work` coding triplets remain contiguous and ordered.
- Added row-aware workbook diagnostics: applicable validation errors identify the worksheet row or exact cell, while path and missing-sheet errors omit a row when none exists.
- Made row diagnostics explicit in rendered messages, for example `Code!D8 (row 8)`, so Excel coordinates are not the only indication of the failing row.
- Added openpyxl/python-dotenv runtime dependencies and focused tests covering the Feature 01 configuration, ingestion, deduplication, and CLI contracts.
- Applied a Brooks-Lint PR review: split the `_extract_dataset`/`_extract_answers` monoliths into named single-responsibility helpers (`_require_sheets`, `_raise_if_issues`, `_build_questions`, `_scan_row_answers`, `_claim_data_key`, `_resolve_work_row`, `_build_answer_record`, `_cell_location`) with behavior unchanged, and hardened the workbook-validation gate with parametrized rejection tests (missing sheet, missing/duplicate/non-text headers, blank required label, missing Survey metadata for a Code list, duplicate question ID, non-integer choice value, merged and error answer cells) that each assert the source workbook is left byte-for-byte unmodified. Suite at 25 passing tests.
- Added regression tests for one-sided Survey and Code label fallback and for rejecting both labels blank, with the source workbook remaining byte-for-byte unchanged on validation failure. Suite at 30 passing tests.
- Normalized a trailing `_other` suffix from `Code.list_name` only when matching question metadata in `Survey.name`; original Code IDs remain unchanged for `Data`/`Work` extraction. Added regression coverage for the normalized lookup. Suite now has 31 passing tests.
- Changed workbook header validation to ignore unexpected headers on every supported sheet while continuing to reject missing or duplicate required headers and invalid `Work` triplet ordering. Added regression coverage for extra headers including `Code.list_name_other`.

## Open Questions

The remaining open questions are recorded in the applicable architecture and feature-specification files.

## Architecture Decisions

- **Cluster proposal evidence:** A cluster is proposal-eligible when it contains at least three distinct exact original answer texts by default. The setting is configurable.
- **Semantic overlap:** The system detects overlap and proposes merges; only explicit analyst confirmation authorizes a merge. A confirmed merge becomes one category, label pair, value, and member set.
- **CLI and output safety:** Input and output paths are resolved from CLI, TOML, environment, and defaults in that order. The source and output must be different paths, and overwrite is opt-in.
- **Answer validation and deduplication:** Nonblank numeric `Data` answer cells are invalid because the raw-answer contract is free text. Exact duplicate text is deduplicated within each question for provider/computation work, with decisions and results fanned out through stable row-level answer and destination-cell mappings.
- **Web application:** Framework, browser UI, review-state storage, and deployment model remain intentionally deferred until Feature 06 implementation.
- **Question extraction key:** `Code.list_name` is the primary question key; normalized matching `Survey.name` supplies the bilingual metadata, and unmatched Survey rows are ignored.
- **Survey metadata lookup:** When a `Code.list_name` ends with `_other`, ingestion removes that suffix only for the `Survey.name` lookup; the original Code list name remains authoritative for `Data` and `Work` columns.
- **Bilingual label fallback:** For each Survey question or Code choice, a blank or whitespace-only English or Arabic label is replaced with the other nonblank label; both blank labels are invalid and stop ingestion.
- **Header order:** Required headers are position-independent on all sheets; only each `Work` question triplet has a required contiguous order.
- **Fixed-header casing:** Fixed schema headers are matched case-insensitively to support SurveyCTO exports such as `Label:Arabic`; dynamic question IDs and `Work` triplet names remain case-sensitive.
- **Unexpected headers:** Headers outside the required contract are ignored on `Survey`, `Code`, `Data`, and `Work`; they do not affect extraction or validation.
- **Feature 01 workbook boundary:** Ingestion opens workbooks with formulas visible (`data_only=False`), validates the required four-sheet contract without saving, maps Data rows to Work rows by the stable `KEY` (including aligned formula-backed Work keys), and exposes immutable row-level cell references for later gated writing.
