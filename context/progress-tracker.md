# Progress Tracker

## Current Phase

Features 01 through 04 are implemented: validated workbook ingestion flows into
cached, validated original-language Nebius embeddings, conservative,
question-scoped Gemini existing-choice verification, and in-memory dense
new-category discovery. Feature 05 labeling is next, followed by Feature 06
review and the final Feature 07 workbook-output stage.

## Completed Work

- Hardened the Feature 04 stage boundary by validating every embedding row-map
  entry against the corresponding canonical processing answer before PCA or
  clustering. Missing, reordered, or identity-mismatched maps now fail instead
  of silently attaching discovery evidence to the wrong answer IDs. Full suite:
  112 passing tests.
- Implemented Feature 04 end to end in the CLI. Discovery now receives only
  Feature 03-unassigned canonical answers, validates the exact embedding and
  duplicate fan-out alignment, and processes each question independently.
  The CLI reports proposed-cluster, unresolved-discovery, and merge-suggestion
  counts without mutating the workbook.
- Added in-memory randomized PCA (`random_state=42`, no whitening) and the
  specified scikit-learn HDBSCAN v1 baseline. The configured effective PCA
  component count is recorded per question; questions with fewer than the
  configured minimum of three distinct texts bypass PCA/HDBSCAN and stay
  represented as unresolved rare evidence.
- Added typed discovery records for PCA reductions, raw point evidence,
  proposal-eligible clusters, and same-question centroid merge suggestions.
  Raw labels and membership probabilities are retained; noise,
  low-probability members, and sub-threshold clusters are unresolved rather
  than reassigned. Proposal centroids use unweighted original embedding vectors
  and fail safely if invalid.
- Added discovery configuration with TOML/environment support: positive
  `pca_components` (default `50`), `min_unique_answer_texts` (minimum `3`),
  membership probability threshold (default `0.5`), and merge cosine threshold
  (default `0.90`). Added `scikit-learn` as the runtime dependency.
- Added fixed-vector regression coverage for small datasets, duplicate fan-out,
  accepted dense clusters, explicit noise, low-probability and rejected
  clusters, strict question separation, merge evidence, configuration
  validation, and CLI discovery failures. Focused Feature 04/config/CLI tests:
  27 passing.

- Finalized the Feature 04 discovery contract. Discovery uses one point per
  distinct exact question/answer text, skips questions with fewer than three
  distinct unassigned texts by default, and retains occurrence counts plus
  complete row-level fan-out without weighting density.
- Selected in-memory scikit-learn PCA only: randomized SVD with random state
  `42`, no whitening, requested components from
  `discovery.pca_components` with default `50`, and effective components capped
  at the distinct answer count minus one and the source dimension.
- Selected `sklearn.cluster.HDBSCAN` with the provisional v1 baseline
  `min_cluster_size=3`, `min_samples=None`, Euclidean distance, EOM cluster
  selection, zero selection epsilon, and single-cluster results allowed.
- Defined accepted membership as a non-noise HDBSCAN result with probability at
  least `0.5` by default. Lower-probability points remain unresolved while
  retaining their raw cluster label and probability; Feature 04 performs no
  automatic reconsideration pass.
- Defined deterministic semantic-overlap evidence: same-question,
  proposal-eligible clusters use unweighted centroids of accepted members in
  the original `4096`-dimensional embedding space and emit pairwise merge
  suggestions at cosine similarity `0.90` or greater by default. HDBSCAN,
  membership, and merge thresholds remain provisional until evaluated against
  manually reviewed calibration fixtures.
- Implemented Feature 03 end to end in the CLI. Each canonical
  question/exact-text answer is evaluated once by Gemini only against all
  existing choices belonging to that question, and accepted decisions fan out
  to every stable respondent-level answer ID. The CLI now reports the accepted
  existing-choice and unassigned-answer counts after this stage.
- Added the official `google-genai` dependency and a Gemini Interactions API
  boundary using `gemini-3.5-flash`, explicit stable API version `v1`, an
  explicit `GEMINI_API_KEY`, model-default sampling, a 120-second timeout, and
  schema-constrained JSON output. No `GOOGLE_API_KEY` fallback is accepted.
