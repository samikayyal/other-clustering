# One-Question “Other” Answer Clustering CLI

## Summary

Build a Python 3.13 command-line program, provisioned and run exclusively through `uv`, that accepts one prepared XLSX workbook containing:

- One survey question.
- Its existing choices, if any.
- Up to 100,000 open-text `Other` answers.

The program will assign high-confidence answers to existing choices, discover coherent new candidate categories, preserve rare meanings, and explicitly route ambiguous or invalid answers to review. It will produce a full audit XLSX and a JSON run manifest. Survey extraction, form integration, write-back, and analyst-feedback ingestion remain out of scope.

The semantic pipeline will be hybrid:

1. Local validation, normalization, deduplication, language detection, and deterministic redaction.
2. Original-language multilingual embeddings for every eligible redacted answer variant and choice anchor using `Qwen/Qwen3-Embedding-8B` through Nebius.
3. Conservative existing-choice matching.
4. Density-based discovery of new categories.
5. LLM-assisted cluster labeling, anchor verification, and composite-answer review through Nebius.

Nebius Token Factory is the sole embedding provider in v1. The requested generation model is `gemini-3.5-flash`, but its provider route is not yet locked: it must either be available in the Nebius model catalog or run through the direct Google Gemini API. If it is not available through Nebius, v1 becomes a deliberate two-provider design or the generation model must be replaced with a Nebius-listed text model. No translation or language-dependent representation switch is performed in v1.

## Public Contracts and Interfaces

### Project and CLI

Create a packaged CLI named `other-cluster`, invoked through `uv run other-cluster ...`.

Commands:

- `template --output INPUT.xlsx`
  - Generate the fixed three-sheet input template and a documented example TOML configuration.
- `validate --input INPUT.xlsx --config CONFIG.toml`
  - Validate all workbook, configuration, model-profile, redaction, and credential requirements without making semantic API calls.
- `estimate --input INPUT.xlsx --config CONFIG.toml`
  - Perform validation, preprocessing, deduplication, language diagnostics, request sizing, and a conservative cost estimate.
  - Make no paid semantic calls.
  - Refuse to continue if the selected model profile lacks pricing metadata.
- `preview --input INPUT.xlsx --config CONFIG.toml --output-dir DIR`
  - Analyze a fixed-seed, frequency/language-stratified sample capped at 2,000 unique normalized variants.
  - Report language distribution, detector confidence, and possible weak-language groups for quality review; never recommend or invoke translation.
  - Produce a preview workbook and preview manifest without authorizing a full run.
- `run --input INPUT.xlsx --config CONFIG.toml --output-dir DIR`
  - Execute a complete run only after validation and budget preflight pass.
- `resume --run-id RUN_ID --output-dir DIR`
  - Resume from the last completed checkpoint.
  - Require the same input hash, configuration hash, provider, model IDs, model parameters, and redaction rules.
- `cache inspect`
  - Report cached payload counts, sizes, providers, models, and run IDs without printing payload bodies.
- `cache purge [--run-id RUN_ID | --before DATE]`
  - Preview what will be deleted and require explicit confirmation before deleting persistent payloads.

Use meaningful nonzero exit codes for schema/configuration errors, budget rejection, provider preflight failure, circuit-breaker termination, and incomplete output.

### Input workbook

Require all three sheets, with exact names.

`Question` must contain exactly one data row:

- `question_id`: required, nonblank stable string.
- `question_text`: required, nonblank question wording.
- `pure_discovery`: required boolean.
  - `false` requires at least one row in `Choices`.
  - `true` explicitly permits an empty `Choices` sheet.

`Choices` must always exist. Each nonblank row contains:

- `choice_id`: required, unique stable string.
- `choice_label`: required.
- `choice_description`: optional.
- `choice_examples`: optional newline-delimited examples.

`Answers` contains:

- `answer_id`: required, unique string; preserve leading zeroes.
- `answer_text`: required column, although individual cells may be blank and receive a row status.
- `answer_language`: optional ISO language hint.
- Any additional columns: accepted as local passthrough metadata, copied unchanged to assignment output, never used as clustering features, and never sent to providers.

Reject formulas in required fields, duplicate IDs, additional rows in `Question`, missing sheets or columns, invalid booleans, invalid language-code syntax, duplicate choice IDs, and inconsistent pure-discovery settings before any provider call.

