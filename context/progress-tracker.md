# Progress Tracker

## Current Phase

Documentation contract clarification before implementation.

## Completed Work

- Defined the default cluster proposal gate as `3` distinct exact answer texts, with the threshold configurable as `discovery.min_unique_answer_texts`.
- Defined semantic-overlap handling: the system proposes a merge and the analyst must confirm it; an approved merge has one bilingual label, one workbook-wide value, and one combined member set.
- Defined the simple CLI/configuration contract: `--input`, `--output`, optional `--config`, and opt-in `--overwrite`, with CLI > TOML > environment > built-in precedence.
- Defined separate-output behavior: in-place source modification is invalid, and an existing output requires explicit overwrite authorization.
- Defined workbook answer handling: numeric answer cells are invalid, while blank cells remain skipped; exact duplicate answer text is processed once per question and fanned out to every row-level answer mapping.
- Deferred the web framework, browser UI approach, review-state storage, and local/hosted deployment choice until Feature 06 implementation.

## Open Questions

The remaining open questions are recorded in the applicable architecture and feature-specification files.

## Architecture Decisions

- **Cluster proposal evidence:** A cluster is proposal-eligible when it contains at least three distinct exact original answer texts by default. The setting is configurable.
- **Semantic overlap:** The system detects overlap and proposes merges; only explicit analyst confirmation authorizes a merge. A confirmed merge becomes one category, label pair, value, and member set.
- **CLI and output safety:** Input and output paths are resolved from CLI, TOML, environment, and defaults in that order. The source and output must be different paths, and overwrite is opt-in.
- **Answer validation and deduplication:** Nonblank numeric `Data` answer cells are invalid because the raw-answer contract is free text. Exact duplicate text is deduplicated within each question for provider/computation work, with decisions and results fanned out through stable row-level answer and destination-cell mappings.
- **Web application:** Framework, browser UI, review-state storage, and deployment model remain intentionally deferred until Feature 06 implementation.
