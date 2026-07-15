# Project Overview

`other-cluster` is a Python 3.13 command-line application that accepts one prepared XLSX workbook containing a survey question, its existing choices, and up to 100,000 open-text `Other` answers. It validates and preprocesses the workbook locally, preserves the original answers, redacts provider-bound text deterministically, embeds eligible answers in their supplied languages through Nebius, conservatively matches existing choices, discovers coherent candidate categories, and uses direct Google Gemini structured generation for verification, bilingual category labels, and composite-answer review. Each source row receives exactly one auditable assignment or explicit status in a new result workbook, accompanied by a JSON run manifest and resumable vector/checkpoint artifacts.

## Goals

1. Provide a reproducible, `uv`-managed CLI for clustering one survey question per run.
2. Reject invalid workbook, configuration, model-profile, redaction, and credential contracts before semantic provider calls.
3. Preserve raw answer text locally while sending only deterministically redacted original-language text to remote providers.
4. Match answers to existing choices only when both conservative vector gates and structured LLM verification agree.
5. Discover new categories without forcing noise, rare meanings, ambiguous answers, or composites into unsafe assignments.
6. Produce complete audit artifacts so every `answer_id`, model decision, threshold, cost, warning, and failure is traceable.
7. Support cost preflight, persistent cache inspection/purge, checkpointing, and safe resume without provider or model mixing.
8. Establish a multilingual pilot baseline for Arabic, including dialectal Arabic, and English; broader language coverage can be added when real evaluation data is available.

## Core User Flow

1. The analyst prepares an XLSX workbook with exactly `Question`, `Choices`, and `Answers` sheets, and creates a versioned TOML configuration.
2. The analyst uses `template` when a correctly shaped starter workbook or example configuration is needed.
3. The analyst runs `validate`; the CLI checks the full local contract without making semantic API calls.
4. The analyst runs `estimate`; the CLI preprocesses locally, sizes requests, estimates worst-case cost including retries, and rejects a run that exceeds its hard budget.
5. The analyst may run `preview` to inspect a deterministic, stratified sample and language-quality diagnostics before authorizing the full run.
6. `run` creates a run ID, fingerprints the input/configuration/prompt/profile contracts, checks provider capabilities, and performs budget preflight.
7. The local pipeline preserves raw values, classifies blanks and configured non-semantic markers, normalizes text, redacts provider-bound text, detects language after deduplication, and maps repeated values to unique normalized variants.
8. Nebius embeds each eligible redacted original-language variant and each existing-choice anchor into the fixed 2048-dimensional `float32` memmap; vector gates identify candidates for existing-choice verification.
9. Direct Google Gemini verifies only vector-qualified existing-choice candidates, screens composites, labels promoted new clusters in English and native Arabic script, and reviews screened composite answers through structured schemas.
10. The pipeline assigns at most one primary category per source row, retains advisory secondary suggestions for verified composites, and explicitly records rare, ambiguous, low-confidence, non-semantic, blank, and provider-error outcomes.
11. The CLI writes a new six-sheet audit workbook, a versioned JSON manifest, the canonical vector artifact, row maps, checkpoints, logs, and redacted provider cache records.
12. The analyst reviews the workbook and can resume a compatible interrupted run or inspect/purge the persistent cache without mutating the input workbook or official survey choices.

## Features

### Input and contract management

- Fixed three-sheet input contract with one question row, optional existing choices controlled by `pure_discovery`, and answer-level passthrough metadata.
- Required string handling that preserves leading zeroes in IDs.
- Formula rejection in required fields, duplicate-ID detection, boolean and language-code validation, and exact sheet/column validation.
- Versioned TOML configuration with explicit provider/model profiles, thresholds, budgets, retry policy, redaction rules, cache policy, and deterministic parameters.
- Environment-only credentials loaded through `python-dotenv` into secret-safe settings.

### Local preprocessing and privacy controls

- Raw answer preservation alongside a separate analysis representation.
- Unicode NFC normalization, deterministic emoji and non-text-symbol cleanup, whitespace cleanup, and cleanup statistics.
- Configurable non-semantic marker classification for blanks, refusals, test entries, and administrative codes.
- Stable deterministic redaction for emails, phones, URLs, identifiers, and analyst-supplied patterns.
- Language-hint precedence, low-accuracy Lingua detection after deduplication, confidence warnings, and no translation or transliteration.
- Stable variant IDs, deduplication, occurrence counts, and source-row remapping.