### TOML configuration

Use a versioned TOML schema with these sections:

- `run`
  - schema version, fixed random seed, selected provider profile, output location, preview size.
- `models.nebius`
  - Explicit embedding model ID, fixed to `Qwen/Qwen3-Embedding-8B` for v1.
  - If the Nebius-only generation route is selected, an explicit, pinned Nebius text-generation model ID for structured judgments and category labels; the embedding model is not used for generation.
  - Explicit Nebius Token Factory API base URL and endpoint policy; the v1 example defaults to `https://api.tokenfactory.nebius.com/v1/` and uses the OpenAI-compatible embeddings and chat-completions routes.
  - Explicit embedding output dimension and normalization policy. The dimension must be fixed in the profile and run hash; Qwen supports a configurable output dimension from 32 through 4096.
  - One fixed English embedding instruction/task definition and exact answer/anchor formatting rules. The instruction policy must be identical for every language and run unless the profile changes.
  - Model parameters, timeouts, retry limits, batching, and structured-output settings.
  - Unit-pricing metadata and `pricing_checked_at`.
- `models.google` (only if direct Gemini generation is selected)
  - Generation model fixed to `gemini-3.5-flash`.
  - Google Gemini API base URL, structured-output settings, safety settings, timeout/retry policy, and unit-pricing metadata.
  - Separate provider identity and credentials; do not pretend this route is Nebius-hosted.
- `clustering`
  - `min_cluster_size = 3`.
  - `max_new_categories = 50`.
  - Deterministic PCA dimension, default `50`.
  - HDBSCAN parameters.
  - `cluster_membership_min = 0.80`.
- `choice_matching`
  - Initial conservative defaults `similarity_min = 0.80` and `margin_min = 0.08`.
  - Require both the vector gate and an affirmative structured LLM verification before automatic existing-choice assignment.
  - Keep thresholds configurable because similarity distributions differ with embedding dimension, instruction policy, language mix, and dataset.
- `normalization`
  - Unicode normalization, whitespace trimming/collapse, and comparison casing only.
- `nonsemantic`
  - Configurable exact markers and regular expressions for refusals, don’t-know values, test entries, and administrative codes.
- `redaction`
  - Deterministic rules for emails, phone numbers, URLs, identifiers, and analyst-supplied patterns.
- `budget`
  - Hard per-run upper limit.
  - If the conservative estimate exceeds the limit, make zero paid calls and fail preflight.
- `failures`
  - Retry policy.
  - Circuit breakers defaulting to 20 consecutive failures or more than 5% failures after at least 100 calls.
- `cache`
  - Workspace-relative directory.
  - Persistent, plaintext full request/response payloads.
  - No automatic expiry; deletion is manual.

Credentials and optional account identifiers are environment variables only:

- `NEBIUS_API_KEY`
- Optional non-secret `NEBIUS_AI_PROJECT_ID` when the Nebius account requires the `ai_project_id` request parameter.
- Conditional `GEMINI_API_KEY` only if direct Google generation is selected.

Never serialize credentials into TOML, logs, manifests, workbooks, checkpoints, or caches.

### Internal provider and data interfaces

Define typed interfaces and Pydantic models so clustering code does not depend on vendor payloads.

`SemanticProvider` operations:

- `healthcheck(profile) -> CapabilityReport`
- `estimate(request_plan) -> CostEstimate`
- `embed(texts, profile) -> EmbeddingBatch`
- `generate_structured(operation, payload, schema, profile) -> StructuredBatch`

Core models:

- `QuestionSpec`
- `ChoiceAnchor`
- `AnswerRecord`
- `NormalizedVariant`
- `LanguageAssessment`
- `ProviderRequestRecord`
- `ExistingChoiceMatch`
- `ClusterCandidate`
- `Assignment`
- `ReviewRecord`
- `RunManifest`
- `Checkpoint`

All generative responses must be schema-constrained and locally validated. Invalid structured responses are retried; persistent item-level failures become unresolved records.

