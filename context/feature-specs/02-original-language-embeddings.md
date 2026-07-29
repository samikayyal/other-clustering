# Feature 02: Original-Language Embeddings

## Objective

Create validated Nebius vectors for every distinct exact question/answer text
without translating or normalizing away original-language content.

## Fixed provider contract

- endpoint: `POST https://api.tokenfactory.nebius.com/v1/embeddings`;
- key: `NEBIUS_API_KEY` from the process environment or optional `.env`;
- model: `Qwen/Qwen3-Embedding-8B`;
- request batches: at most 32 exact answer strings;
- dimensions: 4096, `encoding_format: "float"`;
- timeout: 120 seconds; no application retries; and
- no instruction or prefix is added to answers.

The response indices must uniquely and exactly cover the requested batch. Each
vector must contain 4096 finite numeric values and, after conversion to
`float32`, have an L2 norm approximately equal to 1.0 with `rtol=1e-5` and
`atol=1e-6`. Provider values are never application-renormalized.

## Deduplication and cache

Exact text is processed once per question. The active process keeps a fresh
`float32` array and aligned in-memory row map containing the processing ID,
question, exact text, all answer IDs, respondent keys, and source locations.
No vector run artifact or serialized row map is written.

Valid compatible vectors are reused from `embedding_cache/cache.sqlite3` using
the existing schema and complete typed identity. Cache rows are revalidated for
size, dimensions, finite values, and norm on read. A missing key is fatal only
when an uncached answer requires a provider request; an empty or fully cached
dataset succeeds without `NEBIUS_API_KEY`.

## Failure boundary

Missing/duplicate response indices, malformed vectors, cache corruption,
network errors, timeout, non-success response, or invalid vector norms are
fatal. The workbook remains untouched and no incomplete review file is
published.
