# Architecture

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Runtime | Python 3.13 | Supported execution baseline and type-safe application runtime. |
| Packaging and execution | `uv`, `pyproject.toml`, `uv.lock` | Dependency management, environment provisioning, reproducible commands, and the `other-cluster` console entry point. |
| CLI | Standard-library `argparse` | Hierarchical commands and meaningful exit codes without adding a CLI framework dependency. |
| Domain contracts | Pydantic models plus typed protocols | Validate and exchange application-level records without exposing vendor payload shapes. |
| Small immutable settings/value objects | Frozen standard-library dataclasses | Secret-safe environment settings and compact internal values that do not need Pydantic serialization. |
| Workbook I/O | `openpyxl` | Read, validate, template, and write XLSX files while preserving required string values and rejecting formulas in required fields. |
| Configuration | `tomllib` plus `python-dotenv` | Parse versioned TOML and load environment-only credentials. |
| HTTP transport | `httpx` | Direct Nebius and Google API requests with explicit timeouts, connection reuse, and controlled retry/rate-limit handling. |
| Language diagnostics | Lingua language detector | Low-accuracy, restricted-set language metadata after deduplication; never a translation or routing authority. |
| Vector representation | NumPy | 2048-dimensional `float32` vectors, L2 normalization, memmap storage, row maps, and cosine calculations. |
| Dimension reduction | Scikit-learn PCA/IncrementalPCA | Deterministic or bounded-memory reduction to the configured discovery dimension, default 50. |
| Density discovery | HDBSCAN-style clustering | Discover dense new categories, preserve noise, expose membership probability, and retain rare meanings. |
| Generation | Direct Google Gemini API | Structured verification, bilingual category labeling, and composite review through `gemini-3.5-flash`. |
| Embeddings | Nebius Token Factory embeddings API | Original-language embeddings from `Qwen/Qwen3-Embedding-8B`; no generation. |
| Test runner | `pytest` | Unit, fixture-integration, mocked provider-contract, and opt-in live smoke tests. |
| Local artifacts | XLSX, JSON, NumPy memmap, checkpoints, structured logs, plaintext cache | Auditability, resumability, replay metadata, and analyst review. |

The exact compatible dependency versions are implementation details and must be pinned by `uv.lock`. The architecture does not introduce `pandas` or provider SDKs into the core boundary; workbook handling and direct HTTP provider adapters remain explicit.

## System Boundaries

The target source layout is:

```text
src/other_cluster/
├── cli/
├── config/
├── domain/
├── input/
├── preprocessing/
├── providers/
├── embeddings/
├── clustering/
├── pipeline/
└── artifacts/

tests/
├── unit/
├── integration/
└── live/
```

| Folder | Owns | Must not own |
| --- | --- | --- |
| `cli/` | `argparse` command parsing, command-to-use-case wiring, exit-code mapping, and human-readable command output. | Clustering algorithms, workbook cell rules, provider payload construction, or secret values. |
| `config/` | TOML schema, environment loading, explicit model profiles, redaction/non-semantic rules, canonical configuration serialization, and secret-safe settings. | Workbook row interpretation or API calls. |
| `domain/` | Pydantic records, enums/statuses, protocols, error types, and cross-stage contracts such as `Assignment`, `RunManifest`, and `Checkpoint`. | Vendor JSON, `openpyxl` objects, filesystem details, or clustering implementation. |
| `input/` | XLSX template generation, string-preserving workbook reading, schema validation, formula detection, and input models. | Semantic classification, embeddings, or mutation of the source workbook. |
| `preprocessing/` | Normalization, deterministic symbol cleanup, non-semantic classification, language assessment, redaction, deduplication, variant IDs, and row-to-variant mapping. | Provider calls, clustering, or final category decisions. |
| `providers/` | The `SemanticProvider` interface, Nebius embedding adapter, direct Google generation adapter, typed request/response translation, retry/rate-limit policy, health checks, and provider-contract tests. | Business decisions based on similarity or cluster membership. |
| `embeddings/` | Fixed instruction/anchor serialization, embedding batches, vector validation, memmap creation, row maps, normalization, cosine similarity, and existing-choice candidate gates. | Vendor-specific response parsing or final assignment orchestration. |
| `clustering/` | Bounded frequency expansion, PCA, HDBSCAN discovery, noise/rare handling, stable category ordering, membership thresholds, and category-cap diagnostics. | Workbook writing, provider credentials, or official codebook mutation. |
| `pipeline/` | Stage orchestration, request planning, preflight, existing/new/composite decision flow, primary/secondary assignment logic, stage checkpoints, and run lifecycle. | Direct workbook cell manipulation or raw HTTP payload formatting. |
| `artifacts/` | Result workbook writing, manifest serialization, cache layout, checkpoint persistence, structured logs, hashes, and artifact integrity checks. | Deciding whether an answer is semantically correct. |
| `tests/` | Fast deterministic unit tests, non-sensitive fixture integration tests, mocked provider contracts, and opt-in credential-gated live smoke tests. | Production runtime logic or live survey data. |

