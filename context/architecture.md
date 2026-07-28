# Architecture

## Architectural Goal

Build the smallest pipeline that can extract survey answers from an `.xlsx` workbook, categorize them using external embedding and generation APIs, require complete analyst review, and only then write exact row-level results to an output workbook.

The processing pipeline is exposed through the `other-cluster` console entry
point. A web application provides the intended analyst review surface. Until
that web application is implemented, the same review contract is written as a
versioned UTF-8 JSON file under `./review_packages`; the terminal receives its
path and a compact JSON summary, and a separate structured analyst-approval
input is used for finalization. The system does not require a job queue or
plugin architecture.

## System Context

```text
Operator
   |
   | other-cluster <arguments>
   v
Analysis process
   |---- resolves --------> local XLSX path or Google Sheets link
   |---- downloads -------> actual-named temporary XLSX under ./.temp/ (link input only)
   |---- reads -----------> XLSX workbook
   |---- requests --------> Nebius embeddings API
   |---- requests --------> Google Gemini API
   |---- keeps -----------> in-memory vectors + row map
   `---- produces --------> extracted CSV + structured review package
                                |
                                v
                         Analyst review web app
                         (terminal workflow first)
                                |
                                | complete structured approval
                                v
                         Gated workbook finalizer
```

## Processing Pipeline

The pipeline has seven ordered stages that correspond to the feature specifications:

1. **Resolve and ingest** — parse CLI/configuration, accept a local `.xlsx` path or native Google Sheets link, download link inputs into an isolated temporary directory under `./.temp/` using the filename returned by the XLSX response, validate the workbook contract, extract questions, existing choices, answers, and stable row references, then write those extracted question/answer records to `./extracted_data/<normalized_input_name>_extracted.csv`. The temporary download and directory are deleted in a `finally` block after the run or any failure, with retries for a transiently locked path.
2. **Embed** — send original-language answers to Nebius and persist the returned
   `4096`-dimensional vectors as `float32` without application-side
   renormalization, after validating that they are finite and already unit
   length, with an exact row map.
3. **Reuse existing choices** — ask Gemini for conservative structured verification against the allowed existing choices; retain uncertain answers for discovery.
4. **Discover categories** — reduce remaining vectors to the configured discovery dimension and run density-based clustering while preserving noise and membership probability.
5. **Label and prepare** — use Gemini to label proposed new groups, allocate workbook-wide unique values greater than `100`, and create a structured review package without modifying `Code` or respondent source data.
6. **Review and approve** — present every result to the analyst, require a complete structured approval, and authorize one finalization attempt without mutating the workbook.
7. **Finalize and output** — validate the approval again against the analysis run and workbook, apply approved code-list and respondent-output changes, and save a separate final workbook.

Existing-choice assignment happens before new-category discovery. Only answers
that Gemini does not safely match to an existing choice proceed to discovery.

## Responsibility Boundaries

Implementation should preserve these responsibility boundaries without introducing layers that have no concrete use:

### CLI and Configuration

- Defines `other-cluster` with `argparse`.
- Resolves local workbook paths or native Google Sheets links and explicit run options.
- Materializes Google Sheets links through the XLSX export endpoint under an isolated directory in `./.temp/`, preserves the response-provided workbook filename, and owns cleanup of the created file and directory for the complete run lifetime. Cleanup retries a briefly locked file or directory, warns instead of failing an otherwise successful run, and sweeps empty temporary directories abandoned by earlier runs.
- Loads non-secret settings from TOML and secrets from environment variables populated by `python-dotenv`.
- Starts the pipeline and reports a concise result or failure.

The invocation and configuration contract is defined by Feature 01: `--input`, `--output`, optional `--config`, and opt-in `--overwrite`, with CLI values taking precedence over TOML, environment variables, and built-in defaults. Input and output are always separate paths; an existing output is rejected unless overwrite is enabled. Exit code `0` means success, `2` means CLI/configuration failure, and `1` means workbook, provider, or finalization failure.

### Workbook I/O

- Is the only boundary allowed to interpret worksheet and column structure.
- Extracts typed in-memory records from workbook cells.
- Uses `Code.list_name` as the primary question/column key and joins it to one exact `Survey.name` row through ordered deterministic lookup candidates. A trailing `_other` targets the suffix-free parent. For `_exp`, the exact ID precedes its suffix-free fallback. For each base, exact spelling precedes a variant with a restored underscore before terminal digits. The first existing candidate wins and no candidate fails validation. It never fuzzy-matches identifiers, and the original Code key remains authoritative outside the metadata lookup.
- Resolves each Survey and Code English/Arabic label pair by using the
  nonblank side for both fields when exactly one side is blank; rejects a pair
  when both sides are blank.
- Retains the worksheet name, row number, source-answer column, and exact source cell for every answer.
- Ignores headers that are not required by the supported workbook contract on
  `Survey`, `Code`, and `Data`; required headers remain validated.
- Applies final mutations and saves the output workbook.
- Does not contain embedding, clustering, or prompt logic.

### Embedding

- Calls the Nebius Token Factory embeddings API through `httpx`.
- Sends extracted answer text after HTML markup has been removed; no translation
  is performed.
- Uses `POST https://api.tokenfactory.nebius.com/v1/embeddings` with
  `Authorization: Bearer <NEBIUS_API_KEY>`.
