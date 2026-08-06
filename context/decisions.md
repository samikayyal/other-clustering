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
- **Completion allocation:** new category values are assigned per question in
  stable cluster-ID order and may repeat across question lists.
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
