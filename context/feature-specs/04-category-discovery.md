# Feature 04: New-Category Discovery

## Objective

Discover dense, semantically coherent new groups among answers that were not safely assigned to existing choices, while explicitly preserving noise, rare meanings, and uncertainty.

## Detailed Description

Discovery runs separately for each question so answers from different survey questions can never form a shared cluster. Its input is the normalized `4096`-dimensional vectors for answers left unassigned by Feature 03.

For each question, the stage operates on one point per distinct exact answer
text. Each point retains its occurrence count and complete row-level fan-out,
but repeated respondent occurrences do not contribute duplicate points to
density.

When a question has fewer than
`discovery.min_unique_answer_texts` distinct unassigned texts, the stage skips
PCA and HDBSCAN for that question. Every answer remains traceable as
unresolved/rare evidence and no category is proposed.

Otherwise, the stage reduces the question's vectors in memory using
`sklearn.decomposition.PCA` with:

- requested components from `discovery.pca_components`, default `50`;
- `svd_solver="randomized"`;
- `random_state=42`;
- `whiten=False`; and
- `effective_components = min(requested_components, distinct_answer_count - 1,
  source_dimension)`.

The `distinct_answer_count - 1` cap reflects the maximum informative rank after
PCA centers the samples. The stage records the effective component count and
must not claim that the requested `50` components were produced when fewer were
mathematically possible. `discovery.pca_components` must be a positive integer.

The reduced vectors are passed to `sklearn.cluster.HDBSCAN`. The implementation
must:

- discover dense groups without requiring a predetermined category count;
- identify noise explicitly;
- expose membership probability for each clustered answer; and
- avoid discarding a rare meaning merely because it does not form a dense group.

"Preserve" means a noise or rare answer remains represented as unresolved evidence. It does not automatically mean that it receives its own category.

The reduced vectors are clustered with `sklearn.cluster.HDBSCAN` using this
initial baseline:

```python
HDBSCAN(
    min_cluster_size=3,
    min_samples=None,
    metric="euclidean",
    cluster_selection_method="eom",
    cluster_selection_epsilon=0.0,
    allow_single_cluster=True,
)
```

With scikit-learn, `min_samples=None` makes it equal
`min_cluster_size`, and the point itself is included in that count. Other
HDBSCAN parameters use scikit-learn defaults. These are provisional v1
parameters and must be evaluated later against a manually reviewed calibration
fixture before they are described as optimized.

The raw HDBSCAN cluster label and membership probability are retained for every
point. A point belongs to an accepted cluster membership only when HDBSCAN
assigns it a non-noise cluster label and its membership probability is at least
`discovery.membership_probability_threshold`, default `0.5`. A clustered point
below the threshold becomes unresolved with a low-probability reason while
retaining its raw cluster label and probability as review evidence. Feature 04
does not run a second clustering or automatic reassignment pass.

A cluster becomes a proposed new category only when its accepted members
contain at least `3` distinct exact answer texts by default. The threshold is
configurable through `discovery.min_unique_answer_texts`, which must be an
integer at least `3`. Clusters below the threshold remain represented as
rejected or rare cluster evidence for analyst review; they are not
automatically labeled or coded. Analyst approval remains mandatory for every
proposal that passes the gate.

For every pair of proposal-eligible clusters belonging to the same question,
the stage computes one centroid from each cluster's accepted members in the
original `4096`-dimensional embedding space. A centroid is the arithmetic mean
of the distinct member vectors; occurrence counts do not weight it. The stage
computes cosine similarity between the two centroids and emits a pairwise merge
suggestion when the similarity is at least
`discovery.merge_cosine_similarity_threshold`, default `0.90`. Each suggestion
retains both cluster IDs, the similarity score, and both member sets. Centroids
must be finite and non-zero; otherwise discovery fails instead of emitting
invalid similarity evidence. Each unordered cluster pair is evaluated exactly
once, and suggestions are ordered deterministically by question ID and then by
the two cluster IDs.

The `0.90` merge threshold is a provisional v1 baseline and must be calibrated
later against manually reviewed same-meaning and different-meaning cluster
pairs. The analyst must explicitly confirm every merge suggestion. An approved
merge produces one English label, one Arabic label, one workbook-wide value,
and one combined member set.

The stage produces discovery facts, not final labels or code values. A cluster ID is an internal identifier and must not be used as a final category value.

## Outputs

- Per-question reduced vectors or an in-memory equivalent needed for clustering.
- A cluster or noise identity for every discovery input answer.
- The raw HDBSCAN label and membership probability for every discovery point.
- Accepted cluster membership sets ready for labeling.
- A preserved unresolved set containing noise, rare meanings, rejected clusters, and low-probability members according to the agreed rules.
- Deterministic pairwise semantic-overlap suggestions with original-space
  centroid cosine similarity evidence.

## Success Looks Like

- Only answers from the same question are reduced and clustered together.
- The requested discovery dimension comes from
  `discovery.pca_components`, defaults to `50`, and safely respects the
  dataset's mathematical limits.
- Repeated runs over identical vectors and settings produce the same accepted groups when the selected implementation supports determinism.
- Dense synthetic groups are discovered without preselecting a category count.
- Every input answer is traceable to exactly one discovery result: accepted cluster membership or unresolved/noise.
- Noise and rare meanings remain traceable and are never silently assigned to the nearest cluster.
- Membership probability is retained and the agreed threshold is applied consistently.
- Duplicate respondent occurrences do not change density or centroid
  calculations, while every occurrence retains its row-level fan-out.
- Merge suggestions are limited to clusters from the same question and use the
  configured original-embedding centroid cosine threshold.
- Fixed-vector `pytest` tests cover dense groups, explicit noise,
  low-probability membership, small datasets, duplicate fan-out, centroid merge
  suggestions, and strict separation between questions.
- Calibration tests document the reviewed fixture and results used to revisit
  the provisional HDBSCAN, membership, and merge thresholds.

## Not Included

- Existing-choice verification.
- English or Arabic label generation.
- Numeric code allocation.
- Workbook mutation.
