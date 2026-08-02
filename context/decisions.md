# Architecture Decisions

- **Cluster-first V1:** canonical answers are discovered per question before
  one Gemini call per proposal-eligible fixed cluster.
- **Single review artifact:** schema-version-3 JSON is both immutable evidence
  and editable analyst state; completion atomically updates the same file.
- **Canonical answer facts:** detailed answer information has one home in
  `answers`; clusters and unresolved collections reference processing IDs.
- **Boundary validation:** validate workbooks, provider responses, cache reads,
  persisted JSON, and HTTP input; trust internal frozen stage results.
- **Derived cache compatibility:** an embedding-contract fingerprint identifies
  the fixed V1 embedding policy. Incompatible caches are rebuilt, not migrated.
- **Completion allocation:** new category values are assigned per question in
  stable cluster-ID order and may repeat across question lists.
- **V2 backlog:** workbook mutation and respondent output remain outside V1.
- **Evaluation-only ground truth:** the optional `evaluate --ground-truth` path
  may read `Work` after a review artifact exists. Human codes are never inputs
  to production discovery; benchmark alignment is by respondent `KEY` and exact
  question answer text to prevent evaluation against a different source version.
- **Density calibration:** HDBSCAN keeps a stable minimum cluster size of 8 but
  uses `min_samples=2`; the hand-coded benchmark showed that decoupling density
  conservatism from cluster size recovers paraphrases while preserving the
  multi-cluster guard and the 0.5 membership threshold.
