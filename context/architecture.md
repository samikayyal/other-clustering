# Architecture

## Architectural Goal

Build the smallest pipeline that can extract survey answers from an `.xlsx` workbook, categorize them using external embedding and generation APIs, require complete analyst review, and only then write exact row-level results to an output workbook.

The processing pipeline is exposed through the `other-cluster` console entry point. A web application provides the intended analyst review surface. Until that web application is implemented, the same review contract is exposed as structured terminal output plus a separate structured analyst-approval input. The system does not require a job queue or plugin architecture.

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
   |---- reads/writes ----> local vector memmap + row map
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

The pipeline has six ordered stages that correspond to the feature specifications:

1. **Resolve and ingest** — parse CLI/configuration, accept a local `.xlsx` path or native Google Sheets link, download link inputs into an isolated temporary directory under `./.temp/` using the filename returned by the XLSX response, validate the workbook contract, extract questions, existing choices, answers, and stable row references, then write those extracted question/answer records to `./extracted_data/<normalized_input_name>_extracted.csv`. The temporary download and directory are deleted in a `finally` block after the run or any failure.
2. **Embed** — send original-language answers to Nebius and persist `4096`-dimensional normalized vectors with an exact row map.
3. **Reuse existing choices** — ask Gemini for conservative structured verification against the allowed existing choices; retain uncertain answers for discovery.
4. **Discover categories** — reduce remaining vectors to the configured discovery dimension and run density-based clustering while preserving noise and membership probability.
5. **Label and prepare** — use Gemini to label proposed new groups, allocate workbook-wide unique values greater than `100`, and create a structured review package without modifying `Code` or respondent source data.
6. **Review and finalize** — present every result to the analyst, require a complete structured approval, validate that approval against the analysis run and workbook, then apply approved code-list and later output changes in one gated finalization step.

[INPUT REQUIRED: Confirm that existing-choice assignment happens before new-category discovery. The supplied technical step list does not state where existing-choice verification enters the pipeline.]

## Responsibility Boundaries

Implementation should preserve these responsibility boundaries without introducing layers that have no concrete use:

### CLI and Configuration

- Defines `other-cluster` with `argparse`.
- Resolves local workbook paths or native Google Sheets links and explicit run options.
- Materializes Google Sheets links through the XLSX export endpoint under an isolated directory in `./.temp/`, preserves the response-provided workbook filename, and owns cleanup of the created file and directory for the complete run lifetime.
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
- Validates that every returned vector has `4096` finite values.
- converts vectors to `float32`, L2-normalizes them, and stores them in a NumPy memory map.
- Persists a row map whose order exactly matches the memory-map rows.

[INPUT REQUIRED: Define the Nebius endpoint, authentication environment variable, request/response schema, supported batch size, timeout/retry behavior, and local artifact paths/formats.]

### Categorization

- Holds the minimum logic needed for existing-choice verification, PCA/IncrementalPCA, density clustering, membership probability, and acceptance decisions.
- Keeps existing-choice assignments distinct from discovered new-category assignments.
- Never forces an uncertain answer or density-clustering noise point into a category.
- Treats a cluster as proposal-eligible only when it contains at least `3` distinct exact answer texts by default; the threshold is configurable.
- Detects semantic overlap between separate clusters and emits merge suggestions for analyst confirmation. An approved merge has one bilingual label, one workbook-wide value, and one combined member set.

[INPUT REQUIRED: Decide whether Gemini receives every existing choice for the question or only a candidate shortlist. If a shortlist is required, define its selection method and threshold.]

[INPUT REQUIRED: Select the concrete HDBSCAN implementation and define its required hyperparameters.]

[INPUT REQUIRED: Define thresholds for accepting existing-choice assignments, clusters, and individual cluster memberships.]

### Labeling

- Calls the direct Google Gemini API through `httpx` using `gemini-3.5-flash`.
- Uses structured responses for existing-choice verification and new-category labels.
- Produces one English and one Arabic label for every accepted new category.
- Does not rewrite respondent text.

[INPUT REQUIRED: Define the Gemini endpoint/API version, authentication environment variable, exact structured response schemas, sampling settings, timeout/retry behavior, and prompt rules.]

### Analyst Review and Approval

- Presents every proposed existing-choice assignment, proposed new category, cluster member, noise point, rare answer, rejected cluster, and uncertain match.
- Requires the analyst to give every item an explicit disposition before finalization.
- Emits a structured approval tied to the exact analysis run and source workbook.
- Blocks all workbook mutation when approval is missing, partial, invalid, or belongs to different input data.
- Uses a web application as the intended interface and structured terminal output plus separate approval input as the interim interface.

The web framework, frontend approach, review-state storage, and local or hosted deployment model are intentionally deferred until Feature 06 implementation. Analyst identity/authentication and concurrency requirements remain separate review decisions.