Dependencies should point inward toward `domain`. The CLI depends on pipeline use cases; pipeline depends on domain contracts and specialized services; input, preprocessing, providers, embeddings, clustering, and artifacts do not import the CLI. No layer may leak `openpyxl` rows, vendor response dictionaries, or raw HTTP exceptions into domain models.

## Storage Model

The application is file-oriented and run-scoped. It does not use a database in v1.

| Artifact | Format and ownership | Lifecycle and sensitivity |
| --- | --- | --- |
| Prepared input | Analyst-provided XLSX | Read-only to the application. Raw answer text stays local and is hashed for the run fingerprint. |
| Configuration | Versioned TOML | User-controlled, canonicalized into the configuration hash. Credentials are never stored here. |
| Run result | New XLSX with six fixed sheets | Contains raw local answer text, redacted analysis text, assignments, categories, choices, review fields, and errors. Never overwrite the input. |
| Run manifest | Versioned JSON | Records hashes, exact profiles/parameters, stage counts, costs, warnings, vector metadata, cache metadata, and resume compatibility. Never contains credentials. |
| Vectors | One run-local NumPy memmap, `float32`, shape `(vector_count, 2048)` | Canonical vector artifact for answer variants and choice anchors. Flush, close, checksum, and validate before clustering or resume. |
| Row map | Deterministic JSON or equivalent sidecar | Maps `variant_id`/`choice_id` to memmap row; never infer identity from post-preprocessing workbook order. |
| Checkpoints | Atomic run-local checkpoint records | Store completed stages and recovery metadata. Resume requires identical compatibility hashes and provider/model profiles. |
| Provider cache | Workspace-relative persistent plaintext files | Contains only deterministically redacted requests/responses or bulk-embedding metadata/checksums. Actual bulk vectors stay in the memmap. Manual `cache purge` is required for deletion. |
| Logs | Structured local log files | Operational events, retries, failures, and stage progress without credentials or raw unredacted text. |

At 100,000 vector rows, the raw 2048-dimensional matrix is approximately 819.2 MB (781.25 MiB) before anchors, row maps, PCA/clustering buffers, and the operating system working set. Memory ceilings and peak resident memory must therefore be explicit configuration and manifest fields. Cache files remain separate from result workbooks and should be ignored by generated `.gitignore` defaults.

## LLMs

### Nebius Token Factory

- Provider role: embeddings only.
- Model: exact `Qwen/Qwen3-Embedding-8B` profile; no mutable alias or automatic provider routing.
- Representation: requested 2048 dimensions, `float32`, L2-normalized, persisted in the canonical memmap.
- Input: redacted question context plus redacted answer or choice-anchor text in its supplied/original language.
- Instruction: one fixed English instruction whose hash is part of vector cache and resume compatibility.
- Policy: no translation, transliteration, summarization, language labels, or provider-specific hints appended to the semantic text.
- Credential: `NEBIUS_API_KEY`; optional non-secret `NEBIUS_AI_PROJECT_ID` only when the authenticated account requires it.

### Direct Google Gemini API

- Provider role: structured generation only.
- Model: exact direct `gemini-3.5-flash` generation profile.
- Operations: existing-choice verification, promoted-cluster bilingual labeling, and screened composite verification.
- Output: locally validated structured JSON. Category labels/descriptions must include `label_en`, `description_en`, `label_ar`, and `description_ar`; Arabic fields must use native Arabic script rather than Latin transliteration.
- Input: only redacted answer, question, choice, or cluster evidence required for the operation; never passthrough metadata or unredacted text.
- Credential: `GEMINI_API_KEY`, kept separate from Nebius identity and configuration.

Both providers require mocked contract tests in the default suite and tiny synthetic, non-sensitive credential-gated smoke tests before their v1 profiles are advertised as supported. Hosted-model variance must be surfaced in manifests rather than represented as byte-identical determinism.