Ship explicit, editable profiles rather than hidden aliases. The Nebius profile must use `Qwen/Qwen3-Embedding-8B` for every eligible embedding input and record one fixed output dimension and instruction policy. The selected generation route must name either a pinned Nebius text model or direct Google `gemini-3.5-flash`, and must pass its own structured-output smoke suite. Verify the exact Nebius model IDs against the live catalog before advertising them as supported. [Qwen3-Embedding-8B model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B), [Nebius embeddings API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings), [Nebius structured output](https://docs.tokenfactory.nebius.com/ai-models-inference/json), [Nebius chat-completions API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion).

## Processing and Clustering Design

### 1. Validate and fingerprint

Before any semantic request:

- Parse the workbook with required fields treated as strings.
- Validate the complete input and TOML contracts.
- Hash the workbook content, normalized configuration, model profiles, prompts, deterministic redaction rules, and package versions.
- Create a run ID and checkpoint directory.
- Verify the selected provider set supports embedding and structured generation using the configured model IDs, endpoint routes, output dimension, and JSON-schema behavior.
- Reject mutable model aliases and any provider-side automatic model routing.
- Build a conservative request and cost plan.
- Refuse execution if the upper-bound estimate exceeds the hard budget.

### 2. Classify, normalize, and deduplicate locally

For every input row:

- Preserve `answer_text` exactly.
- Assign blank and configured administrative/non-semantic values explicit statuses without sending them to AI.
- Apply only Unicode normalization, comparison casing, whitespace trimming, and whitespace collapse.
- Create a deterministic `variant_id` from the normalized value.
- Deduplicate semantic calls by variant while preserving the full mapping back to every `answer_id`.
- Retain occurrence counts so frequent answers influence cluster density and category summaries.

Expected early statuses include:

- `blank`
- `nonsemantic_marker`
- `eligible`
- `redaction_warning`
- `language_uncertain`

### 3. Detect language and apply deterministic redaction

- Prefer a valid analyst-supplied `answer_language`.
- Otherwise use local Lingua detection and record the detected language and confidence.
- Treat low-confidence or unsupported local detection as metadata warnings only; do not skip or rewrite the answer.
- Redact emails, phones, URLs, configured ID patterns, and analyst-supplied patterns locally.
- Use stable placeholders such as `[EMAIL_1]` so equivalent redacted variants remain comparable.
- Every eligible redacted original proceeds to the embedding stage regardless of detected language. Blank and deterministic non-semantic rows remain intentionally excluded from semantic calls.
- Never send passthrough metadata or unredacted answer text to Nebius.
- Explicitly document that deterministic redaction does not guarantee removal of names or unstructured locations.

Language detection is an audit and sampling signal, not a routing or translation decision. Preview must report unsupported and low-confidence detector results rather than treating the detector as authoritative. Optional language hints are the preferred override for very short answers. [Lingua language detector](https://pypi.org/project/lingua-language-detector/).

### 4. Generate original-language embeddings and match existing choices

- Embed every unique eligible analysis variant once using Nebius `Qwen/Qwen3-Embedding-8B` on the redacted original-language text. No translation, language-specific model, or runtime representation switch is allowed.
- Embed choice anchors in the same provider, model, dimension, normalization policy, and fixed instruction context. Preserve their supplied language; do not translate them.
- Store the exact embedding dimension, instruction identifier, normalization policy, and model ID in each cache key and in the manifest.
- Build each anchor representation from the question text, choice label, optional description, and optional examples.
- Calculate cosine similarity to every existing choice.
- Treat the highest-ranked choice as an automatic candidate only when:
  - Similarity passes the selected profile’s minimum.
  - Separation from the runner-up passes the margin minimum.
  - The structured LLM verifier returns `match`, cites evidence from the answer and choice definition, and does not mark the answer composite or ambiguous.
- Assign confirmed candidates the existing `choice_id`.
- Keep ranked suggestions for all other answers, but do not force an existing-choice assignment.

Existing-choice assignment statuses include:

- `assigned_existing`
- `ambiguous_existing`
- `no_existing_match`
- `existing_match_error`

### 5. Discover new categories

Run discovery over substantive answers that were not confidently assigned to existing choices:

- Reuse unique-variant embeddings but expand or weight them by source-row frequency so repeated answers affect density.
- Apply deterministic PCA to 50 dimensions, bounded by the sample size and original embedding dimension.
- Run HDBSCAN-style density clustering using a fixed seed and deterministic input ordering.
- Default `min_cluster_size` to 3.
- Preserve HDBSCAN noise rather than forcing it into the nearest cluster.
- Require membership probability of at least `0.80` for an automatic new-category assignment.
- Preserve one- and two-answer meanings as rare candidates instead of collapsing them into a generic residual category.
- Order new clusters deterministically by weighted size and stable medoid identity, then assign run-local IDs such as `NEW-001`.
- If more than the configured 50 promoted new categories emerge, finish diagnostics and provisional output but mark category finalization as failed; do not merge unrelated clusters merely to satisfy the cap.

For every promoted cluster:

- Select frequent examples, medoids, boundary cases, and represented languages.
- Ask the configured LLM for one evidence-grounded English label and short description.
- Prohibit the model from introducing concepts absent from member answers.
- Compare the cluster against existing choices using the same vector and structured-verification gates.
- Reclassify the cluster to an existing choice only when both gates agree conservatively; otherwise retain it as a proposed new category.
- Mark all discovered category labels `proposed_for_review`; never mutate the input workbook or official survey choices.

### 6. Detect composite answers

Use a two-stage process:

- Screen for likely composites using punctuation/conjunction patterns, strong affinity to multiple categories, and small top-category margins.
- Send only screened candidates to the configured LLM for structured composite verification.
- Give each answer exactly one primary category.
- When verified as composite, set `composite = true` and retain ranked secondary suggestions.
- If no defensible primary category exists, use an unresolved status instead of forcing a choice.

### 7. Assign every source row

Every `answer_id` must appear exactly once in the assignment output, including blanks, non-semantic markers, provider failures, rare candidates, and unresolved cases.

Final assignment statuses include:

- `assigned_existing`
- `assigned_new`
- `rare_candidate`
- `unresolved_low_confidence`
- `unresolved_ambiguous`
- `unresolved_composite`
- `unresolved_language`
- `nonsemantic_marker`
- `blank`
- `provider_error`

`unresolved_language` must not be assigned solely because local language detection is uncertain; it requires an attempted original-language semantic path and an explicit semantic/review failure.

No answer may disappear silently.

## Artifacts, Auditability, and Failure Handling

### Result workbook

Create a new XLSX; never modify the input.

Fixed sheets:

- `Summary`
  - Run status, question, provider/models, counts, costs, coverage, unresolved rate, redaction totals, language distribution, category totals, threshold values, warnings, and quality-review instructions.
- `Assignments`
  - `answer_id`, raw answer, normalized variant ID, language hint/detection/confidence, redacted original-language analysis text, status, primary category ID/type/label, confidence, composite flag, secondary suggestions, unresolved reason, review-sample flag, blank analyst-review columns, and all local passthrough metadata.
- `Unique Variants`
  - Variant ID, normalized form, row count, language information, redaction summary, embedding model/dimension/instruction identifiers, cache key, primary result, and confidence.
- `Categories`
  - Existing and new category IDs, type, generated English label, description, weighted answer count, unique-variant count, membership statistics, representative examples in original language, anchor relationship, and `proposed_for_review` status. Generated labels are evidence-grounded synthesis, not translated answer fields.
- `Choice Matches`
  - Ranked existing-choice candidates, cosine similarities, margins, structured-verifier verdicts, and final match disposition.
- `Unresolved and Errors`
  - Every unresolved answer/variant, pipeline stage, reason code, retry count, provider error category, and suggested analyst action.

The deterministic review sample of up to 500 rows is marked in `Assignments` and stratified across:

- Large and small promoted categories.
- Existing-choice assignments.
- Rare candidates.
- Noise/unresolved answers.
- Composite answers.
- Frequent and rare variants.
- Represented languages and language-detection confidence groups.

The workbook provides blank analyst columns for correctness, preferred category, category-coherence judgment, and notes. V1 does not ingest those edits.

### JSON manifest

Write a versioned manifest containing:

- Run ID, schema version, status, timestamps, and stage checkpoints.
- Input, configuration, prompt, profile, and output hashes.
- Selected provider and exact model IDs.
- Exact model parameters, embedding dimensions, and normalization rules.
- Python and dependency versions.
- Fixed seed and deterministic ordering rules.
- Counts at every pipeline stage.
- Token/request usage, estimated cost, actual recorded cost, and budget.
- Redaction-rule hash and redaction counts, but no credentials.
- Original-language-only embedding policy, language distribution, detector warnings, embedding instruction identifier, and exact output dimension.
- Thresholds, clustering parameters, quality metrics, and warnings.
- Cache paths and payload counts.
- Failure/circuit-breaker details.
- Resume compatibility information.

### Cache and logs

Honor the chosen higher-risk cache policy:

- Store complete redacted provider requests and responses as readable workspace files.
- Keep them indefinitely until `cache purge` is run.
- Never duplicate raw, unredacted answers in cache payloads.
- Keep the cache separate from result workbooks.
- Add the cache directory to generated `.gitignore` defaults and warn if files appear tracked.
- State plainly in every manifest that the cache is plaintext, persistent, and may contain sensitive redacted survey content.
- Use structured operational logs without credentials or raw unredacted answer text.

### Failure behavior

- Structural input/configuration errors: fail before provider calls.
- Budget estimate above limit: fail before paid calls.
- Individual malformed or failed embedding, judgment, or labeling request:
  - Retry according to policy.
  - Record unresolved status.
  - Continue the run.
- Systemic provider failure:
  - Stop after 20 consecutive failed calls, or more than 5% failures after at least 100 calls.
  - Flush manifest, payload cache, unresolved records, and checkpoint.
- Resume:
  - Continue only with identical hashes and the same provider/model profile set.
  - Never silently switch providers, change the configured model IDs, endpoint, dimension, or instruction policy.
- Reproducibility:
  - Use fixed seeds, deterministic sorting, pinned models, exact parameters, stable embedding instructions and generation prompts, cached responses, and manifest hashes.
  - Surface unavoidable hosted-model variance instead of claiming byte-identical semantic results.

## Test and Acceptance Plan

### Automated tests

Use `uv run pytest` for all tests.

Unit coverage:

- Workbook and TOML schema validation.
- Required string-ID preservation, including leading zeroes.
- Pure-discovery and choices-sheet rules.
- Formula rejection in required fields.
- Unicode/light normalization without alteration of raw text.
- Deduplication and source-row remapping.
- Non-semantic marker classification.
- Deterministic redaction and placeholder stability.
- Language hint precedence and uncertain detection.
- Original-language embedding invariant, fixed Qwen model ID, dimension, normalization, and instruction policy.
- Cost estimation and zero-call budget rejection.
- Similarity/margin choice gates.
- HDBSCAN noise, rare candidate, and membership handling.
- Stable run-local category IDs.
- Category-cap failure without forced merging.
- Composite screening and structured verification.
- Circuit-breaker thresholds.
- Checkpoint/hash compatibility.
- Plaintext cache inspection and confirmed purge.
- Manifest completeness and secret exclusion.

Fixture integration scenarios:

- English-only question with obvious existing-choice matches.
- New coherent category absent from existing choices.
- Empty choices with explicit pure discovery.
- Mixed Arabic, English, French, and additional-language answers that represent the same concept.
- Cross-language grouping using only original-language embeddings, with no translation fields or calls.
- One-word answers with language hints and low-confidence detection.
- Detector-uncertain answers still embedded and surfaced as language-quality warnings.
- Duplicate variants mapping back to many unique answer IDs.
- Blanks, refusals, test markers, URLs, phones, emails, and configured IDs.
- Rare one- and two-answer meanings.
- Multi-concept answers receiving a primary category, composite flag, and secondary suggestions.
- Weak existing-choice matches remaining unresolved.
- More than 50 promoted categories producing a diagnostic failure rather than merges.
- Individual provider failures continuing as unresolved.
- Systemic failures checkpointing and resuming without provider mixing.
- Complete six-sheet workbook and JSON-manifest round trip at 100,000 rows.

Provider tests:

- Mocked contract tests for the Nebius adapter are mandatory in the default suite.
- Credential-gated live smoke tests must cover `Qwen/Qwen3-Embedding-8B` embeddings, the selected structured-generation route, JSON-schema behavior, pricing/preflight behavior, endpoint selection, and invalid-model rejection. If direct Google generation is selected, its adapter and live smoke test are mandatory too.
- Live tests are opt-in and must use tiny synthetic, non-sensitive fixtures.
- The v1 Nebius profile is usable only after its live smoke suite passes.

### Pilot acceptance

Prepare a seeded, stratified analyst sample of up to 500 assignments.

V1 passes its practical pilot when:

- At least 90% of sampled automatically assigned rows are judged correctly assigned.
- At least 85% of sampled promoted categories are judged internally coherent.
- Every input `answer_id` is traceable to exactly one output assignment/status.
- No structural error, blank, excluded marker, provider failure, or unresolved answer is silently omitted.
- The measured assignment coverage and unresolved rate are reported separately and are not manipulated by forcing low-confidence answers.
- The sole Nebius profile passes the credential-gated live smoke suite before being advertised as supported.

## Assumptions and Explicitly Deferred Scope

- The prepared workbook contains exactly one question per run.
- Survey extraction and detection of `Other` fields are out of scope.
- Source question mode is irrelevant to v1 clustering.
- Every answer receives one primary category at most; secondary suggestions are advisory.
- Existing-choice assignments are automatic only under conservative vector and LLM agreement.
- New categories are proposals requiring analyst review.
- English is the canonical language for generated labels and descriptions; this is generated labeling, not a translation of stored answer text.
- No translation is performed anywhere in v1. All eligible semantic inputs remain in their supplied/original language for embedding and evidence review.
- Original answer text remains the primary evidence and is always preserved locally.
- Input and output may contain raw sensitive text; every selected remote provider receives only deterministically redacted text and no passthrough metadata.
- Deterministic redaction does not guarantee removal of names or informal locations.
- The user accepts persistent plaintext caching of complete redacted hosted request/response payloads.
- Persistent category registries, cross-wave ID reconciliation, analyst-feedback ingestion, category merging through an editing workflow, official codebook mutation, translation, additional hosted-provider adapters beyond the selected v1 provider set, local-model execution, web UI, survey-platform integration, and survey write-back are deferred.
- The initial runtime baseline is the currently configured local environment: Python 3.13 and `uv` 0.6.14.

## Open Decisions Before Implementation

The overall v1 strategy is fixed, but these details still need explicit values in the example TOML profile and acceptance fixtures:

- **Generation model/provider:** the requested model is `gemini-3.5-flash`. Confirm whether Nebius actually exposes that exact model ID. If not, either select a Nebius-listed generation model to preserve a single-provider design or deliberately add the direct Google Gemini provider and its credential/budget/privacy contract. `Qwen/Qwen3-Embedding-8B` is embedding-only and cannot fill this role.
- **Embedding dimension and storage:** choose the Qwen output dimension, vector numeric type, and whether 100,000 unique variants use an in-memory array, memory-mapped file, or another bounded-storage strategy. The dimension affects RAM, cache size, transfer volume, and clustering performance.
- **Embedding instruction policy:** finalize the exact English instruction and whether answers and choice anchors use one shared instruction or a documented query/anchor asymmetry. Hash this text as part of the run contract.
- **Nebius account and endpoint contract:** confirm the Token Factory base URL used by the profile, whether `NEBIUS_AI_PROJECT_ID` is required, and the region/data-residency requirements for redacted survey content.
- **Nebius privacy settings:** decide whether requests must set `store=false` or an equivalent retention control, and document the provider-side retention/training policy alongside the local plaintext-cache warning.
- **Capacity and pricing limits:** record current embedding and generation prices, maximum request size, batch size, concurrency/rate limits, timeout/backoff policy, and a worst-case 100,000-variant estimate. The estimate must include retries and structured-generation calls.
- **Long-answer policy:** define tokenization, truncation/rejection behavior, and whether the question/choice context is embedded with each answer or represented separately when inputs approach the model context limit.
- **No-translation quality bar:** define which languages/scripts are covered by the pilot, how cross-language coherence is measured with original text only, and whether detector-uncertain or out-of-coverage answers receive only a warning or can become unresolved after semantic review.
- **Generated-label language:** confirm that labels and descriptions remain English-only generated summaries, with original-language examples as evidence, rather than adding multilingual output fields in v1.
- **Python runtime alignment:** the project is aligned on Python 3.13 through `.python-version` and `pyproject.toml`; record the exact runtime and `uv` version in the manifest when implementation begins.
