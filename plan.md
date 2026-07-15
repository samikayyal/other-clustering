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
5. LLM-assisted cluster labeling, anchor verification, and composite-answer review through the direct Google Gemini API using `gemini-3.5-flash`.

V1 is deliberately a two-provider design: Nebius Token Factory is the sole embedding provider, and the direct Google Gemini API is the sole generation provider. `Qwen/Qwen3-Embedding-8B` is never used for generation, and Gemini is not treated as Nebius-hosted. No translation or language-dependent representation switch is performed in v1.

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
  - schema version, fixed random seed, selected provider/model profile set, output location, preview size.
- `models.nebius`
  - Explicit embedding model ID, fixed to `Qwen/Qwen3-Embedding-8B` for v1.
  - Explicit Nebius Token Factory API base URL and endpoint policy; the v1 example defaults to `https://api.tokenfactory.nebius.com/v1/` and uses the embeddings route.
  - Embedding output fixed to `2048` dimensions, `float32`, L2-normalized vectors, and a NumPy memory-mapped artifact. These values are part of the profile and run hash. The Nebius endpoint also supports 4096, but 4096 remains an evaluation alternative rather than the v1 storage profile.
  - One fixed English embedding instruction/task definition and exact answer/anchor formatting rules. The instruction policy must be identical for every language and run unless the profile changes:

    ```text
    Task: represent this survey text for semantic clustering and category matching.
    Preserve the meaning in the supplied language.
    Do not translate, summarize, infer personal attributes, or add concepts.

    Survey question:
    {redacted_question_text}

    Text:
    {redacted_text}
    ```

    Do not append detector labels, transliterations, or provider-specific language hints to the text. For a choice anchor, serialize redacted `Label`, optional redacted `Description`, and newline-delimited redacted `Examples` under the same instruction and question context.
  - Embedding batch size, initial concurrency, timeouts, retry limits, and rate-limit handling. Start with synchronous batches of 32–64 inputs and low concurrency (default `2`), then increase only after a synthetic smoke run observes stable latency and no rate-limit pressure.
  - Unit-pricing metadata and `pricing_checked_at`.