- Enforced the Feature 03 decision contract locally after structured output:
  exactly `decision` and `selected_choice_value`, strict assign/no-match
  cross-field rules, no unknown fields, and selected values restricted to the
  supplied question's unique stored choice values. Invalid provider decisions
  stop the stage rather than becoming discovery inputs.
- Added bounded retry handling for Gemini network, timeout, HTTP `408`, `429`,
  and `5xx` failures: five total attempts with exponential backoff and jitter.
  Authentication, malformed requests, malformed structured results, and
  semantically invalid decisions never retry.
- Added Feature 03 regression coverage for accepted duplicate fan-out,
  no-match/ambiguity preservation, invented and malformed choices, strict
  question boundaries, empty-choice pass-through, missing credentials,
  duplicate stored values, retries, optional `.env` credential loading, and
  CLI provider failure. Full suite: 98 passing tests.
- Implemented Feature 02 end to end in the CLI. After workbook validation and
  CSV extraction, each distinct question/exact-text processing answer is sent
  without translation or instruction to Nebius Token Factory using
  `Qwen/Qwen3-Embedding-8B`; provider failures return exit code `1`.
- Added strict Nebius response validation: batch indices must uniquely and
  exactly cover the requested inputs, every vector must contain `4096` finite
  numeric values, and converted `float32` vectors must already be unit length
  within `rtol=1e-5` and `atol=1e-6`. Provider vectors are never renormalized.
- Replaced the hashed JSON embedding cache with one SQLite database at
  `embedding_cache/cache.sqlite3`. Its version-1 `embeddings` table stores the
  complete typed identity (exact text, endpoint, model, dimensions, instruction
  policy, finite requirement, norm tolerances, and renormalization policy) as a
  composite primary key plus a little-endian `float32` BLOB. Legacy JSON entries
  were intentionally discarded without migration.
- Every cache open now verifies `PRAGMA user_version`, the complete table shape,
  and WAL availability; matched BLOBs must have exactly `16,384` bytes and pass
  fresh dimension, finite-value, and unit-norm validation. Connections use a
  5-second busy timeout, WAL mode, and `FULL` synchronous writes. Each complete
  validated provider batch is upserted and committed in one transaction before
  becoming available in memory; a write failure rolls back the whole batch.
- Added SQLite regression coverage for schema/version checks, WAL and connection
  settings, exact little-endian BLOB bytes, identity separation, matched-row
  corruption, batch persistence and rollback, missing-key/provider non-creation,
  and unchanged request, batching, row-map, and CLI behavior. Full suite: 82
  passing tests.
- Replaced persistent run artifacts with an in-memory `float32` vector array
  and aligned row map for the active process. Compatible exact-text cache
  entries continue to prevent repeated provider calls, but no
  `embedding_artifacts/` directory is created; regression coverage verifies
  successful runs create no run-artifact directory, memory-map file, or
  serialized row map.
- In-memory row mappings retain ordered processing IDs, exact answer text, all
  row-level answer IDs, respondent keys, and complete workbook cell locations.
  Malformed caches, non-finite vectors, and non-unit vectors stop processing.
- Added Feature 02 dependencies (`httpx` and NumPy) with `uv` and regression
  coverage for exact Arabic/English request preservation, out-of-order response
  mapping, 32-item batching, unchanged `float32` vectors, duplicate fan-out,
  exact-answer cache reuse across separate invocations, cache
  corruption, malformed vectors and indices, completed-batch recovery, empty
  datasets, and CLI provider failure.
- Locked the Feature 02 provider and persistence contract: Nebius Token Factory
  `POST /v1/embeddings` with `NEBIUS_API_KEY` Bearer authentication,
  `Qwen/Qwen3-Embedding-8B`, batches of at most `32`, `4096` float dimensions,
  a `120`-second request timeout, no retries, no model instruction, strict
  response-index validation, and fail-fast invalid-vector handling.
- Defined Feature 02 vector handling: provider-returned values are converted to
  `float32` and retained unchanged after finite, dimension, and unit-norm
  validation with `rtol=1e-5` and `atol=1e-6`; the application does not
  renormalize them.
- Defined embedding lifetime as in-memory vectors and row mappings for one
  process plus a local SQLite exact-answer cache retained until manually deleted
  and excluded from source control. The database holds plaintext answer identity
  fields and derived embedding BLOBs, so it is sensitive local data rather than
  encrypted storage.