- Sends OpenAI-compatible requests containing model
  `Qwen/Qwen3-Embedding-8B`, at most `32` exact answer strings,
  `encoding_format: "float"`, and `dimensions: 4096`.
- Applies no instruction or prefix to an answer.
- Uses a `120`-second `httpx` timeout per request, performs no application-level
  retries, and stops on the first request or response failure.
- Validates response indices against the complete requested batch and validates
  that every returned vector has `4096` finite values.
- Converts vectors to `float32`, verifies that their L2 norms are approximately
  `1.0` using `rtol=1e-5` and `atol=1e-6`, does not renormalize them, and stores
  them in an in-memory NumPy array for the active process.
- Keeps an in-memory row map whose order exactly matches the vector rows.
- Reuses valid BLOB vectors from `./embedding_cache/cache.sqlite3`. The SQLite
  composite identity stores the exact answer text, endpoint, model, dimensions,
  instruction policy, finite-value requirement, norm tolerances, and
  application-renormalization policy directly in typed columns; different valid
  identities coexist as cache misses.
- Verifies schema version `1` and the complete expected `embeddings` table on
  every open, stores contiguous little-endian `float32` vectors as BLOBs, and
  revalidates their size, finite values, dimensions, and norm on every read.
  Every connection uses a 5-second busy timeout, WAL mode, and `FULL`
  synchronous writes. A complete, validated provider batch is written in one
  SQLite transaction before its vectors join the in-memory result.

### Categorization

- Holds the minimum logic needed for existing-choice verification, in-memory
  PCA, density clustering, membership probability, centroid-similarity merge
  suggestions, and acceptance decisions.
- Keeps existing-choice assignments distinct from discovered new-category assignments.
- Never forces an uncertain answer or density-clustering noise point into a category.
- Sends every existing choice belonging to the answer's question to Gemini for
  verification. It does not build a semantic shortlist or embed existing-choice
  labels.
- Requires existing-choice stored values to be unique within one question
  before making any Gemini request for that question. The same value may be
  reused by different questions.
- Assigns only when exactly one supplied choice captures the answer's complete
  asserted meaning. Ambiguity, uncertainty, negation, partial or related
  overlap, multi-meaning answers not fully captured by one choice, insufficient
  context, and multiple plausible choices produce `no_match`.
- Uses one discovery point per distinct exact question/answer text. Occurrence
  counts remain review evidence and retain complete row-level fan-out, but do
  not weight density or centroid calculations.
- Skips PCA and HDBSCAN when a question has fewer than the configured minimum
  distinct texts, default `3`; the setting cannot be lower than `3`, and all
  such answers remain unresolved/rare.
