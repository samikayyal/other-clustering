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

- Question-macro canonical F1: 0.678.
- Question-macro canonical ARI: 0.766.
- Pooled canonical F1: 0.717.
- Pooled canonical ARI: 0.692.
- Pooled canonical coverage: 98.2%.
- Occurrence-weighted F1: 0.758.
- Occurrence-weighted ARI: 0.726.
- Automatic groups: 73.
- Unresolved canonical answers: 32 of 1,767.

This is a 0.539 absolute increase in the primary macro F1 and a 0.523 increase
in macro ARI over the frozen HDBSCAN baseline. Relative to the prior normalized
character-only production policy, it adds 0.088 macro F1 and 0.134 macro ARI.
Gemini remains downstream for category labeling and does not alter membership.

## Second improvement round

The second round compared the production character policy, cached answer-only
Qwen3 embeddings, instruction-aware Qwen3 embeddings, blended distance
matrices, complete/single/average linkage, and observable question routing.
Ground truth selected policies but never entered a provider request, feature
matrix, clustering call, or review artifact.

| Candidate | Macro F1 | Macro ARI | Finding |
| --- | ---: | ---: | --- |
| Normalized character-only production policy | 0.590 | 0.632 | Strong starting point, but one global threshold remained limiting |
| Character + answer-only Qwen blend | 0.619 | 0.693 | Semantic agreement improved both objectives |
| Character + instruction-aware Qwen blend | 0.631 | 0.693 | Task instruction improved F1 further |
| One observable answer-count split | 0.643 | 0.714 | Question size was a useful reusable routing signal |
| Five answer-count bands | 0.678 | 0.766 | Selected production policy |

The selected bands are `2-20`, `21-50`, `51-100`, `101-200`, and `>200`
canonical answers. They vary only semantic/lexical distance weights, linkage,
and threshold. The policy never branches on a question ID, label, existing
choice text, or ground-truth value.

Single-linkage did not enter the leading candidates and was rejected because
its neighborhood chaining added no benchmark value. Automatic assignment to
existing choices remained rejected from the first round. A Gemini embedding
comparison was started, but the configured free-tier key allows only 100
embedded inputs per minute; it was stopped after the first free batch because
it could not provide a practical full-run feedback loop.

## Remaining improvement paths

The largest remaining errors are in `hh_con_dairy_g_change`,
`in_src_1st_other`, and `other_support_text`. Two one-item questions necessarily
score pairwise F1 as zero because neither truth nor prediction contains a pair.
Possible next experiments, in priority order:

1. Complete a second-provider embedding comparison with Gemini Embedding 2,
   OpenAI `text-embedding-3-large`, or Voyage 4 when an adequately provisioned
   key is available.
2. Test constrained pairwise reranking only for uncertain cluster boundaries;
   avoid all-pairs cost by starting from the selected ensemble neighborhoods.
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