- Approved sending exact Feature 01-cleaned respondent answers to Nebius and
  retaining exact answers and embeddings in the local cache until manual
  deletion.
- Defined Feature 03 candidate scope: Gemini receives every existing choice
  belonging to the question; there is no semantic shortlist and existing-choice
  labels are not embedded.
- Defined the Feature 03 Gemini transport and response shape: the official
  `google-genai` SDK calls stable API version `v1` with `gemini-3.5-flash` and
  an explicitly supplied `GEMINI_API_KEY`; no sampling parameters are sent.
  Gemini requests must use schema-constrained structured responses as specified
  in [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output?hl=en),
  rather than free-form JSON followed by post-hoc parsing.
  The structured decision contains only `decision` (`assign` or `no_match`) and
  `selected_choice_value` (integer or null), with no confidence or reason.
- Defined bounded Gemini request handling as a `120`-second timeout per attempt
  and at most five total attempts with exponential backoff and jitter only for
  network failures, timeouts, HTTP `408`, `429`, and `5xx` responses.
- Locked the conservative Feature 03 meaning rule: assignment requires exactly
  one supplied choice to capture the answer's complete asserted meaning.
  Ambiguity, uncertainty, negation, partial or related overlap, multi-meaning
  answers not fully captured by one choice, insufficient context, and multiple
  plausible choices produce `no_match`.
- Approved sending the exact Feature 01-cleaned answer, bilingual question
  text, and every bilingual existing-choice label and stored value to Google
  Gemini without additional translation or redaction.
- Defined duplicate existing-choice values within one question as a workbook
  error detected before its Gemini requests; the same value may be reused by
  different questions.
- Defined the default cluster proposal gate as `3` distinct exact answer texts, with the threshold configurable as `discovery.min_unique_answer_texts`.
- Defined semantic-overlap handling: the system proposes pairwise merges and
  the analyst must confirm or reject every edge. Approved edges form connected
  groups; each group has one bilingual label, the smallest component value,
  and the deduplicated union of component members.