- Uses `sklearn.decomposition.PCA` with randomized SVD, `random_state=42`,
  `whiten=False`, and a requested component count from
  `discovery.pca_components`, default `50`. The effective component count is
  capped at the requested count, `distinct_answer_count - 1`, and the source
  dimension.
- Uses `sklearn.cluster.HDBSCAN` with `min_cluster_size=3`,
  `min_samples=None`, Euclidean distance, `cluster_selection_method="eom"`,
  `cluster_selection_epsilon=0.0`, and `allow_single_cluster=True`.
- Accepts a clustered point as a category member only when its HDBSCAN
  membership probability is at least the configured threshold, default `0.5`.
  Lower-probability points remain unresolved while retaining their raw cluster
  evidence.
- Treats a cluster as proposal-eligible only when its accepted members contain
  at least `3` distinct exact answer texts by default; the threshold is
  configurable but cannot be lower than `3`.
- Detects semantic overlap only between proposal-eligible clusters from the
  same question. It computes unweighted centroids from accepted members in the
  original `4096`-dimensional embedding space and emits a pairwise merge
  suggestion when their cosine similarity is at least the configured threshold,
  default `0.90`. Finite, non-zero centroids are required. Each unordered pair
  is evaluated once and suggestions have deterministic question/cluster order.
- Treats the initial HDBSCAN parameters, `0.5` membership threshold, and `0.90`
  merge threshold as provisional v1 baselines that require later calibration
  against manually reviewed fixtures.
- Requires analyst confirmation for every merge suggestion. An approved merge
  joins its component clusters under the connected-component merge rule, with
  one bilingual label, the smallest component value, and one combined member
  set.

### Gemini Verification and Labeling

