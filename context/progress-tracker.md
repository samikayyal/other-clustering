# Progress Tracker

## Current Phase

The project is being reset from the former seven-stage assignment/package /
approval/finalization workflow to the locked five-stage Cluster-First V1:

1. workbook ingestion and analysis CLI;
2. original-language embeddings;
3. all-answer category discovery;
4. cluster classification and one schema-version-2 review-file creation; and
5. simplified analyst review and completion.

The context reset, primary source implementation, contract verification, stale-
reference cleanup, and full-suite checks are complete.

## V1 Contract Reset

- V1 reads only `Survey`, `Code`, and `Data`; `Work` is never accessed,
  validated, interpreted, or written.
- V1 ends with one completed reviewed JSON file under `./reviews`.
- No workbook output, CSV extraction, finalization command, package/draft /
  approval/receipt lifecycle, merge/split/move/manual-category workflow, or
  value editing exists in V1.
- Existing-choice reuse occurs once per proposal-eligible cluster during
  Gemini classification, never once per answer.
- All canonical answers are discovery points. Exact duplicate respondent
  occurrences fan out through immutable row mappings without density weighting.
- Values are allocated only when review completes, independently per question,
  by stable cluster ID. Values may repeat across different question lists.
- The Gemini model is `gemini-3.5-flash-lite`; the fixed PCA/HDBSCAN defaults
  are documented in the active feature specifications.

## Architecture Decisions

- **Cluster-first V1 boundary:** Replace per-answer existing-choice Gemini calls
  and seven stages with one request per proposal-eligible cluster after
  question-scoped all-answer discovery.
- **Immutable cluster membership:** The analyst can choose only one whole-cluster
  disposition: same-question existing choice, one bilingual new category, or
  unresolved. Noise and rare canonical answers can only choose existing choice
  or unresolved.
- **Single authoritative review file:** Schema-version-2 JSON is both evidence
  and editable state. Analysis creates `in_review`; browser completion atomically
  updates that same file to `complete`. No duplicate proposal/final snapshot,
  operation log, approval ID, receipt, replay state, or review hash exists.
- **Per-question allocation:** Completion collects existing values greater than
  100 per question, processes final new categories by stable cluster ID, and
  assigns the smallest unused integer. Values may repeat across questions.
- **Provider failure policy:** Five transport attempts and up to three
  structured generations are allowed per eligible cluster. Exhaustion is a
  nonfatal safe warning and a fixed provider-error cluster; Nebius, workbook,
  alignment, and review-write failures remain fatal.
- **V2 workbook backlog:** Workbook mutation, `Work` interpretation, respondent
  output, and finalization mechanics are deferred until after V1 validation.

## Implementation Log

- Context contracts rewritten before source changes to the five active V1
  features. Former Features 03 and 07 are no longer active specifications;
  former package/approval requirements are superseded by the single review-file
  contract.
- Replaced the domain's per-answer assignment, provisional category, merge, and
  package result records with all-answer discovery facts, fixed cluster
  proposals, classification warnings, and a schema-version-2 review-file
  result. Deleted the old assignment, extracted-CSV, labeling, and package
  implementations.
- Reworked discovery to accept only the dataset and aligned embeddings. Every
  canonical question/text answer is a point; per-question PCA/HDBSCAN retains
  noise, rare, low-probability, and rejected-small-cluster evidence without
  centroids or merge suggestions.
- Added one-call-per-eligible-cluster Gemini classification using
  `gemini-3.5-flash-lite`, deterministic 50-member sampling, strict
  existing/new/reject validation, corrective generations, bounded transport
  retries, and nonfatal safe provider-error clusters.
- Restricted each Gemini member sample to exact cleaned text, occurrence
  count, and membership probability; stable processing IDs remain local-only
  for deterministic sampling.
- Added one authoritative atomic schema-version-2 review file under `./reviews`
  with source identity, canonical row mappings, immutable cluster evidence,
  nullable analyst decisions, completion validation, and per-question value
  allocation. Completed files are read-only.
- Replaced the review application with cluster-level and unresolved-answer
  controls, removed draft/category/merge/split/move routes, and simplified the
  CLI to `analyze --input` and `review --review-file`.
- Replaced obsolete tests with V1 discovery, classification, review-file,
  CLI, workbook, embedding, and Google-export coverage. Final focused/full
  suite checkpoint: 91 passing tests.

## Verification Plan

Verification covered ingestion boundaries, all-answer discovery, one-call-per-
cluster classification, provider-error continuation, schema-version-2 review
files, fixed membership, completion validation/allocation, read-only completed
files, CLI command removal, Google Sheets cleanup, and proof that a malformed or
populated `Work` tab has no effect. The final suite passed with `uv run pytest`.

## Open Questions

No V1 implementation question is open. Workbook mutation and respondent-output
destination remain explicit V2 backlog items, not active requirements.