- Defined the simple CLI/configuration contract: `--input`, `--output`, optional `--config`, and opt-in `--overwrite`, with CLI > TOML > environment > built-in precedence.
- Defined separate-output behavior: in-place source modification is invalid, and an existing output requires explicit overwrite authorization.
- Defined workbook answer handling: numeric answer cells are treated as empty, skipped, and reported as source-cell warnings; exact duplicate answer text is processed once per question and fanned out to every row-level answer mapping.
- Removed all `Work`-tab logic from ingestion: `Work` is not required, validated, read, or used for row/cell mapping, and the domain records expose only exact `Data` source locations. Full suite remains green at 50 passing tests.
- Deferred the web framework, browser UI approach, review-state storage, and local/hosted deployment choice until Feature 06 implementation.
- Implemented the `other-cluster` CLI with `--input`, `--output`, `--config`, and opt-in `--overwrite` handling, including the documented exit-code contract.
- Implemented TOML, environment, and optional `.env` resolution with CLI > TOML > environment > built-in precedence and unknown-key validation.
- Implemented read-only `.xlsx` workbook validation and extraction for `Survey`, `Code`, and `Data`, using `Code.list_name` as the primary question key and matching normalized `Survey.name` metadata, including exact source row/cell locations and exclusion of Code value `-96`.
- Implemented bilingual-label fallback during ingestion: a blank or whitespace-only `label:english` or `label:arabic` value inherits the other label for both `Survey` question metadata and `Code` choices; both blank labels produce a row-aware workbook-contract error.
- Implemented respondent-level answer records plus per-question exact-text deduplication for later provider stages; hidden rows are included, numeric cells are skipped with warnings, and formula, merged, and error answer cells fail validation.
- Added regression coverage confirming required workbook headers are resolved by name regardless of column order and that no coding-destination sheet is needed.
- Added row-aware workbook diagnostics: applicable validation errors identify the worksheet row or exact cell, while path and missing-sheet errors omit a row when none exists.
- Made row diagnostics explicit in rendered messages, for example `Code!D8 (row 8)`, so Excel coordinates are not the only indication of the failing row.
- Added openpyxl/python-dotenv runtime dependencies and focused tests covering the Feature 01 configuration, ingestion, deduplication, and CLI contracts.
- Applied a Brooks-Lint PR review: split the `_extract_dataset`/`_extract_answers` monoliths into named single-responsibility helpers (`_require_sheets`, `_raise_if_issues`, `_build_questions`, `_scan_row_answers`, `_claim_data_key`, `_build_answer_record`, `_cell_location`) with behavior unchanged, and hardened the workbook-validation gate with parametrized rejection tests (missing sheet, missing/duplicate/non-text headers, blank required label, missing Survey metadata for a Code list, duplicate question ID, non-integer choice value, merged and error answer cells) that each assert the source workbook is left byte-for-byte unmodified. Suite at 25 passing tests.
- Added regression tests for one-sided Survey and Code label fallback and for rejecting both labels blank, with the source workbook remaining byte-for-byte unchanged on validation failure. Suite at 30 passing tests.
- Normalized a trailing `_other` suffix from `Code.list_name` only when matching question metadata in `Survey.name`; original Code IDs remain unchanged for `Data` extraction. Added regression coverage for the normalized lookup. Suite now has 31 passing tests.
- Changed workbook header validation to ignore unexpected headers on every supported sheet while continuing to reject missing or duplicate required headers. Added regression coverage for extra headers including `Code.list_name_other`.
- Added native Google Sheets link input. Supported links are downloaded through the XLSX export endpoint into an isolated uniquely named directory under `./.temp/`, using the response-provided workbook filename, then removed by `finally` cleanup after successful ingestion or any expected failure. Added configuration, downloader, and CLI cleanup regression coverage.
- Hardened the Google Sheets temporary-file boundary: blocked or unwritable `.temp` paths now produce the clean download-failure exit code, and cleanup errors are attached to rather than masking the primary download or ingestion failure. Added blocked-path and cleanup-preservation regression coverage.
- Expanded Survey metadata lookup with ordered deterministic identifier rules: a trailing `_other` targets its suffix-free parent; a trailing `_exp` prefers its exact ID and falls back to the suffix-free ID; and each base prefers exact spelling before restoring a missing underscore before terminal digits. The first existing candidate wins; unresolved names remain errors and are never fuzzy-matched. Added regression coverage for the observed land-degradation, improved-seeds, severe-shocks, and farm-style exact `_exp` behavior, candidate precedence, and the valid `zero_livestock_exp` rejection. Full suite: 41 passing tests.
- Changed numeric `Data` answer cells to empty-cell behavior with source-cell warnings on the CLI; added ingestion and CLI regression coverage. Numeric cells are excluded from respondent and processing answer records while other workbook-contract failures remain fatal.
- Centralized workbook issues and warnings in the mutable `WorkbookDiagnostics` domain model so extraction helpers share one diagnostics object instead of receiving separate collections.
- Added CSV extraction output under `./extracted_data`: one row per respondent answer with bilingual question text, original-language answer text, respondent `KEY`, row, source column, and exact source cell. Filenames are normalized to lowercase with spaces replaced by underscores and suffixed with `_extracted.csv`.
- Removed HTML tags from Survey question labels and Data answers immediately after extraction, skipping answers that become blank; added regression coverage and preserved the original workbook cells and source locations.

## Open Questions

The remaining open questions are recorded in the applicable architecture and feature-specification files.

## Architecture Decisions

- **Feature 05 labeling contract:** Gemini receives the bilingual question,
  same-question existing choices, and at most 50 deterministically selected
  distinct accepted members. Large clusters use the 25 highest- and 25
  lowest-membership-probability members rather than random sampling. The
  structured result either supplies one validated bilingual label pair or
  rejects the cluster with a fixed coherence reason. Labels are short, plain,
  script-constrained, non-generic, and exact-normalized-duplicate-free. The
  initial generation may receive two corrective regeneration attempts before
  Feature 05 fails without a partial package.
- **Feature 05 provisional value ordering:** Individual proposed clusters are
  ordered by question ID and cluster ID, then receive the smallest available
  workbook-wide integer greater than 100. Feature 05 creates no speculative
  merge alternatives. Feature 06 collapses approved connected components,
  keeps the smallest component value and its labels as the default, requires
  analyst confirmation or valid label edits, and leaves the other component
  values unused.