- Calls the stable Gemini Interactions API through the official `google-genai`
  Python SDK using `gemini-3.5-flash` and API version `v1`. Every request must
  use schema-constrained structured responses following [Gemini structured
  output](https://ai.google.dev/gemini-api/docs/structured-output?hl=en).
- Loads `GEMINI_API_KEY` from the process environment or optional `.env` and
  passes it explicitly to the SDK client.
- Uses a `120`-second timeout per attempt and no more than five total attempts.
  Retries use exponential backoff with jitter for network failures, timeouts,
  HTTP `408`, `429`, and `5xx` responses; non-transient failures and invalid
  structured decisions are not transport-retried. Feature 05 may issue a new
  corrective labeling generation after a structurally valid provider call
  produces a label that fails its local quality contract; this is separate
  from transport retry.
- Sends no sampling parameters and uses schema-constrained structured
  responses for existing-choice verification and new-category labels; free-form
  text or post-hoc JSON parsing is not an acceptable substitute. See [Gemini
  structured output](https://ai.google.dev/gemini-api/docs/structured-output?hl=en).
- Existing-choice verification returns only `decision` (`assign` or
  `no_match`) and `selected_choice_value` (integer or null). It returns no
  confidence or reason. Application validation requires an assigned value to
  identify exactly one supplied choice and requires a rejected decision to
  contain a null value.
- Produces one English and one Arabic label for every accepted new category.
- Does not rewrite respondent text.

Feature 05 sends the bilingual question, same-question existing choices, and
up to `50` distinct accepted member answers with occurrence counts and
membership probabilities. Clusters of at most `50` send all members; larger
clusters send the deterministic `25` highest-probability and `25`
lowest-probability accepted members, with stable processing-answer-ID
tie-breaking. Random sampling is prohibited.

The structured labeling response contains exactly `decision`, `english_label`,
`arabic_label`, and `rejection_reason`. A `label` decision requires both labels
and no rejection reason. A `reject` decision requires null labels and one of
`mixed_meanings`, `insufficient_common_meaning`, or `unsafe_to_label`.
Mechanical label checks cover length, script, prohibited generic wording, and
exact normalized duplicates. The initial generation may be followed by two
corrective generations; exhaustion fails Feature 05 without a partial package.
A valid coherence rejection is preserved for review and is not retried.

Feature 05 labels and allocates only individual proposed clusters. Feature 06
treats approved pairwise merge suggestions as undirected edges and collapses
each approved connected component into one category. The merged category uses
the deduplicated union of component members, retains the smallest component
value, and defaults to that component's label pair; the analyst must confirm or
edit the final bilingual labels. Other component values remain unused.
Component categories receive a `merged` disposition. An approval is invalid if
it separately rejects a merged component or if an explicitly rejected edge has
both endpoints inside the same approved connected component.

### Analyst Review and Approval

- Presents every proposed existing-choice assignment, proposed new category, cluster member, noise point, rare answer, rejected cluster, and uncertain match.
- Requires the analyst to give every item an explicit disposition before finalization.
- Emits a structured approval tied to the exact analysis run and source workbook.
- Blocks all workbook mutation when approval is missing, partial, invalid, or belongs to different input data. Feature 07 owns the gated workbook mutation and output save.
- Uses a web application as the intended interface and a versioned UTF-8 JSON
  review-package file plus separate approval input as the interim interface.

The web framework, frontend approach, review-state storage, and local or hosted deployment model are intentionally deferred until Feature 06 implementation. Analyst identity/authentication and concurrency requirements remain separate review decisions.

The Feature 05 review package uses schema version `1`, a UUIDv4 analysis-run
ID, question-scoped canonical answers and row mappings, namespaced unique
review-item IDs, all existing assignments/categories/merges/unresolved items,
and non-fatal warnings. It is written as UTF-8 JSON under
`./review_packages/<normalized_source_stem>_<analysis_run_id>_review.json`.
Source identity is the input kind, stable locator, display name, byte length,
and lowercase SHA-256 of the exact analyzed XLSX bytes. Feature 07 must resolve
or re-export the same locator and match both byte length and SHA-256 before
mutation. A Google re-export mismatch requires a new analysis; no persistent
second source snapshot is created. The exact analyst-approval schema remains a
Feature 06 input.

## Core Data Records

These are conceptual records, not a requirement to create a class for each one. Plain dataclasses, named tuples, or dictionaries should be chosen according to the simplest implementation.

### Question

- question ID
- question text
- source answer column
- existing choices

### Existing Choice

- question ID or list name
- stored choice value
- English label from `Code.label:english`
- Arabic label from `Code.label:arabic`

During ingestion, a blank or whitespace-only side inherits the nonblank side.
Both sides being blank is a workbook-contract error.

### Answer

- stable internal answer ID
- question ID
- exact extracted text after HTML-tag cleanup
- worksheet name
- workbook row number
- source column

Blank and whitespace-only `Data` answers are skipped. HTML markup is removed
from question labels and answers immediately after extraction, and an answer
that becomes blank is skipped. Numeric answer cells are treated as empty and
skipped, while ingestion emits a source-cell warning; the application does not
use Excel number formats to convert them to displayed text. Hidden rows are
processed like visible rows. Formula-based, merged, and error-valued
respondent-answer cells in `Data` are outside the supported raw-data contract.

### Vector Row

- stable internal answer ID
- in-memory vector row index
- question ID
- workbook row reference

Exact duplicate answer text is deduplicated once per question for provider and computation stages. The vector row represents one canonical question/text processing item and contains the stable row-level answer IDs and workbook references to which its result must fan out. Every row-level `Answer` record remains authoritative for respondent and source-cell mapping.

### Assignment

- stable internal answer ID
- assignment kind: existing choice, discovered category, or unresolved
- assigned value when present
- decision evidence: Gemini decision, cluster ID, and/or membership probability

Decision evidence is included in the structured review package and shown to the
analyst. Feature 03 produces only the structured decision and selected stored
value, without a Gemini confidence or reason. Clustering evidence may include a
cluster ID and membership probability. The exact persisted schema is part of
Feature 06.

### New Category

- question ID
- discovered cluster ID
- allocated integer value greater than `100`
- English label
- Arabic label
- member answer IDs

### Review Package

- schema version `1`, analysis-run UUIDv4, and UTC creation timestamp
- exact source locator, display name, byte length, and SHA-256 identity
- question-scoped bilingual metadata and existing choices
- canonical exact-text answers with every respondent row mapping
- namespaced review items for proposed existing-choice assignments, proposed
  new categories, merge suggestions, and unresolved answers
- bilingual labels, globally unique values, members, and clustering evidence
- deterministic array ordering and cross-reference validation
- UTF-8 JSON serialization under `./review_packages`
- no authority to mutate the workbook

### Analyst Approval

- analysis run ID and matching source-workbook identity
- analyst identity
- explicit disposition for every review item
- final approved labels, category values, memberships, and assignments
- complete-review confirmation
- authority for one gated finalization attempt

## Vector and Discovery Invariants

- Embedding model is exactly `Qwen/Qwen3-Embedding-8B` unless the product contract is revised.
- Every stored embedding is `4096`-dimensional `float32`.
- Every stored embedding contains only finite values and has an L2 norm
  approximately equal to `1.0` using `rtol=1e-5` and `atol=1e-6`.
- Provider-returned values are not application-side renormalized.
- In-memory vector order and row-map order are identical.
- Answers are embedded in their original language.
- Discovery reduction uses in-memory PCA and reads its positive requested
  component count from `discovery.pca_components`, default `50`.
- PCA uses `svd_solver="randomized"`, `random_state=42`, and `whiten=False`.
- The effective component count is
  `min(requested_components, distinct_answer_count - 1, source_dimension)`.
- A question with fewer than `discovery.min_unique_answer_texts` distinct
  unassigned texts skips PCA and HDBSCAN; its answers remain unresolved/rare.
- Density discovery uses one point per distinct exact question/text answer and
  reports raw cluster/noise identity and membership probability for every
  considered point.
- Accepted membership requires a non-noise cluster and probability at least
  `discovery.membership_probability_threshold`, default `0.5`.
- Noise and low-probability members are not silently reassigned.
- Proposal-eligible same-question clusters receive deterministic pairwise merge
  suggestions when their unweighted original-embedding centroids have cosine
  similarity at least `discovery.merge_cosine_similarity_threshold`, default
  `0.90`.

## Workbook Write Invariants

- No `Code` mutation occurs during ingestion, embedding, assignment, discovery, labeling, or proposal generation.
- Feature 07 is the only feature that mutates or saves a coded workbook.
- Workbook mutation happens only after a complete structured analyst approval is validated against the same analysis run and source workbook.
- A new category is added to the code list no more than once per question.
- Every program-generated value greater than `100` is unique across the entire workbook.
- `101` is the conventional first allocation candidate, not a mandatory starting value.
- The allocator considers existing workbook values and current proposals before selecting an unused value.
- Any duplicate generated value detected before finalization stops the write and reports the value and all conflicting rows or proposals.
- Noise, rare answers, rejected clusters, and uncertain matches receive no automatic value; they remain unchanged unless explicitly assigned and approved by the analyst.
- Unrelated workbook cells and sheets remain unchanged.
- Source answer cells remain unchanged; extracted answer text has HTML markup
  removed before downstream processing.
- The output is always saved to a path different from the source workbook. In-place modification is invalid, and an existing output path requires explicit overwrite authorization.

[INPUT REQUIRED: Define whether workbook macros are supported; `openpyxl` handling differs for `.xlsx` and macro-enabled files.]

Noise, rare meanings, rejected clusters, and uncertain matches receive no automatic output value. Their source cells remain unchanged unless the Feature 07 output contract explicitly assigns and approves a category.

## Failure and Recovery

The minimal safe failure model is:

- Validate workbook structure before calling paid APIs.
- Delete a temporary Google Sheets download after success or failure, including a failed download that created a partial file. A removal blocked by another process is retried; a removal that still fails is reported as a warning on a successful run and attached as a note to an in-flight failure, and never changes the run's outcome.
- Stop on a malformed required API response, vector dimension mismatch, row-map mismatch, or workbook write conflict.
- Do not save a partially categorized workbook as the successful output.
- Do not mutate or save a coded workbook when analyst approval is absent, incomplete, stale, or invalid.
- Stop with a detailed error if a generated value greater than `100` is duplicated anywhere in the workbook or approval package.
- Return a non-zero process exit code on failure.
- Do not log API secrets or full authorization headers.

Nebius embedding calls are not retried. Any network error, timeout, non-success
HTTP response, malformed response, missing or duplicate response index, invalid
vector, or cache corruption stops the embedding stage. Gemini requests use the
bounded retry contract defined by Feature 03 and the Gemini provider boundary.

Valid SQLite rows committed by completed batches are reusable after an
interrupted run. A failed write rolls back the complete current batch while
earlier committed batches remain available. The database is created only when a
complete provider batch is ready to persist; an empty dataset, missing API key,
or provider failure before that point does not create it. Every execution
assembles a fresh in-memory vector array and ordered row map for downstream
stages; neither is persisted as a run artifact.

A valid dataset with no eligible processing answers makes no embedding request
and returns an in-memory `float32` array with shape `(0, 4096)` and an empty
ordered row map.

## Configuration Boundary

Only settings that are genuinely required by the agreed behavior should be configurable. Likely configuration groups are:

- input/output workbook paths;
- Nebius and Gemini credentials;
- API timeouts/batching required for reliable calls;
- PCA component count, `discovery.pca_components`, default `50`;
- minimum unique answer texts for a proposed cluster, default `3`;
- membership probability threshold, default `0.5`;
- original-embedding centroid merge cosine threshold, default `0.90`;
- fixed provisional HDBSCAN parameters defined by Feature 04.

The minimum unique-answer setting must be an integer at least `3`, and the PCA
component count must be a positive integer. Membership and merge thresholds
must be finite numeric values in `[0.0, 1.0]`. Items are not configuration
options merely because they might change someday. New settings require a
concrete product need.

## Security and Privacy

- Survey answers leave the local machine when sent to an external provider.
- Secrets are loaded from environment variables, optionally through `.env`, and are never stored in TOML.
- Exact extracted respondent answers are approved to be sent to Nebius without
  translation or redaction beyond Feature 01's HTML-tag cleanup.
- The exact Feature 01-cleaned answer, bilingual question text, and every
  bilingual existing-choice label and stored value are approved to be sent to
  Google Gemini for Feature 03 without additional translation or redaction.
- Exact answers and cached embeddings may remain on the local machine in the
  plaintext identity columns and BLOBs of `embedding_cache/cache.sqlite3` after
  a successful run. They are retained until manually deleted; SQLite storage is
  not encryption and there is no automatic expiry or cleanup policy. In-memory
  vectors and row maps disappear when the analysis process ends.
- `embedding_cache/` is excluded from source control.

## Verification Strategy

- Pure transformations and workbook mapping are covered with unit tests.
- Workbook behavior is covered with small generated `.xlsx` fixtures.
- Nebius and Gemini HTTP calls are mocked in automated tests; tests must not require paid network calls.
- Vector tests verify dimension, dtype, finite values, unit-norm validation
  without renormalization, SQLite schema compatibility, little-endian BLOB
  encoding, transaction rollback, cache reuse, and row alignment.
- Discovery tests use fixed vectors and deterministic settings to verify cluster, noise, and membership handling.
- Review-gate tests prove that missing, partial, stale, and invalid approvals produce no workbook mutation.
- An end-to-end test exercises all six stages with mocked provider responses, complete analyst approval, and exact workbook-cell assertions.

[INPUT REQUIRED: Provide or approve a sanitized representative workbook fixture and the expected coded output used for acceptance testing.]