[INPUT REQUIRED: Define the exact structured review-package and analyst-approval schemas.]

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
- memory-map row index
- question ID
- workbook row reference

Exact duplicate answer text is deduplicated once per question for provider and computation stages. The vector row represents one canonical question/text processing item and contains the stable row-level answer IDs and workbook references to which its result must fan out. Every row-level `Answer` record remains authoritative for respondent and source-cell mapping.

### Assignment

- stable internal answer ID
- assignment kind: existing choice, discovered category, or unresolved
- assigned value when present
- confidence evidence: Gemini decision, cluster ID, and/or membership probability

Confidence evidence is included in the structured review package and shown to the analyst. Its exact persisted schema is part of Feature 06.

### New Category

- question ID
- discovered cluster ID
- allocated integer value greater than `100`
- English label
- Arabic label
- member answer IDs

### Review Package

- analysis run ID and source-workbook identity
- all questions and respondent answer references
- proposed existing-choice assignments
- proposed new categories, bilingual labels, globally unique values, members, and clustering evidence
- noise, rare answers, rejected clusters, and uncertain matches
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
- Every non-zero embedding is L2-normalized before cosine calculations.
- Memory-map order and row-map order are identical.
- Answers are embedded in their original language.
- Discovery reduction defaults to `50` dimensions.
- PCA should be deterministic when the dataset fits the selected deterministic implementation.
- IncrementalPCA should be used only when bounded-memory processing is required.
- The effective component count cannot exceed mathematical limits imposed by the sample and feature counts.
- Density discovery reports cluster/noise identity and membership probability for every considered answer.
- Noise is not silently reassigned.

[INPUT REQUIRED: Define the dataset-size or memory rule that selects PCA versus IncrementalPCA, including batch size.]

[INPUT REQUIRED: Define expected behavior when too few unassigned answers exist for the requested discovery dimension or for density clustering.]

## Workbook Write Invariants

- No `Code` mutation occurs during ingestion, embedding, assignment, discovery, labeling, or proposal generation.
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

Noise, rare meanings, rejected clusters, and uncertain matches receive no automatic output value. Their source cells remain unchanged unless a later output contract explicitly assigns and approves a category.

## Failure and Recovery

The minimal safe failure model is:

- Validate workbook structure before calling paid APIs.
- Delete a temporary Google Sheets download after success or failure, including a failed download that created a partial file.
- Stop on a malformed required API response, vector dimension mismatch, row-map mismatch, or workbook write conflict.
- Do not save a partially categorized workbook as the successful output.
- Do not mutate or save a coded workbook when analyst approval is absent, incomplete, stale, or invalid.
- Stop with a detailed error if a generated value greater than `100` is duplicated anywhere in the workbook or approval package.
- Return a non-zero process exit code on failure.
- Do not log API secrets or full authorization headers.

[INPUT REQUIRED: Define whether failed API calls are retried, how many times, and which response classes are retryable.]

[INPUT REQUIRED: Define whether vector artifacts are reusable after interruption and how compatibility with the workbook/model is checked.]

## Configuration Boundary

Only settings that are genuinely required by the agreed behavior should be configurable. Likely configuration groups are:

- input/output workbook paths;
- Nebius and Gemini credentials;
- API timeouts/batching required for reliable calls;
- discovery dimension, default `50`;
- minimum unique answer texts for a proposed cluster, default `3`;
- selected clustering parameters and acceptance thresholds.

Items are not configuration options merely because they might change someday. New settings require a concrete product need.

## Security and Privacy

- Survey answers leave the local machine when sent to Nebius and Gemini.
- Secrets are loaded from environment variables, optionally through `.env`, and are never stored in TOML.
- Local memmap and row-map artifacts contain derived survey data and must be treated as sensitive.

[INPUT REQUIRED: Confirm that sending respondent answers to both external providers is approved and define any required redaction, retention, or deletion policy.]

[INPUT REQUIRED: Define whether local vector and row-map artifacts are retained after success or deleted.]

## Verification Strategy

- Pure transformations and workbook mapping are covered with unit tests.
- Workbook behavior is covered with small generated `.xlsx` fixtures.
- Nebius and Gemini HTTP calls are mocked in automated tests; tests must not require paid network calls.
- Vector tests verify dimension, dtype, normalization, persistence, and row alignment.
- Discovery tests use fixed vectors and deterministic settings to verify cluster, noise, and membership handling.
- Review-gate tests prove that missing, partial, stale, and invalid approvals produce no workbook mutation.
- An end-to-end test exercises all six stages with mocked provider responses, complete analyst approval, and exact workbook-cell assertions.

[INPUT REQUIRED: Provide or approve a sanitized representative workbook fixture and the expected coded output used for acceptance testing.]
