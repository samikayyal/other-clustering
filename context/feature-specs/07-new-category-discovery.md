# Spec 07 — New Category Discovery

**Status:** Planned
**Dependencies:** Spec 03, Spec 06
**Implementation order:** 07 of 11

## Outcome

Substantive variants not confidently assigned to existing choices are grouped through deterministic, bounded density discovery. The pipeline preserves noise and rare meanings, creates stable run-local candidate IDs, and never forces unrelated clusters together to satisfy the category cap.

## Discovery population

- Start with substantive eligible variants that are not confidently assigned to an existing choice.
- Reuse their existing embedding rows; do not re-embed or translate them.
- Apply source-row frequency only through bounded expansion: replicate each unique variant `min(occurrence_count, expansion_cap)` times, with default `expansion_cap = 20`.
- Record the expansion cap and expanded counts in the manifest and category evidence.

## Deterministic clustering

1. Sort unique variants by `variant_id` before constructing the clustering input.
2. Apply deterministic PCA to the configured target dimension, default 50 and bounded by sample size and original dimension.
3. Use streaming/incremental processing or an explicit working-memory ceiling where full PCA/clustering buffers could exceed capacity.
4. Run HDBSCAN-style density clustering with fixed parameters and default `min_cluster_size = 3`.
5. Preserve noise; do not assign noise to the nearest cluster.
6. Require a configurable minimum membership probability for an automatic new-category assignment, with the initial default taken from the Spec 02b calibration record (pre-calibration placeholder `0.80`).
7. Preserve one- and two-answer meanings as `rare_candidate` records rather than collapsing them into a residual category.
8. Order promoted clusters deterministically by expanded size and stable medoid identity.
9. Assign run-local IDs such as `NEW-001`, `NEW-002`, and so on.
10. If more than `max_new_categories = 50` promoted categories emerge, preserve valid existing-choice assignments, stop before Gemini cluster labeling and composite review, mark members of promoted new clusters `unresolved_category_cap`, and fail category finalization with `category_cap_diagnostic_failure`. Never select the largest 50, merge unrelated clusters, or spend labeling budget to pass the cap.

## Cluster representation

Represent each promoted new category by its stable medoid’s original 4096-dimensional embedding. Use that medoid for cluster-level comparison with existing-choice anchors and for downstream composite candidate ranking. Generated bilingual labels are explanatory audit fields only and are never vector representations.

## Category evidence

For each promoted cluster, collect:

- frequent examples and stable medoids;
- boundary cases and membership probabilities;
- occurrence-expanded and unique-variant counts;
- represented languages and detector warnings;
- relationship to existing-choice anchors;
- stable medoid identity and original embedding row;
- review/proposal status.

The next slice owns bilingual labeling and cluster-level reclassification checks. This slice must expose enough evidence for those operations without mutating the input workbook or official choices.

## Implementation tasks

1. Implement bounded occurrence expansion without duplicating the full vector matrix unnecessarily.
2. Implement deterministic PCA/IncrementalPCA selection and memory diagnostics.
3. Implement HDBSCAN discovery, probability thresholds, noise, and rare-candidate paths.
4. Implement stable medoid/category ordering and run-local IDs.
5. Implement stable medoid representations and category-cap diagnostic failure with provisional evidence for downstream audit output.

## Tests

- Canonical variant ordering produces stable discovery input.
- `min(occurrence_count, expansion_cap)` is applied exactly and recorded.
- PCA respects target/sample/original-dimension bounds and configured memory ceiling.
- HDBSCAN noise remains unassigned; low-membership items do not become automatic new categories.
- One- and two-answer meanings become rare candidates.
- Stable category IDs remain unchanged under equivalent input ordering.
- Stable medoid embeddings are used for cluster-level comparisons and never replaced by generated labels.
- More than 50 promoted categories preserves existing-choice assignments, stops before labeling/composite review, marks new-cluster members `unresolved_category_cap`, and produces provisional evidence without forced merging.
- Existing-choice-assigned variants are excluded from discovery.
- Memmap rows are reused and no second full vector JSON matrix is created.

## Acceptance criteria

- Discovery produces deterministic candidate clusters and explicit noise/rare outcomes for the same validated and fingerprinted input.
- No low-membership or noise answer is silently forced into a new category.
- Category-cap overflow is visible in the run status and manifest, and the provisional output path is explicit.
- Downstream labeling receives representative, boundary, language, and anchor evidence for every promoted cluster.

## Non-goals

- LLM category labels, existing-choice reclassification, composite review, final assignment, or workbook writing.
