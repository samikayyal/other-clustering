# Cluster-First V1 Contract

## Outcome and boundary

`other-cluster` turns supported SurveyCTO `Other` answers into one UTF-8,
schema-version-3 review JSON file. Analysis creates it with `status:
"in_review"`; local-browser completion atomically updates the same file to
`"complete"`. The completed file is V1's sole output and source of truth.

V1 analysis reads only `Survey`, `Code`, and `Data`; the optional read-only
ground-truth evaluation may inspect `Work` only after a review file exists. No
command writes or saves `Work`, and V1 never creates a workbook, CSV, package,
draft, approval, receipt, or finalization artifact. Translation,
split/merge/move editing, free-standing categories, value editing, and
respondent output are out of scope.

## Commands and secrets

```text
other-cluster analyze --input PATH_OR_GOOGLE_SHEETS_URL
other-cluster review --review-file REVIEW_JSON
other-cluster review --review-file REVIEW_JSON --ground-truth XLSX_OR_GOOGLE_SHEET
other-cluster evaluate --review-file REVIEW_JSON
other-cluster evaluate --review-file REVIEW_JSON --ground-truth XLSX_OR_GOOGLE_SHEET
```

`analyze` prints detailed human-readable progress, including stage totals and
per-batch, per-question, and per-cluster completion, to stderr. Its final
machine-readable run summary remains the only output written to stdout.
Gemini diagnostics on stderr include the question, cluster, generation, and
transport-attempt context for every JSON-escaped response body and every
secret-safe provider error. Provider errors expose only the exception type and
HTTP status, when available; they never include API keys or request URLs.

`evaluate` is read-only. It validates one review JSON file and prints one
section per question with canonical-answer cluster counts and sizes, clustered
versus unresolved percentages, largest-cluster share, representative member
texts, and the persisted Gemini acceptance, rejection, or provider-error result
for each cluster. Percentages use canonical answer texts as their denominator;
exact duplicate responses remain visible through each answer's occurrence count
in the review file.

With `--ground-truth`, `evaluate` additionally reads the reference workbook's
`Work` tab strictly as benchmark data. It aligns rows by `KEY`, reads each
question's raw / `_Coded` / `_C1` triplet, and reports label-invariant Adjusted
Rand Index plus pairwise precision, recall, and F1 for canonical answer texts
and respondent occurrences. Blank human codes, missing keys, source-text
mismatches, and conflicting duplicate-text codes are excluded and reported.
This evaluation-only path never supplies `Work` values to analysis, embedding,
clustering, classification, review, or completion.

The same optional `--ground-truth` input on `review` displays the cached,
read-only benchmark in the browser: overall canonical and occurrence-weighted
metrics plus per-question metrics. It does not add benchmark data to the review
JSON or change the analyst workflow.

Only `NEBIUS_API_KEY` and `GEMINI_API_KEY` are loaded from the process
environment or an optional current-directory `.env`. There is no TOML,
ordinary `OTHER_CLUSTER_*` setting, output flag, overwrite flag, or
finalization command. Google Sheets exports use the operating system temporary
directory and are cleaned up after the run.

## Workbook ingestion

Required headers are `Survey(type, name, label:english, label:arabic)`,
`Code(list_name, value, label:english, label:arabic)`, and `Data(KEY` plus
supported answer columns). Fixed headers are case-insensitive; dynamic question
IDs are case-sensitive. `Code.list_name` is the exact Data-column identifier;
deterministic normalization is only for matching `Survey.name` metadata. The
`_other` suffix is removed for that lookup; `_exp` and `_explain` try both the
exact ID and the suffix-stripped ID before applying numeric-separator
normalization.

`value: -96`, `-9999`, and `-9998` are excluded from existing choices.
One-sided bilingual labels use the nonblank side;
two blank labels are invalid. Blank or HTML-empty answers are skipped; numeric
answers are warned and skipped; formula, merged, and error cells are invalid.
Hidden Data rows are processed. Original-language answer text is retained,
exact duplicates are canonicalized once per question, and each canonical answer
retains its occurrence count and complete respondent/cell mappings.

## Analysis pipeline

1. Embed each canonical question/text answer with Nebius
   `Qwen/Qwen3-Embedding-8B`, 4096-dimensional unit vectors, batches of at
   most 32. The SQLite cache is exact-text derived data keyed by one embedding
   contract fingerprint; cache data with a different contract must be deleted
   and rebuilt.
2. Cluster every question independently. PCA requests 50 randomized,
   non-whitened components (seed 42), capped by sample count minus one and
   vector dimension. HDBSCAN uses a min cluster size of 8, reduced to the
   question's distinct canonical-answer count when that count is smaller,
   Euclidean/EOM, `min_samples=2`, epsilon 0, and does not allow one
   cluster. Accepted membership requires probability at least 0.5; a proposal
   requires three accepted distinct texts.
3. Call Gemini `gemini-3.5-flash-lite` once for each proposal-eligible fixed
   cluster, pacing all requests and transport retries at no more than 15 per
   rolling 60 seconds per process. It may select a same-question choice,
   propose one valid bilingual category, or reject the cluster. Transport
   exhaustion becomes a safe, reviewable provider-error warning. Exhausting
   corrective generations for locally invalid responses instead leaves the
   cluster unresolved with an invalid-response warning; it is not reported as
   a provider outage. Arabic category labels may contain ASCII or Arabic-Indic
   digits when they also contain Arabic letters.
4. Write `./reviews/<normalized_source_stem>_<analysis_run_id>.json` with the
   source byte size and SHA-256.

Provider responses, workbooks, and cached vectors are validated at their
boundaries. Synchronous frozen stage results are trusted; persisted review JSON
and browser HTTP input are validated strictly.

## Review document and completion

`questions[].answers` is the sole detailed canonical-answer store: text,
occurrence count, row mappings, and discovery evidence live there. Clusters
contain immutable member processing IDs plus their proposal and analyst
decision; unresolved items contain a processing ID, reason, and decision. The
browser resolves member presentation through the canonical answer map.

Cluster membership is immutable. Each cluster permits exactly one disposition:
same-question existing choice, one valid bilingual new category, or unresolved.
Unresolved canonical answers permit only existing choice or unresolved.
Completion requires a nonblank analyst name and a decision for all items.

Only final new-category cluster decisions receive a value. Per question,
existing integers greater than 100 are reserved, then stable cluster IDs are
processed in order and assigned the smallest unused integer above 100. Values
may repeat between questions. Completed files are read-only.