### Semantic matching and discovery

- Nebius `Qwen/Qwen3-Embedding-8B` original-language embeddings with a fixed 2048-dimensional `float32`, L2-normalized memmap representation.
- Existing-choice anchor construction and configurable similarity/margin gates.
- Direct Google `gemini-3.5-flash` structured verification for conservative existing-choice assignment.
- Deterministic bounded frequency expansion, PCA, HDBSCAN-style discovery, noise preservation, rare-candidate preservation, and stable `NEW-###` IDs.
- Bilingual, evidence-grounded English/Arabic labels and descriptions for proposed new categories.
- Composite screening and structured verification with one primary category and advisory secondary suggestions.

### Auditability and operations

- New six-sheet result workbook: `Summary`, `Assignments`, `Unique Variants`, `Categories`, `Choice Matches`, and `Unresolved and Errors`.
- Versioned JSON manifest containing hashes, provider/model details, parameters, counts, costs, warnings, vector metadata, cache metadata, and resume compatibility.
- Deterministic review sample of up to 500 rows with blank analyst-review columns; v1 does not ingest analyst edits.
- Persistent plaintext cache of redacted provider payloads and metadata, with explicit inspection and manual purge commands.
- Checkpointing, circuit breakers, structured logs, failure continuation for individual items, and safe resume for compatible runs.

### Command surface

- `template`, `validate`, `estimate`, `preview`, `run`, and `resume` commands.
- `cache inspect` and confirmation-protected `cache purge` commands.
- Meaningful nonzero exit codes for contract errors, budget rejection, provider preflight failure, circuit-breaker termination, and incomplete output.

## In Scope

- One prepared XLSX workbook representing one survey question per run.
- Existing-choice matching, pure discovery when explicitly enabled, proposed new categories, rare meanings, noise, ambiguity, and composite-answer review.
- Local validation, normalization, deduplication, language diagnostics, deterministic redaction, request planning, cost estimation, semantic calls, clustering, assignment, audit output, caching, checkpointing, and resume.
- Nebius Token Factory for embeddings and the direct Google Gemini API for generation, with separate provider identity and credentials.
- Arabic including dialectal Arabic and English in the initial evaluation fixture.
- Synthetic, non-sensitive credential-gated provider smoke tests and a manually labeled pilot fixture.

## Out of Scope

- Extracting survey questions or `Other` values from SurveyCTO or another survey platform.
- Survey-platform integration, form write-back, official choice/codebook mutation, or analyst-feedback ingestion.
- Persistent category registries, cross-wave category-ID reconciliation, and category merging workflows.
- Automatic translation, transliteration, language-dependent rewriting, translated answer fields, or language-specific routing.
- Local-model execution, additional hosted-provider adapters beyond the selected v1 pair, batch/offline provider APIs, and a web UI.
- Automatic removal guarantees for names or informal locations that deterministic redaction cannot recognize.
- Treating generated bilingual labels as translations of individual answers.

## Success Criteria

- Invalid input/configuration and conservative budget overruns make zero paid semantic calls.
- Every input `answer_id` appears exactly once in `Assignments`, including blanks, non-semantic markers, provider failures, rare candidates, and unresolved cases.
- No raw answer text or passthrough metadata is sent to either provider; raw answers remain available only in local audit artifacts.
- Existing-choice assignments require the configured vector similarity gate, runner-up margin, and affirmative structured verifier result.
- New categories remain `proposed_for_review`; category-cap overflow fails diagnostically instead of forcing unrelated merges.
- All generated categories contain non-empty English and native-Arabic label and description fields, or an explicit labeling error.
- A successful run produces the six-sheet XLSX, JSON manifest, canonical memmap and row map, checksums, and required checkpoints/logs.
- Compatible resume rejects changed input/configuration/profile/model/endpoint/dimension/instruction/redaction hashes and never silently switches providers.
- The pilot reports assignment correctness, category coherence, coverage, and unresolved rate side by side overall and by language.
- Practical pilot targets are at least 90% correctness for sampled automatic assignments, at least 85% category coherence, complete exactly-one-output traceability, and passing credential-gated smoke suites for both providers before profiles are advertised as supported.