- **Feature 05 review-package contract:** A successful analysis writes one
  schema-version-1 UTF-8 JSON file under `./review_packages`, identified by a
  UUIDv4 analysis-run ID. The package groups canonical answers and all
  respondent row mappings by question, uses namespaced unique review-item IDs,
  includes every assignment/category/merge/unresolved item, and uses
  deterministic ordering. Source identity contains the stable locator,
  display name, exact XLSX byte length, and SHA-256. Finalization must resolve
  or re-export the same source and match both byte length and hash; a Google
  export mismatch requires a new analysis. The CLI prints only the package path
  and compact counts, and a failed build leaves no partial package.
- **In-memory embedding results:** Every execution creates a fresh in-memory
  vector array and row map for downstream stages. The embedding stage does not
  calculate a dataset fingerprint or persist a vector run artifact; only
  compatible exact-answer cache entries are reusable across executions.
  Feature 05 separately fingerprints the exact source XLSX solely to bind its
  review package and later approval/finalization to that workbook.
- **Empty embedding datasets:** A valid workbook with no eligible text answers
  produces an in-memory zero-row `float32` array with shape `(0, 4096)` and an
  empty row-map entry list without requiring a provider key or request.
- **Nebius embedding contract:** Feature 02 calls the OpenAI-compatible Nebius
  Token Factory embeddings endpoint with `NEBIUS_API_KEY`, exact unprefixed
  answers, fixed model and dimensions, batches of at most `32`, a `120`-second
  timeout, and no retries.
- **Provider vector preservation:** Nebius vectors are converted to `float32`
  and stored without application-side renormalization only after strict shape,
  finite-value, response-index, and unit-norm validation.
- **SQLite embedding persistence and privacy:** Compatible vectors are cached
  in `embedding_cache/cache.sqlite3` using the complete typed exact-text/provider
  identity and little-endian `float32` BLOBs. Schema/version/vector corruption
  fails fast; completed provider batches commit atomically and earlier commits
  survive later failures. Exact Feature 01-cleaned answers are approved for
  Nebius transmission and remain plaintext sensitive local cache data until
  manually deleted.
- **Existing-choice evaluation:** Gemini evaluates every existing choice for
  the relevant question. No existing-choice shortlist or label-embedding stage
  is used.