- `models.google`
  - Direct Google Gemini generation model fixed to `gemini-3.5-flash`.
  - Direct Google Gemini API base URL and `generateContent` endpoint policy (the v1 example uses Google's Gemini API directly, not an OpenAI-compatible proxy), structured-output settings, safety settings, timeout/retry policy, and unit-pricing metadata.
  - Structured-generation batch size and a configurable maximum verification-item budget; category labeling and composite-review calls are counted separately in preflight.
  - Category-label schema requires both `label_en`/`description_en` and `label_ar`/`description_ar` from the LLM. Arabic output must use Arabic script; Latin transliteration is not an accepted substitute.
  - Separate provider identity and credentials; do not pretend this route is Nebius-hosted.
- `clustering`
  - `min_cluster_size = 3`.
  - `max_new_categories = 50`.
  - `expansion_cap = 20` for bounded frequency expansion during discovery.
  - Deterministic PCA dimension, default `50`.
  - Streaming/incremental PCA and an explicit working-memory ceiling; a memmap bounds vector storage but does not automatically make PCA or HDBSCAN memory-bounded.
  - HDBSCAN parameters.
  - `cluster_membership_min = 0.80`.
- `choice_matching`
  - Initial defaults `similarity_min = 0.80` and `margin_min = 0.08`; calibrate both thresholds on the manually labeled gold fixture before the pilot, using the documented assignment-quality and coverage/unresolved trade-offs.
  - Require both the vector gate and an affirmative structured LLM verification before automatic existing-choice assignment.
  - Keep thresholds configurable because similarity distributions differ with embedding dimension, instruction policy, language mix, and dataset.
- `normalization`
  - Normalize to Unicode NFC, preserving letters, combining marks, numbers, whitespace, and ordinary punctuation.
  - Recommended removal policy: remove emoji grapheme sequences using pinned Unicode emoji data, including their variation selectors, skin-tone modifiers, and joiners; remove remaining Unicode `So`/`Sk` symbol characters and unprintable controls; preserve currency (`Sc`) and mathematical (`Sm`) symbols because they can carry meaning in answers.
  - Preserve language-relevant text, including Arabic marks and zero-width joiners/non-joiners when they are not part of an emoji sequence. Replace removed spans with one space, then trim and collapse whitespace.
  - Do not transliterate, translate, correct spelling, or perform language-dependent rewriting. Record removed code-point/grapheme counts and the cleanup-policy hash.
- `nonsemantic`
  - Configurable exact markers and regular expressions for refusals, don’t-know values, test entries, and administrative codes.
- `redaction`
  - Deterministic rules for emails, phone numbers, URLs, identifiers, and analyst-supplied patterns.
- `budget`
  - Hard per-run upper limit.
  - Include the worst-case eligible embedding calls, Gemini verifier/label/composite calls, retries, and the 20% retry reserve in the estimate. Never silently skip a required verifier call because the candidate count is large.
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
- `GEMINI_API_KEY` for direct Google generation.

Never serialize credentials into TOML, logs, manifests, workbooks, checkpoints, or caches.

Load these variables with `python-dotenv` and a small frozen standard-library `dataclass`. The loader must validate required keys without echoing values, and secret fields must use `repr=False` or an equivalent secret-safe representation so a settings object cannot print credentials. `uv run` supplies the environment to Python but does not itself make `.env` loading a provider contract. Add the dependency with `uv add python-dotenv` when implementation begins.

Provider setup checklist:

- Keep the existing `NEBIUS_API_KEY` in the local `.env`; do not print it or commit the file. `NEBIUS_AI_PROJECT_ID` is optional and should be added only if the authenticated Nebius model listing or inference request requires it.
- Add `GEMINI_API_KEY` to the same local `.env` after creating a Google AI Studio key and restricting it to the Gemini API where supported.
- Before a real run, list Nebius models with the authenticated account, inspect the verbose limits/pricing metadata, and record the exact model entry and timestamp in the profile.
- Run separate credential-gated smoke tests: Nebius embeddings with a synthetic multilingual fixture and direct Google structured JSON generation with a synthetic labeling request. Never use survey answers in smoke tests.

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
- `BilingualCategoryLabel`
- `Assignment`
- `ReviewRecord`
- `RunManifest`
- `Checkpoint`

All generative responses must be schema-constrained and locally validated. Invalid structured responses are retried; persistent item-level failures become unresolved records.

Ship explicit, editable profiles rather than hidden aliases. The Nebius profile must use `Qwen/Qwen3-Embedding-8B` for every eligible embedding input and record the fixed 2048-dimensional `float32` memmap representation, L2 normalization, and instruction policy. The Google profile must name direct `gemini-3.5-flash`, require bilingual English/Arabic category-label output, and pass its own structured-output smoke suite. Verify the exact Nebius model ID, account limits, pricing, and requested dimension against the live catalog and a live synthetic embedding before advertising the profile as supported. [Qwen3-Embedding-8B model card](https://huggingface.co/Qwen/Qwen3-Embedding-8B), [Nebius embeddings API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings), [Google Gemini models](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash), [Google structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en).

## Processing and Clustering Design

### 1. Validate and fingerprint

Before any semantic request:

- Parse the workbook with required fields treated as strings.
- Validate the complete input and TOML contracts.
- Hash the workbook content, normalized configuration, model profiles, exact prompts/instructions, deterministic cleanup and redaction rules, and package versions.
- Record `embedding_instruction_sha256` separately. The instruction is part of the vector-space contract: changing it invalidates compatible reuse of old embeddings even when the model ID is unchanged.
- Create a run ID and checkpoint directory.
- Verify both selected providers support their assigned capability using the configured model IDs, endpoint routes, output dimension, and JSON-schema behavior.
- Reject mutable model aliases and any provider-side automatic model routing.
- Build a conservative request and cost plan.
- Refuse execution if the upper-bound estimate exceeds the hard budget.

### 2. Classify, normalize, and deduplicate locally

For every input row:

- Preserve `answer_text` exactly.
- Assign blank and configured administrative/non-semantic values explicit statuses without sending them to AI.
- Create the analysis text by applying the pinned deterministic cleanup policy: Unicode normalization, emoji/non-text-symbol removal, and whitespace cleanup. Preserve spelling errors and the original script; do not transliterate, translate, or silently rewrite content.
- If cleanup leaves no substantive text, classify the row as blank/non-semantic and do not embed it.
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
- Otherwise use Lingua in low-accuracy mode with a restricted language set containing the languages covered by the fixture plus `unknown`, and record the detected language and confidence. Run detection after deduplication on unique variants only.
- Treat low-confidence or unsupported local detection as metadata warnings only; do not skip or rewrite the answer.
- Redact emails, phones, URLs, configured ID patterns, and analyst-supplied patterns locally.
- Use stable placeholders such as `[EMAIL_1]` so equivalent redacted variants remain comparable.
- Apply the same deterministic redaction policy to the question text and existing-choice label/description/examples before any remote request; preserve their raw forms locally for the audit workbook.
- Every eligible redacted original proceeds to the embedding stage regardless of detected language. Blank and deterministic non-semantic rows remain intentionally excluded from semantic calls.
- Never send passthrough metadata or unredacted survey text to either selected provider.
- Explicitly document that deterministic redaction does not guarantee removal of names or unstructured locations.

Language detection is audit-only metadata and a sampling signal, not a routing or translation decision. Configure Lingua's low-accuracy mode with the fixture's supported languages plus `unknown`; record the selected mode and language set in the manifest. Detect only unique variants after deduplication. The v1 fixture and pilot must include Arabic, dialectal Arabic, English, French, and additional real languages, while preserving each answer in its supplied script. Latin-transliterated Arabic and deliberate code-switching are not required fixture cases. Preview must report unsupported and low-confidence detector results rather than treating the detector as authoritative. Optional language hints are the preferred override for very short answers. Paying for high-accuracy detection provides no benefit because this metadata is not used for routing. [Lingua language detector](https://pypi.org/project/lingua-language-detector/).

### 4. Generate original-language embeddings and match existing choices

- Embed every unique eligible analysis variant once using Nebius `Qwen/Qwen3-Embedding-8B` on the complete redacted original-language text. No translation, language-specific model, or runtime representation switch is allowed.
- Embed choice anchors in the same provider, model, dimension, normalization policy, and fixed instruction context. Preserve their supplied language; do not translate them.
- Use the fixed 2048-dimensional `float32` output, L2-normalize it, and write rows to a NumPy memory-mapped matrix rather than materializing the full matrix in RAM.
- Store the exact embedding dimension, dtype, storage format, instruction identifier and SHA-256, normalization policy, model ID, and memmap row mapping in each cache key and in the manifest.
- Build each anchor representation from the question text, choice label, optional description, and optional examples.
- Apply the vector gate to unique variants before calling Gemini. Batch independent structured judgments where the provider schema permits, verify only vector-qualified candidates, label only promoted clusters, and composite-review only screened answers. Never issue one Gemini call per raw answer row; if the configured budget or verification cap cannot cover a candidate, leave it explicitly unresolved/review-required instead of assigning it from the vector score alone.
- Do not application-truncate eligible answers or chunk them. A survey answer will never exceed 40,000 tokens; verify the full redacted text against the selected model's context limit and record source token counts. Never replace the answer with an LLM summary in v1.
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

- Reuse unique-variant embeddings and apply source-row frequency through bounded expansion as the only mechanism: replicate each variant `min(occurrence_count, expansion_cap)` times, with a default cap such as `20`. Record the cap in the manifest so duplicates cannot exhaust memory.
- Apply deterministic PCA to 50 dimensions, bounded by the sample size and original embedding dimension.
- Run HDBSCAN-style density clustering with fixed parameters and canonical input ordering: sort variants by `variant_id` before clustering. Determinism does not depend on an HDBSCAN seed.
- If PCA uses a randomized solver, its seed is fixed; prefer `svd_solver='full'` or ARPACK with the canonical ordering so no seed is needed at all.
- Default `min_cluster_size` to 3.
- Preserve HDBSCAN noise rather than forcing it into the nearest cluster.
- Require membership probability of at least `0.80` for an automatic new-category assignment.
- Preserve one- and two-answer meanings as rare candidates instead of collapsing them into a generic residual category.
- Order new clusters deterministically by expanded size and stable medoid identity, then assign run-local IDs such as `NEW-001`.
- If more than the configured 50 promoted new categories emerge, finish diagnostics and provisional output but mark category finalization as failed; do not merge unrelated clusters merely to satisfy the cap.

For every promoted cluster:

- Select frequent examples, medoids, boundary cases, and represented languages.
- Ask the configured LLM for two evidence-grounded parallel labels and short descriptions: English (`label_en`, `description_en`) and Arabic (`label_ar`, `description_ar`). Both must be generated by Gemini from the same redacted cluster evidence; Arabic must be native Arabic script, not Latin transliteration.
- Prohibit the model from introducing concepts absent from member answers.
- Treat these as bilingual category summaries, not translations of individual stored answers. Do not add a translation call or translated answer field.
- Require all four bilingual fields in the structured response and validate that neither language silently falls back to the other. A failed bilingual label request leaves the category proposed with an explicit labeling error.
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
  - `answer_id`, raw answer, normalized variant ID, language hint/detection/confidence, redacted original-language analysis text, cleanup/removal summary, status, primary category ID/type/label, confidence, composite flag, secondary suggestions, unresolved reason, review-sample flag, blank analyst-review columns, and all local passthrough metadata.
- `Unique Variants`
  - Variant ID, normalized form, row count, language information, cleanup/removal and redaction summaries, source token count, embedding model/dimension/dtype/instruction identifiers, memmap row, cache key, primary result, and confidence.
- `Categories`
  - Existing and new category IDs, type, generated English `label_en`/`description_en`, generated Arabic `label_ar`/`description_ar`, label-generation status, expanded answer count, unique-variant count, membership statistics, representative examples in original language, anchor relationship, and `proposed_for_review` status. Generated labels are bilingual evidence-grounded summaries, not translated answer fields. Existing choice text remains preserved as supplied and is not silently translated.
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
- Fixed parameters and canonical ordering rules, including `variant_id` sorting before clustering; PCA seed only when a randomized solver is used.
- Lingua detection mode and restricted language set, including `unknown`; detection-after-deduplication policy.
- Clustering `expansion_cap` and the bounded-expansion rule `min(occurrence_count, expansion_cap)`.
- Counts at every pipeline stage.
- Token/request usage, estimated cost, actual recorded cost, and budget.
- Redaction-rule hash and redaction counts, but no credentials.
- Original-language-only embedding policy, language distribution, detector warnings, embedding instruction identifier, and exact output dimension.
- Vector artifact path, shape, dtype, normalization, memmap row map, flush/checksum status, and instruction SHA-256.
- Thresholds, clustering parameters, quality metrics, and warnings.
- Cache paths and payload counts.
- Failure/circuit-breaker details.
- Resume compatibility information.

### Vector artifacts

- Store answer-variant and choice-anchor vectors in a single run-local NumPy memmap with shape `(vector_count, 2048)` and dtype `float32`.
- At 100,000 vector rows, the raw matrix is approximately 819.2 MB (781.25 MiB) before choice anchors, row maps, PCA/clustering buffers, and the operating system's working set; capacity planning must budget those additional costs.
- Keep a deterministic sidecar row map keyed by `variant_id` or `choice_id`; never infer row identity from workbook order after preprocessing.
- Flush and close the memmap before clustering or handoff, record its byte size and SHA-256, and verify the shape/dtype/normalization on resume.
- Run PCA and clustering from the memmap with bounded working memory (streamed statistics or incremental PCA where required); report peak resident memory and fail with a diagnostic if the configured ceiling is exceeded.
- The memmap is the canonical vector artifact. Provider payload caches remain separate replay/audit artifacts and must not contain a second full JSON copy of every vector.

### Cache and logs

Use a separated cache policy:

- Store complete redacted provider requests and responses as readable workspace files for generation and small diagnostic calls.
- For bulk embedding calls, store the redacted request, response metadata, vector row range, response checksum, and usage information; write the actual vectors only to the canonical `float32` memmap so they are not duplicated in large JSON payloads.
- Keep them indefinitely until `cache purge` is run.
- Never duplicate raw, unredacted answers in cache payloads, and never serialize bulk embedding vectors as a second full JSON matrix.
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
  - Use fixed parameters, canonical deterministic sorting, pinned models, exact parameters, stable embedding instructions and generation prompts, cached responses, and manifest hashes. Fix a seed only when PCA uses a randomized solver; prefer a deterministic full or ARPACK solver.
  - Surface unavoidable hosted-model variance instead of claiming byte-identical semantic results.

## Test and Acceptance Plan

### Automated tests

Use `uv run pytest` for all tests.

Unit coverage:

- Workbook and TOML schema validation.
- Required string-ID preservation, including leading zeroes.
- Pure-discovery and choices-sheet rules.
- Formula rejection in required fields.
- Unicode normalization and deterministic emoji/non-text-symbol removal without alteration of raw text or spelling.
- Deduplication and source-row remapping.
- Non-semantic marker classification.
- Deterministic redaction and placeholder stability.
- Language hint precedence and uncertain detection.
- Original-language embedding invariant, fixed Qwen model ID, 2048 dimension, `float32` dtype, L2 normalization, memmap row mapping, and instruction SHA-256.
- Full-answer embedding behavior, 40,000-token answer boundary, model-context validation, and no silent truncation or chunking.
- Cost estimation and zero-call budget rejection.
- Similarity/margin choice gates.
- HDBSCAN noise, rare candidate, and membership handling.
- Stable run-local category IDs.
- Category-cap failure without forced merging.
- Composite screening and structured verification.
- Circuit-breaker thresholds.
- Checkpoint/hash compatibility.
- Instruction changes invalidating embedding reuse, including cache-key and resume rejection.
- Memmap shape/dtype/checksum validation and confirmed vector-row recovery.
- Plaintext cache inspection and confirmed purge.
- Manifest completeness and secret exclusion.

Fixture integration scenarios:

- English-only question with obvious existing-choice matches.
- New coherent category absent from existing choices.
- Empty choices with explicit pure discovery.
- Mixed Arabic, dialectal Arabic, English, French, and additional-language answers that represent the same concept.
- Cross-language grouping using only original-language embeddings, with no translation fields or calls.
- Emoji and non-text symbols removed deterministically while Arabic letters/marks, other scripts, punctuation, and spelling errors remain usable.
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
- Mocked contract tests for the direct Google Gemini adapter are mandatory in the default suite, including the required English/Arabic label-and-description schema and native Arabic-script validation.
- Credential-gated live smoke tests must cover Nebius `Qwen/Qwen3-Embedding-8B` embeddings at the selected 2048 dimensions, the direct Google `gemini-3.5-flash` structured-generation route, bilingual JSON-schema behavior, pricing/preflight behavior, endpoint selection, and invalid-model rejection for each provider. A separate smoke comparison may exercise 4096 dimensions.
- Live tests are opt-in and must use tiny synthetic, non-sensitive fixtures.
- The v1 two-provider profile is usable only after both live smoke suites pass.

### Pilot acceptance

Prepare a manually labeled, seeded, stratified evaluation fixture before the pilot. The fixture should contain roughly 20–30 semantic intents, 3–5 variants per intent, Arabic and dialectal Arabic, English, French, and additional real languages, spelling errors, short answers, refusals/blanks, and existing-choice plus new-category cases. Labels must be assigned by bilingual or language-competent reviewers; do not create the gold set by translating the answers automatically.

Report only these metrics overall and by language where applicable:

- **Review-sample assignment correctness:** at least 90%.
- **Category coherence:** at least 85%.
- **Exactly-one-output traceability:** every `answer_id` appears in exactly one output assignment/status.
- **Coverage and unresolved rate:** report side by side, with denominators and exclusions.
- **Per-language coverage and unresolved rate:** required because multilingual behavior is the core risk.
- **Bilingual-label checks:** English/Arabic field completeness and Arabic-script validity.

Export the metric definitions, denominators, exclusions, confidence intervals where meaningful, and per-stratum sample sizes in the manifest and Summary sheet. Do not hide low coverage behind correctness or coherence; always display coverage and unresolved rate side by side.

V1 passes its practical pilot when:

- At least 90% of sampled automatically assigned rows are judged correctly assigned.
- At least 85% of sampled promoted categories are judged internally coherent.
- Coverage and unresolved rate are always reported side by side overall and per language.
- Every input `answer_id` is traceable to exactly one output assignment/status.
- No structural error, blank, excluded marker, provider failure, or unresolved answer is silently omitted.
- The measured assignment coverage and unresolved rate are reported separately and are not manipulated by forcing low-confidence answers.
- Both Nebius embedding and direct Google generation profiles pass their credential-gated live smoke suites before being advertised as supported.

## Assumptions and Explicitly Deferred Scope

- The prepared workbook contains exactly one question per run.
- Survey extraction and detection of `Other` fields are out of scope.
- Source question mode is irrelevant to v1 clustering.
- Every answer receives one primary category at most; secondary suggestions are advisory.
- Existing-choice assignments are automatic only under conservative vector and LLM agreement.
- New categories are proposals requiring analyst review.
- Generated labels and descriptions are bilingual, evidence-grounded summaries: Gemini must provide both English and Arabic fields. They are not translated answer fields; existing choice text remains supplied text.
- No translation is performed anywhere in v1. All eligible semantic inputs remain in their supplied/original language for embedding and evidence review.
- Original answer text remains the primary evidence and is always preserved locally.
- Input and output may contain raw sensitive text; every selected remote provider receives only deterministically redacted text and no passthrough metadata.
- Deterministic redaction does not guarantee removal of names or informal locations.
- The user accepts persistent plaintext caching of redacted hosted request/response payloads, with bulk embedding vectors stored only in the memmap and their cache entries retaining metadata/checksums rather than a second JSON vector copy.
- Persistent category registries, cross-wave ID reconciliation, analyst-feedback ingestion, category merging through an editing workflow, official codebook mutation, translation, additional hosted-provider adapters beyond the selected v1 provider set, local-model execution, web UI, survey-platform integration, and survey write-back are deferred.
- The initial runtime baseline is the currently configured local environment: Python 3.13 and `uv` 0.6.14.

## Remaining Operational Prerequisites and Decisions

The core v1 strategy is now locked: Nebius embeddings with `Qwen/Qwen3-Embedding-8B`, 2048-dimensional `float32` memmap vectors, one fixed instruction, no translation, deterministic eligibility/cleanup, complete-answer embedding without truncation or chunking because answers are bounded at 40,000 tokens, and direct Google `gemini-3.5-flash` generation with bilingual English/Arabic category labels and descriptions. The remaining items are operational prerequisites or implementation details:

- **Nebius live catalog and account contract:** the account check on 2026-07-14 found `Qwen/Qwen3-Embedding-8B` with a 40,960-token context, 600,000 tokens/minute, and 10,000 requests/minute; synthetic embedding calls accepted both `dimensions=2048` and `dimensions=4096` and returned the requested lengths. V1 selects 2048; 4096 remains an evaluation alternative. Recheck limits and pricing during implementation/preflight because they can change, and keep `NEBIUS_AI_PROJECT_ID` optional unless the account requires it.
- **Google credential:** create a Gemini API key, restrict it to the Gemini API where the account supports key restrictions, add `GEMINI_API_KEY` to the local `.env`, and run a tiny direct `gemini-3.5-flash` structured-output smoke test with synthetic data. The current `.env` contains `NEBIUS_API_KEY`; it does not yet contain the Google key.
- **Provider privacy/data handling:** this is a learning project, so provider-retention and production access-control review is deferred. Deterministic redaction and secret exclusion still apply.
- **Capacity and pricing:** populate live pricing and limits in the profile later. The current starting recommendation remains synchronous embedding batches of 32–64 and concurrency `2`, with exponential backoff, `Retry-After`/rate-limit handling, and a 20% retry reserve; defer a batch/offline API until correctness and resume behavior are proven.
- **Deterministic symbol policy:** use the recommended NFC/emoji/`So`/`Sk` cleanup policy in the normalization section, pin the exact Unicode/emoji data, and test Arabic marks, other scripts, punctuation, numbers, misspellings, currency/math symbols, and symbol-only answers. This is an implementation contract, not a language-routing decision.
- **Evaluation fixture:** create the multilingual gold set before tuning thresholds. Recommended coverage is Arabic/MSA and dialectal Arabic, English, French, Spanish or Turkish, Urdu or Persian, and one additional non-Latin script, with 20–30 intents and 3–5 human-labeled variants per intent. Add more languages as real project data permits; do not manufacture quality by auto-translating the gold answers.
- **Generated-label language:** resolved to bilingual LLM-generated English and Arabic labels/descriptions with native Arabic script; no translated answer fields or translation calls are added.
- **Cache retention:** the 2048-dimensional memmap is the canonical vector store. The redacted request/response cache remains until an explicit manual purge; there is no automatic expiry. Additional production access controls can be revisited later because this v1 is for learning purposes.
- **Python runtime alignment:** the project is aligned on Python 3.13 through `.python-version` and `pyproject.toml`; record the exact runtime and `uv` version in the manifest when implementation begins.
