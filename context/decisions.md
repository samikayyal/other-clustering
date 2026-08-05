# Architecture Decisions

- **Cluster-first V1:** canonical answers are discovered per question before
  one Gemini call per proposal-eligible fixed cluster.
- **Single review artifact:** schema-version-3 JSON is both immutable evidence
  and editable analyst state; completion atomically updates the same file.
- **Canonical answer facts:** detailed answer information has one home in
  `answers`; clusters and unresolved collections reference processing IDs.
- **Boundary validation:** validate workbooks, provider responses, persisted
  JSON, and HTTP input; trust internal frozen stage results.
- **Local lexical discovery:** automatic membership uses question-scoped,
  normalized character TF-IDF, deterministic SVD, and average-linkage cosine
  clustering. The WFP benchmark favored recurring lexical forms over remote
  semantic embeddings, so discovery has no embedding-provider or cache boundary.
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
- **Lexical distance calibration:** the WFP-only iterative benchmark selected
  average-linkage cosine distance `0.9125` after comparing HDBSCAN, DBSCAN, and
  agglomerative policies. This is benchmark-fitted evidence, not a claim of
  cross-survey generalization.
