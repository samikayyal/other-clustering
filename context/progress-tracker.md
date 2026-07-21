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
- Implemented read-only `.xlsx` workbook validation and extraction for `Survey`, `Code`, `Data`, and `Work`, including exact row/cell locations, exclusion of Code value `-96`, and Work triplet ordering checks.
- Implemented respondent-level answer records plus per-question exact-text deduplication for later provider stages; hidden rows are included and unsupported numeric, formula, merged, and error answer cells fail validation.
- Added openpyxl/python-dotenv runtime dependencies and focused tests covering the Feature 01 configuration, ingestion, deduplication, and CLI contracts.
- Applied a Brooks-Lint PR review: split the `_extract_dataset`/`_extract_answers` monoliths into named single-responsibility helpers (`_require_sheets`, `_raise_if_issues`, `_build_questions`, `_scan_row_answers`, `_claim_data_key`, `_resolve_work_row`, `_build_answer_record`, `_cell_location`) with behavior unchanged, and hardened the workbook-validation gate with parametrized rejection tests (missing sheet, missing/duplicate/non-text headers, blank required label, missing choice rows, duplicate question ID, non-integer choice value, merged and error answer cells) that each assert the source workbook is left byte-for-byte unmodified. Suite at 25 passing tests.

## Open Questions

The remaining open questions are recorded in the applicable architecture and feature-specification files.

## Architecture Decisions

- **Cluster proposal evidence:** A cluster is proposal-eligible when it contains at least three distinct exact original answer texts by default. The setting is configurable.
- **Semantic overlap:** The system detects overlap and proposes merges; only explicit analyst confirmation authorizes a merge. A confirmed merge becomes one category, label pair, value, and member set.
- **CLI and output safety:** Input and output paths are resolved from CLI, TOML, environment, and defaults in that order. The source and output must be different paths, and overwrite is opt-in.
- **Answer validation and deduplication:** Nonblank numeric `Data` answer cells are invalid because the raw-answer contract is free text. Exact duplicate text is deduplicated within each question for provider/computation work, with decisions and results fanned out through stable row-level answer and destination-cell mappings.
- **Web application:** Framework, browser UI, review-state storage, and deployment model remain intentionally deferred until Feature 06 implementation.
- **Feature 01 workbook boundary:** Ingestion opens workbooks with formulas visible (`data_only=False`), validates the required four-sheet contract without saving, maps Data rows to Work rows by the stable `KEY` (including aligned formula-backed Work keys), and exposes immutable row-level cell references for later gated writing.
