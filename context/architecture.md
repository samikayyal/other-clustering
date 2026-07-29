# Architecture

## Architectural Goal

Build the smallest safe pipeline that turns a supported SurveyCTO coding
workbook into one question-scoped, analyst-completed JSON review artifact.
V1 ends when that file is atomically marked complete. The application does not
produce or mutate a workbook.

## System Context

```text
Operator
  |
  | other-cluster analyze --input PATH_OR_GOOGLE_SHEETS_URL
  v
Analysis process
  |-- resolves/downloads temporary XLSX input
  |-- reads only Survey, Code, and Data
  |-- embeds canonical question/text answers through Nebius/cache
  |-- clusters every canonical answer independently per question
  |-- classifies proposal-eligible clusters through Gemini
  `-- atomically writes ./reviews/<stem>_<run_id>.json
                                  |
                                  v
                    other-cluster review --review-file REVIEW_JSON
                                  |
                                  `-- local Flask/Jinja browser review
                                      and atomic completion of same JSON
```

`Work` is outside the system context and must never be accessed. No output
workbook, CSV extraction, package, draft, approval, receipt, or second review
snapshot exists in V1.

## Five Ordered Stages

1. **Ingest** — resolve local `.xlsx` or native Google Sheets input, use a
   temporary export for links, validate `Survey`, `Code`, and `Data`, extract
   bilingual questions, choices, canonical answers, and exact row mappings.
2. **Embed** — deduplicate exact text within each question, reuse compatible
   SQLite vectors, or call Nebius for missing vectors. Keep aligned vectors and
   row maps in memory only.
3. **Discover** — pass every canonical answer to per-question PCA/HDBSCAN.
   Preserve raw labels/probabilities and classify each point as accepted fixed
   cluster membership or unresolved evidence. Do not compute centroids,
   merge suggestions, or pre-assign answers.
4. **Classify and write** — call Gemini once for each proposal-eligible cluster.
   The provider may select a supplied same-question choice, propose one
   bilingual category, or reject the cluster. Provider exhaustion is a warning
   and leaves a fixed provider-error cluster. Build and atomically write one
   schema-version-2 review file.
5. **Review and complete** — the local browser edits only nullable authoritative
   decisions. Completion validates fixed membership, same-question references,
   labels, analyst name, and full coverage; allocates new values per question;
   then atomically saves `status: complete` in the same file.

## Responsibility Boundaries

### CLI and input sources

The CLI exposes only `analyze --input` and `review --review-file`. It loads
only `NEBIUS_API_KEY` and `GEMINI_API_KEY` from the process environment or an
optional current-directory `.env`. Discovery settings, provider models,
timeouts, and retry counts are fixed constants in code. Google Sheets export
owns temporary-file creation and cleanup for the full analysis run.

### Workbook ingestion

Workbook code is the only boundary that interprets sheet and cell structure. It
validates and reads exactly `Survey`, `Code`, and `Data`, ignores all other
sheets, removes HTML tags from extracted labels/answers, skips blank and
numeric answers, and retains respondent `KEY`, source row, source column, and
exact source cell. It never reads `Work`, even if present and malformed. It
never saves a workbook.

### Embeddings

The Nebius boundary sends original-language exact answer text to
`Qwen/Qwen3-Embedding-8B` in batches of 32 and validates 4096 finite,
approximately unit-length vectors without renormalizing. A valid SQLite exact-
text cache is reused. A missing key is fatal only when a provider call is
needed; an empty or completely cached dataset needs no key.

### Discovery

Discovery receives only the dataset, aligned embeddings/row map, and fixed
settings. It has no existing-choice assignment input. It uses one point per
distinct exact question/text answer, keeps occurrence counts as evidence, and
does not density-weight duplicates. HDBSCAN noise, rare points, low-
probability members, and rejected-small-cluster members remain unresolved.
Question boundaries are absolute.

### Cluster classification

Gemini receives one request per eligible cluster, with question context, all
same-question existing choices, and a deterministic member sample. The model
is `gemini-3.5-flash-lite`. Structured response validation enforces the
existing/new/reject cross-field contract and label quality rules. Transport
retries cover network errors, timeouts, 408, 429, and 5xx for five attempts;
up to three structured generations are allowed for invalid responses or label
quality failures. A valid rejection is final. Exhaustion becomes a safe,
nonfatal provider-error warning.

