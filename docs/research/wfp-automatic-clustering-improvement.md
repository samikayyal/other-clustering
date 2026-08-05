# WFP Automatic Clustering Improvement

## Scope

This experiment uses only the frozen WFP FSOM Q2 2026 benchmark. Ground-truth
codes are available to the evaluator for repeated scoring and policy selection,
but are never inputs to representation, clustering, classification, or review.
The result is benchmark-fitted and does not establish cross-survey
generalization.

The primary objective is equal-question-weight pairwise F1 over distinct
canonical answer texts. Equal-question-weight ARI is a secondary guardrail.
Codes `-9998` and `-9999`, blank codes, missing keys, exact-text mismatches, and
ambiguous duplicate-text codes are excluded.

## Frozen baseline

- Scored population: 774 canonical answers across 12 questions and 63 human
  groups.
- Question-macro canonical F1: 0.139.
- Question-macro canonical ARI: 0.243.
- Pooled canonical F1: 0.404.
- Pooled canonical coverage: 57.1%.
- Occurrence-weighted F1: 0.705.

The prior Qwen embedding, PCA, and HDBSCAN policy left many smaller questions
entirely unresolved. Large questions dominated the pooled score, which is why
the equal-question metric is the headline result.

## Experiments

All candidates were question-scoped and received only answer text or cached
answer embeddings.

| Candidate | Macro F1 | Macro ARI | Finding |
| --- | ---: | ---: | --- |
| Qwen + PCA-50 + HDBSCAN baseline | 0.139 | 0.243 | Low coverage and severe fragmentation |
| Qwen + PCA-50 + cosine DBSCAN | 0.277 | 0.300 | Better recall, but broad clusters in large questions |
| Character TF-IDF/SVD + cosine DBSCAN | 0.589 | 0.559 | High recall with more merging |
| Character TF-IDF/SVD + average linkage | 0.589 | 0.616 | Best balanced unnormalized policy |
| Arabic-normalized character TF-IDF/SVD + average linkage | 0.590 | 0.632 | Selected policy |

Character features use word-boundary n-grams of length 2-5. The selected policy
uses at most 50 deterministic SVD components and average-linkage agglomerative
clustering at cosine distance 0.9125. Clusters with two or more canonical texts
are proposal-eligible; singletons remain unresolved.

Automatic assignment to existing `Code` choices was also tested. Only 51 of
the 774 scored answers use existing choice values. Character-similarity anchors
and Qwen semantic anchors did not improve F1 or ARI at any safe threshold, so
that stage was not added.

## Production replay

- Question-macro canonical F1: 0.590.
- Question-macro canonical ARI: 0.632.
- Pooled canonical F1: 0.616.
- Pooled canonical ARI: 0.583.
- Pooled canonical coverage: 96.8%.
- Occurrence-weighted F1: 0.741.
- Automatic groups: 61.
- Unresolved canonical answers: 37 of 1,767.

This is a 0.451 absolute increase in the primary macro F1 and a 0.389 increase
in macro ARI. Discovery is now local and no longer requires Nebius embeddings
or an embedding cache. Gemini remains downstream for category labeling and
does not alter membership.

## Remaining improvement paths

The largest remaining errors are in `hh_con_dairy_g_change`,
`hh_con_vegies_g_change`, `in_src_1st_other`, and `other_support_text`.
Possible next experiments, in priority order:

1. Add observable question-type routing, for example short categorical answers
   versus longer explanations, while keeping one global policy per type.
2. Test a lexical-semantic ensemble that accepts a merge only when character
   and multilingual semantic neighborhoods agree.
3. Use stability selection across nearby distance thresholds to retain robust
   groups and leave unstable boundary answers unresolved.
4. Test constrained automatic existing-choice assignment only for questions
   whose `Code` choices cover most ground-truth groups; the global anchor policy
   was not effective.
5. Audit human group consistency and the one exact-text mismatch before using
   small score changes to choose another policy.

Further tuning against this same workbook will increase benchmark overfitting.
Any later generalization claim requires a new independently coded survey or a
new frozen revision that was not used for policy selection.
