# Feature 04: New-Category Discovery

## Objective

Discover dense, semantically coherent new groups among answers that were not safely assigned to existing choices, while explicitly preserving noise, rare meanings, and uncertainty.

## Detailed Description

Discovery runs separately for each question so answers from different survey questions can never form a shared cluster. Its input is the normalized `4096`-dimensional vectors for answers left unassigned by Feature 03.

For each question, the stage reduces vectors to a configured discovery dimension using scikit-learn:

- default requested dimension: `50`;
- `PCA` for deterministic in-memory reduction; or
- `IncrementalPCA` when bounded-memory processing is necessary.

The effective component count must obey the mathematical limits imposed by the number of answers and source dimensions. It must not pretend that `50` components were produced when fewer are possible.

- [INPUT REQUIRED: Define the dataset-size or memory threshold for choosing PCA versus IncrementalPCA.]
- [INPUT REQUIRED: Define IncrementalPCA batch size and whether it is a fixed setting or derived from available rows.]
- [INPUT REQUIRED: Define the minimum number of unassigned answers required to run reduction and clustering, plus behavior below that minimum.]
- [INPUT REQUIRED: Confirm the random state and solver settings required for deterministic PCA behavior.]

The reduced vectors are passed to an HDBSCAN-style density-clustering implementation. The implementation must:

- discover dense groups without requiring a predetermined category count;
- identify noise explicitly;
- expose membership probability for each clustered answer; and
- avoid discarding a rare meaning merely because it does not form a dense group.

"Preserve" means a noise or rare answer remains represented as unresolved evidence. It does not automatically mean that it receives its own category.

The concrete discovery contract is not yet supplied:

- [INPUT REQUIRED: Select the HDBSCAN implementation/package.]
- [INPUT REQUIRED: Define `min_cluster_size`, `min_samples`, distance metric, cluster selection method, and any other non-default parameter required for acceptance.]
- [INPUT REQUIRED: Define the minimum membership probability for assigning an answer to an accepted cluster.]
A cluster becomes a proposed new category only when it contains at least `3` distinct exact answer texts by default. The threshold is configurable through `discovery.min_unique_answer_texts` and counts distinct original answer strings rather than respondent occurrences. Clusters below the threshold remain represented as rejected or rare cluster evidence for analyst review; they are not automatically labeled or coded. Analyst approval remains mandatory for every proposal that passes the gate.
- [INPUT REQUIRED: Define whether low-probability members become noise/unresolved or may be reconsidered later.]
- [INPUT REQUIRED: Define whether duplicate answer frequency contributes multiple weighted points to density or one unique point with a count.]
The system detects semantic overlap between separate clusters, such as "Lebanese" and "from Lebanon," and emits a merge suggestion for analyst confirmation. The analyst must explicitly confirm the suggestion. An approved merge produces one English label, one Arabic label, one workbook-wide value, and one combined member set.

The stage produces discovery facts, not final labels or code values. A cluster ID is an internal identifier and must not be used as a final category value.

## Outputs

- Per-question reduced vectors or an in-memory equivalent needed for clustering.
- A cluster or noise identity for every discovery input answer.
- Membership probability for every clustered answer when supplied by the chosen implementation.
- Accepted cluster membership sets ready for labeling.
- A preserved unresolved set containing noise, rare meanings, rejected clusters, and low-probability members according to the agreed rules.

## Success Looks Like

- Only answers from the same question are reduced and clustered together.
- The requested discovery dimension defaults to `50`, while the effective dimension safely respects the dataset's mathematical limits.
- Repeated runs over identical vectors and settings produce the same accepted groups when the selected implementation supports determinism.
- Dense synthetic groups are discovered without preselecting a category count.
- Every input answer is traceable to exactly one discovery result: accepted cluster membership or unresolved/noise.
- Noise and rare meanings remain traceable and are never silently assigned to the nearest cluster.
- Membership probability is retained and the agreed threshold is applied consistently.
- Fixed-vector `pytest` tests cover dense groups, explicit noise, low-probability membership, small datasets, and strict separation between questions.

Full acceptance cannot be tested until the HDBSCAN implementation, parameters, and remaining cluster/member acceptance rules are supplied.

## Not Included

- Existing-choice verification.
- English or Arabic label generation.
- Numeric code allocation.
- Workbook mutation.
