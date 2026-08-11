# Architecture Decisions

- **Cluster-first V1:** canonical answers are discovered per question before
  one Gemini call per proposal-eligible fixed cluster.
- **Single review artifact:** schema-version-3 JSON is both immutable evidence
  and editable analyst state; completion atomically updates the same file.
- **Canonical answer facts:** detailed answer information has one home in
  `answers`; clusters and unresolved collections reference processing IDs.
- **Boundary validation:** validate workbooks, provider responses, persisted
  JSON, and HTTP input; trust internal frozen stage results.
- **Observable lexical-semantic discovery routing:** automatic membership uses
  question-scoped normalized character TF-IDF plus validated Qwen3 semantic
  embeddings. Canonical-answer count selects one of five fixed distance,
  weighting, linkage, and threshold policies; question IDs and ground-truth
  values never participate. The policy is deliberately fitted to the frozen
  WFP benchmark and is not evidence of cross-survey generalization.
- **Semantic embedding boundary:** Nebius `Qwen/Qwen3-Embedding-8B` produces
  answer-only and inline instruction-aware clustering vectors. Exact provider
  inputs and unit vectors use the existing transactional SQLite cache. Missing
  vectors fail analysis closed; cached vectors allow replay without a key.
- **Completion allocation:** confirmed active new-category decisions receive
  the smallest unused same-question integer above 100 in stable group creation
  order and values may repeat across question lists.
- **V2 backlog:** workbook mutation and respondent output remain outside V1.
- **Evaluation-only ground truth:** the optional `evaluate --ground-truth` path
  may read `Work` after a review artifact exists. Human codes are never inputs
  to production discovery; benchmark alignment is by respondent `KEY` and exact
  question answer text to prevent evaluation against a different source version.
  Ground-truth codes `-9998` and `-9999` are excluded from the benchmark
  population and every reported metric. Canonical-answer quality is reported
  both pooled and as an equal-question-weight macro across scored questions.
- **Answer-count calibration:** WFP-only iteration selected reusable bands at
  20, 50, 100, and 200 canonical answers after comparing lexical, semantic,
  blended, instruction-aware, density-based, and linkage variants. This is
  benchmark-fitted evidence, not a claim of cross-survey generalization.

## Accepted version-4 decisions

The identity-free artifact, revisioned decision/confirmation commands, legacy
read-only boundary, structural editing, Undo, progress, completion, and locking
are implemented. Evaluation integration remains a later slice of the accepted
design.

- **Mutable schema-version-4 workspace:** New version-4 analyses will replace
  immutable review membership with server-owned answer-location commands.
  Every canonical answer remains an indivisible unit and occupies exactly one
  current location: one active group, Needs attention, or Excluded from coding.
- **Explicit two-state group review:** Active groups use only `needs_review`
  and `confirmed`. Confirmation is an explicit action over the current
  membership and coding decision; any applied membership or decision change
  returns affected non-empty groups to `needs_review`.
- **Revisioned command boundary:** The browser will submit narrow mutation
  commands with an expected review revision. The server will atomically own
  invariant enforcement, state mutation, compact history, one-level Undo, and
  persistence; stale mutations will fail without automatic replay.
- **Legacy isolation:** Every schema-version-3 artifact will become view-only
  when version 4 ships. There will be no version-3 migration or upgrade path.
- **Developer-only ground truth:** Ground-truth data and metrics will be removed
  from the analyst workflow. The separate developer evaluation path will score
  immutable automatic discovery membership, never reviewer edits.
- **Identity-free review:** Version 4 will contain no analyst identity,
  attribution, or name-based completion requirement.
