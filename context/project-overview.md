# Project Overview

## Product Summary

`other-cluster` groups free-text answers submitted through an `Other` option
into question-scoped review categories. V1 accepts a local `.xlsx` workbook or
a native Google Sheets URL, discovers coherent answer clusters, asks Gemini to
classify eligible clusters, and lets an analyst complete one authoritative
review JSON file in a local browser.

V1 reads only `Survey`, `Code`, and `Data`. The `Work` worksheet is completely
outside the product boundary: it is never required, opened, validated,
interpreted, or written. No workbook is mutated or produced by V1.

Answers remain in their original language. HTML markup is removed from
question labels and answers while retaining text content. Arabic, dialectal
Arabic, and English are supported without translation before embedding or
classification.

## Primary Outcome

For each supported question, V1 produces one UTF-8 review file that contains:

1. the source-workbook identity and bilingual question metadata;
2. all canonical exact answer texts, occurrence counts, respondent keys, and
   source row/cell mappings;
3. every same-question existing choice;
4. discovery evidence for every canonical answer;
5. fixed-membership clusters with one Gemini proposal or provider-error state;
6. unresolved noise, rare, low-probability, and rejected-small-cluster evidence;
   and
7. nullable authoritative analyst decisions.

The analyst may complete the file in the local review application. Completion
validates every decision, allocates values only to final new categories, and
atomically saves the same file with `status: "complete"`. This completed JSON
is the V1 output and source of truth. There is no finalization command and no
workbook output.

## Five V1 Stages

1. **Workbook ingestion and analysis CLI** — accept local or Google Sheets
   input, validate only `Survey`, `Code`, and `Data`, and build exact row maps.
2. **Original-language embeddings** — embed each distinct question/text pair
   with Nebius or reuse a validated SQLite exact-text cache entry.
3. **All-answer category discovery** — cluster every canonical answer
   independently within its question using the fixed PCA/HDBSCAN defaults.
4. **Cluster classification and review-file creation** — make one Gemini call
   per proposal-eligible cluster and write one schema-version-2 review file.
5. **Analyst review and completion** — review whole clusters and unresolved
   canonical answers in the browser, validate the complete result, allocate
   per-question values, and atomically mark the file complete.

## CLI

```text
other-cluster analyze --input PATH_OR_GOOGLE_SHEETS_URL
other-cluster review --review-file REVIEW_JSON
```

Analysis settings are fixed in code. Only `NEBIUS_API_KEY` and
`GEMINI_API_KEY` are loaded from the process environment or an optional
current-directory `.env`. There is no TOML configuration, ordinary
`OTHER_CLUSTER_*` configuration, analysis-time output path, overwrite flag, or
finalization command.

Google Sheets input is exported as a temporary XLSX using the response's
filename and cleaned up after the run. The review file is written to:

```text
./reviews/<normalized_source_stem>_<analysis_run_id>.json
```

## Workbook Contract

The required sheets and columns are:

- `Survey`: `type`, `name`, `label:english`, `label:arabic`;
- `Code`: `list_name`, `value`, `label:english`, `label:arabic`; and
- `Data`: `KEY` plus answer columns whose dynamic names match supported
  `Code.list_name` values.

Fixed headers are case-insensitive; dynamic question identifiers remain
case-sensitive. `Code.list_name` identifies the question and deterministic
normalization is used only to find matching `Survey.name` metadata. The
`value: -96` Other choice is excluded. One-sided bilingual labels inherit the
nonblank side; both blank sides are invalid.

Blank answers are skipped, numeric answer cells are skipped with warnings, and
HTML tags are removed immediately. Exact duplicates are embedded and clustered
once per question while every respondent occurrence fans out through its own
answer ID and source mapping. Hidden `Data` rows are processed. Other sheets
are ignored, including any malformed or populated `Work` sheet.

## Fixed Discovery Contract

- Nebius model: `Qwen/Qwen3-Embedding-8B`, 4096-dimensional unit vectors.
- PCA: requested components `50`, randomized solver, `random_state=42`, no
  whitening, effective components capped by sample count minus one and source
  dimension.
- HDBSCAN: `min_cluster_size=3`, `min_samples=None`, Euclidean/EOM, epsilon
  `0`, single cluster allowed.
- Accepted membership probability: `0.5`.
- Proposal minimum: three distinct accepted texts.
- Every canonical answer is a discovery point; occurrence counts never weight
  density.

Only proposal-eligible clusters reach Gemini. Noise, rare, low-probability,
and rejected-small-cluster answers remain unresolved evidence.

## Review and Value Rules

System cluster membership is immutable. An analyst chooses one whole-cluster
disposition: one same-question existing choice, one new bilingual category, or
unresolved. Noise and rare canonical answers allow only an existing choice or
unresolved. Members cannot be split, merged, moved, or assigned independently,
and free-standing categories are not allowed.

Existing-choice reuse happens at cluster classification time. Values are
allocated only when review completes, independently for each question's
`Code` list. Each final new category receives the smallest unused integer
greater than `100` among that question's existing choices, processed by stable
cluster ID. Values may repeat across different question lists.

## Out of Scope and V2 Backlog

V1 does not translate answers, edit the survey instrument, interpret `Work`,
write `Code`, write respondent output, create CSV artifacts, persist package /
draft / approval / receipt lifecycles, or provide split/merge/manual-category
editing.

V2 may add workbook mutation and a defined respondent-output destination after
the V1 review contract has been validated. Those mechanics are backlog only
and are not active requirements.
