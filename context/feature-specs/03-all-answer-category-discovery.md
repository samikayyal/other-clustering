# Feature 03: All-Answer Category Discovery

## Objective

Discover fixed-membership, question-scoped clusters from every canonical
answer. Discovery has no existing-choice assignment input and never performs
Gemini calls.

## Inputs and isolation

The stage accepts only the ingested dataset, aligned embeddings/row map, and
fixed V1 settings. Every distinct exact question/text answer is one discovery
point, regardless of whether its meaning resembles an existing choice.
Duplicate respondent occurrences retain their counts and complete row mappings
but never density-weight a point. Answers from different questions can never
share PCA or HDBSCAN state.

## Fixed reduction and clustering

For a question with fewer than three distinct answer texts, skip PCA/HDBSCAN
and emit every canonical answer as unresolved rare evidence.

Otherwise use PCA with requested components `50`, `svd_solver="randomized"`,
`random_state=42`, and `whiten=False`. The effective component count is the
minimum of 50, distinct answer count minus one, and source dimension.

Run HDBSCAN with:

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

Retain raw cluster label and membership probability for every point. A member
is accepted only for a non-noise label and probability at least `0.5`.
Noise, low-probability members, and clusters with fewer than three accepted
distinct texts are unresolved evidence. A proposal-eligible cluster has at
least three accepted distinct texts and immutable membership.

Discovery preserves reasons such as `noise`, `rare_insufficient_distinct_texts`,
`low_probability`, and `rejected_small_cluster`. It does not calculate
original-space centroids, merge suggestions, automatic assignments, or values.

## Outputs

The stage returns deterministic per-question canonical answers, fixed clusters,
cluster member evidence, and unresolved canonical answers. Every canonical
answer appears exactly once in either one fixed proposal-eligible cluster or
the unresolved evidence set.
