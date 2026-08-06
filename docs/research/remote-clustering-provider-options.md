# Remote clustering provider options

## Dataset and cost basis

The frozen uncoded WFP workbook contains 1,767 canonical answers, 71,865 answer
characters, and 13,412 whitespace-delimited words. The selected production
policy embeds an instruction-aware form of every answer in a clusterable
question and an answer-only form for the `2-20` and `51-100` answer bands.
Provider tokenization varies, especially for Arabic, so costs below use a
conservative ceiling of 250,000 input tokens per complete embedding replay.

## Current options

| Provider/model | Relevant capability | List-price ceiling for this run | Practical finding |
| --- | --- | ---: | --- |
| Nebius `Qwen/Qwen3-Embedding-8B` | 4,096-dimensional, multilingual, instruction-aware Qwen3 embedding | Confirm in the Nebius dashboard; the public self-service price is dynamically rendered | Selected because the configured key and cache produced the best measured result |
| Google `gemini-embedding-001` | Explicit `CLUSTERING` task type; 128-3,072 dimensions | about $0.04 at $0.15/M tokens | Configured key was on the free tier, but its 100-input/minute quota made a full interactive sweep impractical |
| Google `gemini-embedding-2` | Newer multilingual/multimodal embedding; prompt-based task instruction | about $0.05 at $0.20/M tokens | Strong next comparison when paid throughput is enabled |
| OpenAI `text-embedding-3-small` | General embedding explicitly documented for clustering | about $0.005 at $0.02/M tokens | Cheapest paid comparison |
| OpenAI `text-embedding-3-large` | Larger general embedding | about $0.033 at $0.13/M tokens | Higher-quality OpenAI comparison |
| Voyage `voyage-4-large` | Current general-purpose multilingual embedding | $0 under the published 200M-token free allowance; then about $0.03 at $0.12/M | Attractive next independent comparison |
| Cohere `embed-v4.0` / `embed-multilingual-v3.0` | Multilingual classification and embedding | Trial keys are free but limited; verify production price in the Cohere pricing page | Viable, but lower priority without a configured key |

## Primary sources

- [Qwen3 Embedding repository](https://github.com/QwenLM/Qwen3-Embedding) documents
  the 8B model's 4,096 dimensions, multilingual support, instruction awareness,
  and reported 1-5% task-instruction gains.
- [Nebius embedding API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-embeddings)
  documents the OpenAI-compatible endpoint and usage reporting; the
  [Nebius product page](https://nebius.com/services/token-factory/text-to-image)
  lists Qwen3-Embedding-8B and describes zero-retention mode.
- [Gemini embeddings documentation](https://ai.google.dev/gemini-api/docs/embeddings)
  documents clustering task types, dimensions, and current models; the
  [Gemini pricing page](https://ai.google.dev/gemini-api/docs/pricing) lists
  embedding token prices and free/paid data-use differences.
- [OpenAI text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
  lists the current small and large embedding prices and clustering use case.
- [Voyage pricing](https://docs.voyageai.com/docs/pricing) lists per-token prices
  and free allowances; [Voyage embedding models](https://docs.voyageai.com/docs/embeddings)
  describes Voyage 4 as general-purpose and multilingual.
- [Cohere embed models](https://docs.cohere.com/docs/cohere-embed) documents the
  multilingual models; [Cohere pricing behavior](https://docs.cohere.com/docs/how-does-cohere-pricing-work)
  documents free but limited trial usage.

## Recommendation

Ship the measured Qwen3 policy with its transactional exact-input cache. For a
future independent provider check, test Voyage 4 Large first because its
published free allowance covers this workload, followed by Gemini Embedding 2
with paid throughput. Keep provider vectors behind the same validated cache
boundary so a comparison changes representation, not ingestion, scoring, or
review behavior.
