# Spec 04 — Provider Contracts and Adapters

**Status:** Planned
**Dependencies:** Spec 01, Spec 02, Spec 03
**Implementation order:** 04 of 11

## Outcome

The application has provider-neutral semantic interfaces and two explicit direct HTTP adapters: Nebius for embeddings and Google Gemini for structured generation. Vendor payloads are translated into typed domain records, secrets stay outside requests/logs/artifacts except where required in HTTP authentication, and mocked contract tests protect the boundary.

## Provider interface

Define a `SemanticProvider` protocol with:

- `healthcheck(profile) -> CapabilityReport`;
- `embed(texts, profile) -> EmbeddingBatch`;
- `generate_structured(operation, payload, schema, profile) -> StructuredBatch`.

Cost estimation is a local planning operation owned by the run-planning layer; it does not call a provider. The provider interface must expose provider/model identity, endpoint capability, request/response usage, token-count source, tokenizer-version status, pricing-profile identifier, retry/billing outcome, and safe error categories without exposing raw vendor JSON to clustering or pipeline code.

## Nebius adapter

- Use the direct Nebius Token Factory embeddings route and explicit base URL/endpoint policy from configuration.
- Accept only the exact `Qwen/Qwen3-Embedding-8B` profile for v1.
- Request 4096 dimensions, validate returned length, convert to `float32`, and L2-normalize in the application before memmap persistence.
- Support synchronous batches of roughly 32–64 with initial low concurrency of 2; make limits configurable and record them in the manifest.
- Handle timeouts, transient HTTP errors, rate limits, `Retry-After`, malformed payloads, and usage/pricing metadata through bounded retry policy.
- Return Nebius aggregate `usage.prompt_tokens` after successful embedding calls and return Google count-token results plus generation input/output/thinking usage; never treat the provisional fallback as provider usage.
- Preserve `billing_status` per attempt. Google 400/500 failures are documented as not charged; other failure classes and Nebius failed-request billing remain unknown until the profile's documented/account evidence says otherwise.
- Never use the embedding model for generation.

## Direct Google Gemini adapter

- Use the direct Google Gemini API `generateContent` route, not a Nebius-hosted or OpenAI-compatible proxy.
- Accept only the explicit `gemini-3.5-flash` generation profile for v1.
- Request structured JSON for existing-choice verification, category labeling, and composite verification.
- Validate the category-label schema fields `label_en`, `description_en`, `label_ar`, and `description_ar`; require native Arabic script in Arabic fields and reject silent language fallback.
- Expose operation-specific payloads and structured results rather than a generic untyped generation response.
- Require explicit `thinking_mode` and `thinking_budget_tokens` profile fields and set them on every generation request; reject a profile that omits them, never fall back to the provider-default thinking behavior, and flag unexpected nonzero thinking usage as a contract violation under the pinned thinking-disabled policy (see `context/provider-token-billing.md`).
- Keep generation calls bounded by the configured verification/label/composite budgets; never issue one generation call per raw answer row.

## Shared transport and safety rules

- Use `httpx` with explicit timeouts and a bounded retry policy.
- Load `NEBIUS_API_KEY`, optional `NEBIUS_AI_PROJECT_ID`, and `GEMINI_API_KEY` independently from environment settings.
- Provider payloads may include only redacted question/choice/answer/cluster evidence required for the operation. Do not include local passthrough metadata or unredacted text.
- Do not log authorization headers, credentials, raw unredacted text, or full sensitive payloads.
- Record provider, model, route, request checksum, response checksum/usage, retry count, and safe error category in `ProviderRequestRecord`.
- Reject mutable aliases and provider-side automatic model routing during capability checks.

## Tests

### Mocked and live tests

Default mocked contract tests must cover:

- Nebius request shape, model ID, dimension parameter, batch mapping, response length, normalization, rate-limit/retry behavior, malformed response handling, and invalid-model rejection.
- Google endpoint selection, model ID, structured schema, native Arabic-script validation, retry behavior, malformed JSON, and invalid-model rejection.
- Credential absence without secret leakage.
- Provider-neutral conversion into typed results.

Opt-in live smoke tests must use tiny synthetic, non-sensitive fixtures and separately cover Nebius embeddings at 4096 dimensions and direct Google bilingual structured generation. A separate lower-dimensional Nebius comparison is optional and never changes the v1 storage contract. Both live suites must pass before the v1 provider profiles are advertised as supported.

## Acceptance criteria

- Pipeline code can depend on `SemanticProvider` and typed results without importing vendor response classes or dictionaries.
- Nebius and Google routes remain separate in code, configuration, credentials, logs, and manifests.
- Mocked provider tests run offline through `uv run pytest`.
- Invalid provider responses become typed retry/error outcomes; they cannot silently become successful semantic decisions.
- Live smoke tests are opt-in, synthetic, and explicitly report whether each profile is supported.

## Non-goals

- Embedding instruction construction, memmap storage, similarity gates, clustering, final assignments, or run orchestration.
- Translation, fallback to other providers, local inference, or automatic provider/model selection.