### Review persistence

The review file is both immutable evidence and editable state. Its schema
version is `2`; it contains no duplicate proposal/final snapshot, operation
logs, approval IDs, hashes of the review file, receipts, replay state, or merge
graph. Analysis creates it with `status: in_review`; the browser atomically
replaces it after each valid edit and on completion. A completed file is
read-only and cannot be reopened for amendment.

## Core Data Records

Conceptual records should remain simple dataclasses or dictionaries.

### Question

- question ID and exact `Data` source column;
- bilingual question text;
- same-question existing choices;
- canonical answer records;
- discovery evidence, fixed clusters, and unresolved evidence.

### Canonical answer

- stable processing ID;
- question ID and exact cleaned text;
- occurrence count;
- complete row-level mappings containing answer ID, respondent `KEY`, sheet,
  row, column, and coordinate;
- nullable discovery evidence and zero or one fixed cluster reference.

### Cluster

- stable cluster ID scoped to its question;
- immutable canonical member processing IDs;
- deterministic member evidence with exact text, occurrence count, and raw
  membership probability;
- Gemini proposal, including `provider_error` when classification exhausted;
- one nullable authoritative analyst decision.

### Unresolved canonical answer

- processing ID;
- reason (`noise`, `rare_insufficient_distinct_texts`, `low_probability`,
  `rejected_small_cluster`, or provider-related evidence);
- one nullable authoritative decision limited to existing choice or unresolved.

### Review file

Top level:

```json
{
  "schema_version": 2,
  "analysis_run_id": "lowercase UUIDv4",
  "status": "in_review | complete",
  "created_at_utc": "timestamp",
  "updated_at_utc": "timestamp",
  "completed_at_utc": "timestamp | null",
  "analyst_name": "string | null",
  "source_workbook": {},
  "questions": [],
  "warnings": []
}
```

Question and decision fields are defined by the active feature specifications.
The file preserves Arabic UTF-8, deterministic ordering, and exact source
identity. The source workbook is not modified.

## Discovery Invariants

- Nebius vectors are 4096-dimensional `float32`, finite, and approximately
  unit length using `rtol=1e-5`, `atol=1e-6`.
- PCA requests 50 randomized components with seed 42 and no whitening; the
  effective count is bounded by `distinct_count - 1` and source dimension.
- HDBSCAN uses min cluster size 3, `min_samples=None`, Euclidean/EOM,
  epsilon 0, and allows one cluster.
- Accepted membership probability is at least 0.5.
- A Gemini proposal requires at least three distinct accepted texts.
- Every canonical answer is considered by discovery; duplicates are one point
  with full row fan-out.
- No centroid similarity, merge suggestion, split, or member movement exists.

## Review Invariants

- Cluster membership is immutable and all members receive one cluster-level
  final disposition together.
- Noise/rare/unresolved canonical answers may only select an existing choice
  from the same question or remain unresolved.
- Completion requires a nonblank analyst name and exactly one valid decision
  for every cluster and unresolved canonical answer.
- New-category labels pass concise bilingual label checks and are unique after
  same-question normalization.
- Final new-category values are allocated only on completion, independently for
  each question, using the smallest unused integer greater than 100 from that
  question's existing choices and stable cluster-ID order. Values may repeat
  across questions.
- Completion updates decisions, timestamps, status, and allocations in one
  atomic replacement.
- Completed files are read-only.

## Failure and Recovery

Workbook-contract, Nebius, embedding-alignment, malformed review-file, and
review-write failures are fatal. Gemini cluster exhaustion is nonfatal and
records a safe warning plus a provider-error cluster. Temporary Google export
cleanup warnings do not mask the primary outcome. Atomic replacement always
uses a temporary file in the target directory; an interrupted save leaves the
previous authoritative file intact.

## Security and Privacy

Answers leave the local machine when sent to Nebius or Gemini. API keys come
only from environment variables or optional `.env`, never from TOML or JSON.
Gemini requests include no respondent keys or workbook locations. The local
SQLite cache may contain exact answer text and derived vectors.

## V2 Boundary

Workbook mutation, the `Work` interpretation, respondent-output destination,
final workbook save, and any approval/receipt/replay lifecycle are deferred to
V2. They must not be reintroduced as active V1 mechanics.
