# Provider Token Counting and Billing Research

**Research snapshot:** 2026-07-16

**Scope:** the v1 profiles only: Nebius Token Factory `Qwen/Qwen3-Embedding-8B` for embeddings and the direct Google Gemini API `gemini-3.5-flash` for structured generation.

This document records the provider evidence needed by Spec 05. A provider fact is marked as `documented`, `not documented`, or `project policy`; the latter must not be presented as a provider guarantee.

## Decision summary

| Profile | Authoritative input-count method | Pricing snapshot | Hard-budget status |
| --- | --- | --- | --- |
| Nebius embeddings | Successful `/v1/embeddings` response `usage.prompt_tokens`; no standalone preflight counter was found in the official API reference | Authenticated verbose model catalog/organization price catalog is required; no public model-specific numeric price was exposed in the reviewed official pages | Blocked until the authenticated model-price snapshot and billing outcome policy are captured |
| Google Gemini generation | Authenticated `POST .../{model}:countTokens` over the complete serialized `GenerateContentRequest`; validate actual usage from the generation response | Google pricing page, Standard paid tier, retrieved 2026-07-16 and last updated 2026-07-09 UTC | Counting and published Standard pricing are documented; implementation still uses the residual blockers below before claiming a trusted hard-budget calculation |

The research gate is therefore documented, but the hard-budget calculation is not implementation-ready. The main unresolved item is not a missing prose assumption: Nebius's public documentation does not provide the selected model's numeric price or an explicit failed-request billing rule. Those values must come from the authenticated account/catalog and be fingerprinted before a paid run can be approved.

## Nebius Token Factory: embedding profile

### Counting, authentication, limits, and billing

- **Endpoint and method:** `POST https://api.tokenfactory.nebius.com/v1/embeddings`. The request requires a model and input. The documented response includes `usage.prompt_tokens` and `usage.total_tokens`; for embeddings the example shows both as the same aggregate count. This response field is the v1 authoritative count after a request succeeds. Source: [Create embeddings](https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings).
- **Standalone counter:** no separate Nebius embedding token-count endpoint was found in the official API reference or documentation index reviewed on 2026-07-16. Preflight therefore cannot use a provider-authoritative counter for a request that has not yet been sent.
- **Authentication:** the embeddings endpoint requires `Authorization: Bearer <token>`. `NEBIUS_API_KEY` and optional `NEBIUS_AI_PROJECT_ID` remain separate profile inputs; credentials are never fingerprinted. Source: [Create embeddings](https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings).
- **Rate limits:** Nebius documents dynamic request-per-minute and token-per-minute limits, evaluated in rolling 15-minute windows. Current limits must be read from response headers, including `x-ratelimit-limit-requests`, `x-ratelimit-limit-tokens`, remaining/reset headers, and `Retry-After`; a limit breach returns HTTP 429. The plan must not hardcode an old account limit. Source: [Rate limits and scaling](https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits).
- **Count-call billing:** there is no standalone count call. The embedding request is a real provider operation and its returned usage must be treated as potentially billable. Nebius documents mandatory billing setup and usage monitoring, but the reviewed public billing page does not state a model-specific price or a separate rule making usage accounting free. Source: [Billing and consumption](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new).

### Model/tokenizer version