- **Feature 03 Gemini boundary:** Existing-choice verification uses the official
  `google-genai` SDK, stable API version `v1`, `gemini-3.5-flash`, and the
  explicitly loaded `GEMINI_API_KEY`. Requests use model-default sampling and
  schema-constrained structured responses per [Gemini structured
  output](https://ai.google.dev/gemini-api/docs/structured-output?hl=en), a
  `120`-second timeout per attempt, and no more than five attempts with
  exponential backoff and jitter for transient network, timeout, `408`, `429`,
  and `5xx` failures.
- **Existing-choice decision schema:** Gemini returns only `decision`
  (`assign` or `no_match`) and `selected_choice_value` (integer or null).
  Cross-field validation and exact membership in the supplied choices are
  enforced locally; no confidence or reason is requested or accepted.
- **Conservative existing-choice meaning:** Assignment is allowed only when
  exactly one supplied choice captures the answer's complete asserted meaning.
  Ambiguity, uncertainty, negation, partial or related overlap, multiple
  meanings not fully represented by one choice, insufficient context, and
  multiple plausible choices remain unmatched for discovery.
- **Feature 03 Gemini privacy:** The exact Feature 01-cleaned answer, bilingual
  question text, and all bilingual existing-choice labels and stored values are
  approved for Google Gemini transmission without additional translation or
  redaction.
- **Existing-choice value identity:** Stored choice values must be unique
  within one question and are validated before that question's Gemini calls.
  Reuse across different questions remains valid.
- **Cluster proposal evidence:** A cluster is proposal-eligible when it contains at least three distinct exact original answer texts by default. The setting is configurable.
- **Semantic overlap:** The system detects overlap and proposes pairwise
  merges; only explicit analyst confirmation authorizes an edge. Approved
  edges form connected components. Each becomes one category with the union of
  component members, the smallest component value, and an analyst-confirmed or
  edited bilingual label pair. A rejected edge inside an approved component or
  a separately rejected component category makes the approval inconsistent.
- **Feature 04 reduction:** Discovery uses only in-memory randomized PCA with
  random state `42`, no whitening, a positive requested component count from
  `discovery.pca_components` with default `50`, and
  `min(requested_components, distinct_answer_count - 1, source_dimension)`
  effective components. Questions below the configured minimum distinct-text
  count skip reduction and clustering and remain unresolved/rare.
- **Feature 04 clustering:** Discovery uses one distinct question/text point
  with occurrence metadata and `sklearn.cluster.HDBSCAN` configured with
  `min_cluster_size=3`, `min_samples=None`, Euclidean distance, EOM selection,
  zero selection epsilon, and single-cluster results allowed. Accepted
  membership requires probability at least `0.5` by default.
- **Semantic-overlap evidence:** For proposal-eligible clusters from the same
  question, Feature 04 compares unweighted accepted-member centroids in the
  original `4096`-dimensional embedding space and proposes a merge at cosine
  similarity `0.90` or greater by default. The analyst must confirm every
  suggestion.
- **CLI and output safety:** Input and output paths are resolved from CLI, TOML, environment, and defaults in that order. The source and output must be different paths, and overwrite is opt-in.
- **Answer validation and deduplication:** Numeric `Data` answer cells are treated as empty and skipped, with a source-cell warning printed by the CLI. Exact duplicate text is deduplicated within each question for provider/computation work, with decisions and results fanned out through stable row-level answer and source-cell mappings.
- **Web application:** Framework, browser UI, review-state storage, and deployment model remain intentionally deferred until Feature 06 implementation.
- **Feature-stage separation:** Feature 05 ends with bilingual labeling, workbook-wide value allocation, and review-package preparation. Feature 06 owns analyst review and complete approval. Feature 07 is the final and only workbook-output/finalization stage; it validates the approval, writes approved `Code` and respondent-output changes, and saves the separate output workbook.
- **Question extraction key:** `Code.list_name` is the primary question key; normalized matching `Survey.name` supplies the bilingual metadata, and unmatched Survey rows are ignored.
- **Survey metadata lookup:** For the `Survey.name` lookup only, a trailing `_other` targets its suffix-free parent, a trailing `_exp` prefers exact then suffix-free, and each base prefers exact spelling before restoring an underscore before terminal digits. The first existing candidate wins; no match fails and identifiers are never fuzzy-matched. The original Code list name remains authoritative for the `Data` answer column.
- **Bilingual label fallback:** For each Survey question or Code choice, a blank or whitespace-only English or Arabic label is replaced with the other nonblank label; both blank labels are invalid and stop ingestion.
- **Header order:** Required headers are position-independent on `Survey`, `Code`, and `Data`; no coding-destination tab or triplet order is part of the contract.
- **Fixed-header casing:** Fixed schema headers are matched case-insensitively to support SurveyCTO exports such as `Label:Arabic`; dynamic question IDs remain case-sensitive.
- **Unexpected headers:** Headers outside the required contract are ignored on `Survey`, `Code`, and `Data`; other sheets are outside extraction and do not affect validation.
- **Feature 01 workbook boundary:** Ingestion opens workbooks with formulas visible (`data_only=False`), validates the required three-sheet contract without saving, extracts Data rows by their stable `KEY`, and exposes immutable row-level source-cell references for later review/output work.
- **Google Sheets input identity:** Native `docs.google.com/spreadsheets/d/...` links are converted to the XLSX export endpoint; the response-provided workbook filename is preserved inside a uniquely named temporary directory under the current working directory's `.temp` directory. That directory and file are deleted, in a `finally` block, after success or failure; local input paths are untouched.
- **Temporary cleanup is never fatal:** Removal of the temporary download and its directory is retried ten times at `0.1`-second intervals to absorb a transient Windows handle hold (antivirus or indexer scanning the freshly written workbook). A removal that still fails is printed as a `warning:` on an otherwise successful run rather than raising `InputDownloadError`, so a janitorial failure cannot discard a completed ingestion and embedding run. Empty `google-sheet-*` directories older than one hour are swept from `.temp/` at the start of the next link run; the age guard keeps a concurrent run's freshly created directory safe.
- **Extraction CSV output:** The validated in-memory extraction is exported once per run to `./extracted_data/<normalized_input_name>_extracted.csv`; the source workbook remains unmodified.
- **Extracted text cleanup:** The ingestion boundary removes HTML tags from question labels and answers with a regular expression while retaining text content; source workbook cells remain unchanged.
