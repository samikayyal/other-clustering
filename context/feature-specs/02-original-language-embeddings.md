# Feature 02: Original-Language Embeddings

## Objective

Create a stable vector representation for every eligible answer using Nebius Token Factory's `Qwen/Qwen3-Embedding-8B` model without translating or otherwise changing the answer language.

## Detailed Description

The embedding stage receives the answer records created by Feature 01. It sends their exact text to the Nebius embeddings API through `httpx` and requests embeddings from `Qwen/Qwen3-Embedding-8B`.

The provider integration uses this fixed request contract:

- base URL: `https://api.tokenfactory.nebius.com/v1`;
- endpoint: `POST /embeddings`;
- API key: `NEBIUS_API_KEY`, loaded from the environment or optional `.env`;
- authorization: `Authorization: Bearer <NEBIUS_API_KEY>`;
- request body: OpenAI-compatible JSON with model
  `Qwen/Qwen3-Embedding-8B`, an `input` array containing at most `32` exact
  answer strings, `encoding_format: "float"`, and `dimensions: 4096`;
- response body: an OpenAI-compatible embedding list whose `data` entries each
  contain an integer `index` and numeric `embedding` array;
- timeout: `120` seconds per request through `httpx`;
- retries: none; the first network error, timeout, non-success HTTP response, or
  malformed response stops the embedding stage; and
- model instruction: none. The exact extracted answer is sent without a prefix
  or task instruction.

For every returned embedding, the application must:

1. verify that response indices are unique and exactly cover
   `0..requested_input_count-1`, then map vectors to inputs by those indices
   rather than trusting response-array order;
2. verify the vector has exactly `4096` finite numeric values;
3. convert it to NumPy `float32`;
4. verify that its L2 norm is approximately `1.0` using `rtol=1e-5` and
   `atol=1e-6`, without application-side renormalization;
5. store the unchanged `float32` values in a fixed-shape NumPy memory map; and
6. write a row-map entry that connects the memory-map row to the stable answer
   ID and workbook location.

The memory map has logical shape `(processing_answer_count, 4096)`, where each processing answer is one distinct exact text scoped to one question. The row map must preserve the relationship between each canonical processing answer and its vector, including the complete fan-out list of original respondent locations represented by that deduplicated answer.

Repeated exact text is embedded once per question. The corresponding row-map entry contains the question ID, exact answer text, and all stable row-level answer IDs and workbook source-row references sharing that question/text key. Any embedding, assignment, or discovery result is applied to each of those row-level records through this fan-out mapping.

Completed per-run artifacts are stored as:

```text
embedding_artifacts/
  <dataset-fingerprint>/
    embeddings.f32
    row-map.json
```

`row-map.json` contains a schema version, source-workbook SHA-256, dataset
fingerprint, endpoint, model, dimensions, dtype, instruction policy,
vector-validation contract, memory-map shape, and an ordered entry for every
memory-map row. Each entry contains the memory-map row number, processing ID,
question ID, exact answer text, stable row-level answer IDs, and complete
workbook source locations.

Run artifacts are first written to temporary paths and made visible as complete
artifacts only after the full memory map and row map validate. If a completed
artifact directory already exists, it is reused only when every compatibility
field and ordered row-map input matches. An incompatible collision stops the
stage instead of overwriting. The CLI's workbook `--overwrite` option does not
authorize replacement of incompatible embedding artifacts.

Valid embeddings are reused across runs through a plaintext cache:

```text
embedding_cache/
  <first-two-cache-key-characters>/
    <cache-key>.json
```

The cache key is a SHA-256 over the exact UTF-8 answer text, endpoint, model,
dimensions, instruction policy, and vector-validation contract. A cache entry
contains those identity fields, the exact answer text, and the validated
`float32` vector. This permits the same exact text to reuse one provider vector
across workbooks or questions while each question-specific processing answer
still receives its own memory-map row and fan-out mapping. Cache entries are
written atomically. Valid entries from completed batches remain reusable if a
later batch fails, but no per-run artifact is considered successful until the
entire stage completes.

An empty, zero-norm, non-finite, incorrectly sized, or non-unit embedding stops
the stage. Categorization does not continue and no partial run artifact is
reported as successful.

The stage must not translate, transliterate, summarize, spell-correct, or normalize away dialectal content before the provider call. Any minimal whitespace handling must be defined by the workbook eligibility contract rather than silently changing the source value.

## Outputs

- A `float32` memory map with exactly `4096` columns.
- Provider-returned rows verified to be unit length and suitable for cosine
  calculation without application-side renormalization.
- A row map aligned exactly with memory-map order.
- A failure result that prevents categorization when the provider response is incomplete, malformed, or misaligned.

## Success Looks Like

- Arabic, dialectal Arabic, and English answers are sent in their original
  language and exact extracted text form after the Feature 01 HTML-tag cleanup.
- The configured model is exactly `Qwen/Qwen3-Embedding-8B`.
- Every stored row has dtype `float32`, dimension `4096`, finite values, and L2
  norm approximately `1.0` using `rtol=1e-5` and `atol=1e-6`; stored values
  have not been application-side renormalized.
- Reopening the memory map and row map reproduces the exact answer-to-vector relationship.
- Repeated answers retain all respondent-row references even if the API request is deduplicated.
- A missing vector, unexpected dimension, response-order mismatch, or invalid number stops the stage without producing a successful partial result.
- `pytest` tests with mocked HTTP responses verify request preservation,
  response-index mapping, shape, dtype, finite values, unchanged provider
  values, unit-norm validation, persistence, cache reuse and invalidation, and
  row alignment without calling the live Nebius API.

## Not Included

- Translation.
- Existing-choice decisions.
- PCA or clustering.
- Gemini calls.
- Workbook mutation.