- **Model identifier:** exact profile value `Qwen/Qwen3-Embedding-8B`; do not replace it with a mutable alias.
- **Model version:** the model ID is the only stable version identifier exposed by the reviewed public embedding contract. At live preflight, record the model ID returned by the provider and the relevant authenticated [`GET /v1/models?verbose=true`](https://docs.tokenfactory.nebius.com/api-reference/models/list-models) metadata, including any model price, limit, context, or revision fields when available.
- **Tokenizer version:** the reviewed public Nebius pages do not expose a separate tokenizer revision. Record `tokenizer_version = provider-managed-undisclosed` unless the authenticated model catalog returns a concrete revision. Do not infer a Hugging Face tokenizer revision from the model name.
- **Fingerprint consequence:** `model_id`, `model_catalog_snapshot`, `tokenizer_version`, `token_count_source`, and `token_count_source_version` are required profile fields. An undisclosed tokenizer version is an explicit value, not an omitted field.

### Batching

The documented `input` schema includes string and array forms, and the response is a list of embeddings with indices plus aggregate `usage` fields. It does not document a separate per-item token-count endpoint or a separate batch pricing formula. The adapter must:

1. Canonicalize the exact input list and batch request body before sending it.
2. Treat one POST as one request record and map response indices to the canonical input order.
3. Use the response aggregate `usage.prompt_tokens` as the authoritative total for that POST.
4. Preserve per-item fallback estimates in the request plan, but never pretend they are provider-returned per-item counts.
5. Confirm the accepted array-of-strings form with a synthetic contract test before enabling multi-item batches; the public prose describes arrays of tokens but does not fully explain the batch semantics.

The selected v1 batch policy remains synchronous batches of approximately 32–64 texts with low initial concurrency, but the actual batch size, concurrency, and observed rate-limit headers are manifest fields.

### Structured output, failed requests, and retries

- **Structured output in v1:** not applicable to the selected Nebius profile. V1 uses Nebius only for embeddings; generation and JSON-schema labeling use Google.
- **Nebius text-generation capability:** Nebius documents JSON Schema following through `response_format` for text models. The public pricing/UI documentation distinguishes input-token and output-token prices in USD per million tokens but lists no separate structured-output tariff. Therefore, if a future Nebius generation profile is introduced, its prompt/system/schema/tool material is treated as input tokens and generated JSON is treated as output tokens at that model's normal rates. This is an explicit inference from the general input/output pricing fields, not a v1 billing entitlement. Sources: [Structured output and JSON](https://docs.tokenfactory.nebius.com/ai-models-inference/json) and [UI and Playground](https://docs.tokenfactory.nebius.com/ai-models-inference/playground).
- **Failed requests:** the reviewed public Nebius billing documentation does not say whether failed, timed-out, rate-limited, or malformed embedding requests consume billable tokens.
- **Retries:** a successful retry is a new provider request and must be included in the conservative attempt bound. For a failed attempt, the plan records `billing_status = unknown` unless an authenticated Nebius billing contract or usage export proves otherwise. The estimate reserves the full possible input charge for every attempt; it never assumes that a failed attempt is free.

### Pricing

Nebius model cards describe input and output prices in USD per million tokens, and the authenticated verbose model-list route can expose richer model metadata. The reviewed public pages still do not expose a numeric price for `Qwen/Qwen3-Embedding-8B`; the organization price catalog/model response must be captured for the selected account and model. The public billing page documents account funding/usage monitoring and shows invoices/tax lines in USD.

Required profile fields:

| Field | Current documented value | Required before hard-budget approval |
| --- | --- | --- |
| `pricing_unit` | `per_1m_tokens` (model-card display) | Confirm the exact catalog unit and whether the selected embedding price is input-only |
| `pricing_currency` | `USD` for the billing/invoice snapshot | Capture the catalog currency with the price record |
| `pricing_source` | [Organization prices](https://tokenfactory.nebius.com/organization/prices) plus authenticated [`GET /v1/models?verbose=true`](https://docs.tokenfactory.nebius.com/api-reference/models/list-models) | Save the authenticated catalog/model-response source identifier and URL |
| `pricing_publication_date` | Not exposed in the public page reviewed | Capture the catalog effective/publication timestamp |
| `pricing_retrieved_at` | `2026-07-16` | Store the actual authenticated retrieval timestamp |
| `pricing_version` | `nebius-org-price-catalog-snapshot` (placeholder ID only) | Replace with a content hash or provider version/effective date |
| `input_price` | Unknown; do not use zero | Record the selected model's numeric price |

No numeric Nebius price is invented in this plan. Until the authenticated snapshot exists, `estimate` may produce a provisional, clearly labeled token plan but cannot authorize a paid hard-budget run.

### Fallback estimate

When the official usage counter is unavailable before a call, the provisional tokenizer-free estimate is:

```text
estimated_input_tokens = max(1, ceil(len(canonical_request_utf8_bytes) / 2))
```

The estimate is calculated over the exact canonical serialized request, including JSON delimiters, model-independent fixed text, separators, redacted content, and every item in the batch. This is intentionally conservative for the v1 Arabic/English scope, but it is not a tokenizer implementation and does not unlock hard-budget approval. Every live response replaces the estimate with `usage.prompt_tokens` and records the difference.

## Google Gemini API: structured-generation profile

### Counting, authentication, limits, and billing

- **Endpoint and method:** `POST https://generativelanguage.googleapis.com/v1beta/{model=models/*}:countTokens`, using the selected model resource name. The request may send `contents[]` or the full `generateContentRequest`; the latter includes the prompt plus steering information such as system instructions and function declarations. The project must use the full canonical `GenerateContentRequest` so the count includes the actual system instruction, JSON schema/configuration, and any tools. Source: [Counting tokens API reference](https://ai.google.dev/api/tokens).
- **Authentication:** use `x-goog-api-key` or the documented API-key query form. The API key is required at runtime and never enters a fingerprint.
- **Count-call billing:** Google states that `GetTokens`/`countTokens` requests are not billed and do not count against inference quota. Source: [Gemini billing](https://ai.google.dev/gemini-api/docs/billing).
- **Rate limits:** the Google rate-limit page documents project-level RPM, input TPM, RPD, and possible spend-based limits for model inference. It does not publish a separate `countTokens` RPM in the reviewed material. The adapter must still handle authentication errors, service throttling, and HTTP 429 with bounded retries; the count call's no-billing/no-inference-quota statement must not be generalized to `generateContent`.
- **Generation billing:** input tokens, output tokens, cached tokens, and cached-storage duration are billable dimensions. For this project, the selected Standard paid tier uses input and output token rates; context caching is not part of the v1 request plan unless explicitly enabled. Source: [Gemini billing](https://ai.google.dev/gemini-api/docs/billing) and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

### Model/tokenizer version

- **Model identifier:** exact stable profile value `gemini-3.5-flash`.
- **Provider-published limits:** input limit `1,048,576`; provider maximum output limit `65,536`. Source: [Gemini 3.5 Flash model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash).
- **Tokenizer version:** Google does not expose a separate tokenizer revision in the reviewed API/model/pricing pages. The official `countTokens` result for the exact model is authoritative. Record `tokenizer_version = provider-managed-undisclosed` unless a future official model response exposes a concrete tokenizer revision.
- **Fingerprint consequence:** `model_id`, `model_page_last_updated`, `tokenizer_version`, `count_tokens_endpoint`, `count_tokens_request_shape`, and `count_tokens_api_version` are required profile fields.

### Batching

The `countTokens` endpoint counts one `contents[]` or one complete `GenerateContentRequest` per call; it is not a multi-request counter. If the application uses Gemini Batch API, each inline request or each JSONL line is a complete `GenerateContentRequest`, so the local planner counts each member separately and sums the results. It must not count only the outer batch envelope. Google documents inline requests and JSONL input, and prices Batch API at 50% of the equivalent interactive cost. Sources: [Counting tokens API reference](https://ai.google.dev/api/tokens), [Gemini Batch API](https://ai.google.dev/gemini-api/docs/batch-api), and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

V1 selects direct interactive `generateContent`, not Gemini Batch API. Batch pricing remains documented as an explicit alternative profile rather than silently applied to direct calls.

### Structured-output billing

Google structured output is JSON Schema constrained generation. The schema/configuration is part of the canonical generation request and is counted as input; generated JSON is output. There is no separate structured-output token price in the pricing table, so the request uses the selected model's normal input price and normal output price, with thinking tokens included in the output price. This is a billing interpretation from the structured-output request contract plus the general input/output pricing rules; it is not a claim that JSON syntax has a separate tariff. Sources: [Structured outputs](https://ai.google.dev/gemini-api/docs/structured-output), [Gemini billing](https://ai.google.dev/gemini-api/docs/billing), and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

### Conservative output limits by operation

These are application safety caps, not Google's model maximum. They are deliberately much lower than the provider maximum and are fingerprinted as profile fields:

| Operation | Output contract | `max_output_tokens` cap | Budget treatment |
| --- | --- | ---: | --- |
| Existing-choice verifier | One structured verdict, confidence, and short evidence | `256` | Reserve 256 output tokens per attempted verifier call |
| Promoted-cluster bilingual labeler | `label_en`, `description_en`, `label_ar`, `description_ar` | `512` | Reserve 512 output tokens per attempted label call |
| Composite reviewer | Primary plus up to two advisory secondary choices, verdict, and evidence | `512` | Reserve 512 output tokens per attempted composite call |

The adapter must set these caps explicitly, reject a profile that omits them, and record actual output/thinking token usage when returned. If a future schema requires more output, that is a profile change and a new budget/pricing fingerprint.

### Failed requests and retries

Google explicitly states that requests failing with HTTP 400 or 500 are not charged for tokens used, although they still count against quota. The reviewed billing page does not state an equivalent no-charge rule for 429, transport timeout, connection reset, or other failures. A successful retry is a new generation request and is charged according to its actual usage. Source: [Gemini billing](https://ai.google.dev/gemini-api/docs/billing).

The conservative planner therefore prices every possible generation attempt at its full input plus operation output cap. Actual usage replaces the estimate after a response. For failed calls, the manifest records HTTP class, retry ordinal, usage if present, and `billing_status`; only documented 400/500 failures may be recorded as `not_charged`, while other failures remain `unknown` unless the provider response/account record proves otherwise.

### Pricing snapshot

The selected Google profile is the Standard paid tier for direct interactive calls:

| Field | Value |
| --- | --- |
| `pricing_unit` | Per 1,000,000 tokens |
| `pricing_currency` | USD |
| `input_price` | `$1.50` per 1M input tokens |
| `output_price` | `$9.00` per 1M output tokens, including thinking tokens |
| `cached_input_price` | `$0.15` per 1M cached tokens, if caching is enabled in a future profile |
| `pricing_source` | [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `pricing_publication_date` | Page last updated `2026-07-09 UTC` |
| `pricing_retrieved_at` | `2026-07-16` |
| `pricing_version` | `google-gemini-pricing-2026-07-09-standard` |

The same pricing page lists Batch input `$0.75` and output `$4.50` per 1M tokens for this model; that is a separate `batch` pricing profile and is not used for v1 direct generation. Google documents Batch as 50% of standard interactive cost.

### Fallback estimate

If `countTokens` is unavailable, use the same tokenizer-free provisional fallback as Nebius over the complete canonical request:

```text
estimated_input_tokens = max(1, ceil(len(canonical_generate_content_request_utf8_bytes) / 2))
```

The estimate includes system instructions, JSON schema, tools, messages, separators, and serialized configuration. It does not estimate output from character length; output is conservatively bounded by the operation cap above. A fallback-estimated Google request must remain visibly provisional and must not be used to claim implementation-ready hard-budget enforcement unless the project explicitly accepts that risk in a later decision.

## Fingerprinted profile fields

Spec 05 and the run manifest must retain these non-secret fields for every provider profile:

```text
provider_id
role
endpoint
model_id
model_catalog_snapshot
model_page_last_updated
tokenizer_version
token_count_method_id
token_count_source
token_count_endpoint
token_count_request_shape
token_count_api_version
batch_counting_policy
structured_output_billing_policy
failure_billing_policy
retry_billing_policy
pricing_unit
pricing_currency
pricing_input_rate
pricing_output_rate
pricing_cache_rate
pricing_publication_date
pricing_effective_at
pricing_source
pricing_version
pricing_retrieved_at
fallback_estimator_id
fallback_estimator_formula
operation_output_token_limits
```

`token_count_method_id`, `pricing_version`, `pricing_retrieved_at`, and the exact serialized-request policy are fingerprint inputs. A change in any of them invalidates the cost-plan fingerprint even if the workbook and prompts are unchanged.

## Source register and publication dates

The Google Developer pages expose explicit last-updated dates. The Nebius documentation pages reviewed here expose no publication/update date in their page content; `2026-07-16` is therefore recorded as the research retrieval date, not misrepresented as a provider publication date. The authenticated Nebius price/model response must carry its own effective/publication timestamp when captured.

| Provider source | Used for | Provider publication/update date exposed | Research retrieval |
| --- | --- | --- | --- |
| [Google Counting tokens API](https://ai.google.dev/api/tokens) | `countTokens` endpoint, request shape, full-request inputs | Last updated `2026-04-24 UTC` | `2026-07-16` |
| [Google token guide](https://ai.google.dev/gemini-api/docs/tokens) | chat/history, multimodal, system/tool, and usage interpretation | Last updated `2026-07-06 UTC` | `2026-07-16` |
| [Google Gemini 3.5 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash) | model ID and provider input/output limits | Last updated `2026-06-24 UTC` | `2026-07-16` |
| [Google pricing](https://ai.google.dev/gemini-api/docs/pricing) | Standard and Batch rates, unit, currency | Last updated `2026-07-09 UTC` | `2026-07-16` |
| [Google billing](https://ai.google.dev/gemini-api/docs/billing) | count-call billing and 400/500 failure billing | Date not exposed in reviewed page content | `2026-07-16` |
| [Google Batch API](https://ai.google.dev/gemini-api/docs/batch-api) | inline/JSONL batch counting and 50% pricing | Last updated `2026-07-02 UTC` | `2026-07-16` |
| [Google structured outputs](https://ai.google.dev/gemini-api/docs/structured-output) | JSON Schema request/response contract | Last updated `2026-07-07 UTC` | `2026-07-16` |
| [Nebius create embeddings](https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings) | endpoint, auth, input schema, usage fields | Not exposed in reviewed page content | `2026-07-16` |
| [Nebius list models](https://docs.tokenfactory.nebius.com/api-reference/models/list-models) | authenticated model/verbose metadata source | Not exposed in reviewed page content | `2026-07-16` |
| [Nebius rate limits](https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits) | dynamic RPM/TPM and response headers | Not exposed in reviewed page content | `2026-07-16` |
| [Nebius billing](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new) | billing setup, usage monitoring, USD invoice context | Not exposed in reviewed page content | `2026-07-16` |
| [Nebius structured output](https://docs.tokenfactory.nebius.com/ai-models-inference/json) | future text-model JSON Schema capability | Not exposed in reviewed page content | `2026-07-16` |
| [Nebius UI and Playground](https://docs.tokenfactory.nebius.com/ai-models-inference/playground) | model-card pricing unit/currency display | Not exposed in reviewed page content | `2026-07-16` |

## Readiness gate after this research

The plan may implement local request planning, fingerprinting, provisional estimates, and usage reconciliation now. It must not yet advertise the hard-budget calculation as trusted or implementation-ready until all of the following are captured:

1. An authenticated Nebius price-catalog snapshot for `Qwen/Qwen3-Embedding-8B`, including numeric rate, exact unit, currency, and effective/publication timestamp.
2. A documented Nebius account/billing answer for failed, timed-out, 429, and retried embedding requests, or an explicit accepted policy that treats all unknown failures as potentially billable.
3. A live Nebius model-catalog/capability response confirming the exact model, requested 4096 dimensions, and the accepted multi-item input form.
4. A synthetic Google `countTokens` versus `generateContent` fixture confirming that the exact canonical structured request produces the expected usage fields, including schema/configuration handling.
5. An explicit project decision to use the documented tokenizer fallback for any counter outage, with the fallback and its conservative safety rationale retained in the fingerprint.
