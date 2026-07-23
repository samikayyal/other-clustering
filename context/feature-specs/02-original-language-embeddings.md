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
5. store the unchanged `float32` values in a fixed-shape in-memory NumPy array; and
6. retain a row-map entry that connects the vector row to the stable answer
   ID and workbook location.

The in-memory vector array has shape `(processing_answer_count, 4096)`, where each processing answer is one distinct exact text scoped to one question. The in-memory row map must preserve the relationship between each canonical processing answer and its vector, including the complete fan-out list of original respondent locations represented by that deduplicated answer.

Repeated exact text is embedded once per question. The corresponding row-map entry contains the question ID, exact answer text, and all stable row-level answer IDs and workbook source-row references sharing that question/text key. Any embedding, assignment, or discovery result is applied to each of those row-level records through this fan-out mapping.

Vectors and row mappings exist only in memory for the active analysis process.
The row map preserves ordered entries containing the vector row number,
processing ID, question ID, exact answer text, stable row-level answer IDs, and
complete workbook source locations. No `embedding_artifacts/` directory,
memory-map file, or serialized row-map file is written.

Valid embeddings are reused across runs through one local SQLite database at
`embedding_cache/cache.sqlite3`. The `embeddings` table uses a composite primary
key of the exact answer text, endpoint, model, dimensions, instruction policy,
finite-value requirement, norm tolerances, and application-renormalization
policy. There are no hashes, cache keys, prefix directories, JSON entries, or
legacy migration path. Existing JSON entries were intentionally discarded when
this storage format was introduced.

The database is schema version `1` (`PRAGMA user_version = 1`). Every open
verifies that version and the expected table columns before any cache read. A
malformed, corrupt, or incompatible database is an embedding failure; it is
never silently rebuilt, deleted, repaired, or bypassed. Rows with a different
valid composite identity are cache misses and may coexist with current rows.

Each vector is stored as a contiguous little-endian `float32` BLOB. A cache read
requires exactly `4096 * 4` bytes, copies the decoded vector into owned memory,
and repeats the dimension, finite-value, and unit-norm checks without
renormalizing. Each connection requires a 5-second busy timeout, WAL journal
mode, and `FULL` synchronous writes. Provider calls remain outside database
transactions. Once one complete provider batch has been response-indexed and
validated, its vectors are upserted in one transaction and become available in
memory only after that commit succeeds. A write or commit failure rolls back
the entire batch; earlier committed batches remain reusable after a later
failure.

The cache directory and database are not created for an empty dataset, a
missing API key, or a provider failure before a batch completes. This permits
the same exact text to reuse one provider vector across workbooks or questions
while each question-specific processing answer still receives an in-memory
vector row and fan-out mapping for the active run.

An empty, zero-norm, non-finite, incorrectly sized, or non-unit embedding stops
the stage. Categorization does not continue and no partial result is reported as
successful.

The stage must not translate, transliterate, summarize, spell-correct, or normalize away dialectal content before the provider call. Any minimal whitespace handling must be defined by the workbook eligibility contract rather than silently changing the source value.

When Feature 01 yields no eligible processing answers, the stage makes no
provider request and does not require `NEBIUS_API_KEY`. It returns an in-memory
`float32` array with shape `(0, 4096)` and an empty row map.

## Outputs

- An in-memory `float32` vector array with exactly `4096` columns.
- Provider-returned rows verified to be unit length and suitable for cosine
  calculation without application-side renormalization.
- A row map aligned exactly with in-memory vector order.
- A failure result that prevents categorization when the provider response is incomplete, malformed, or misaligned.

## Success Looks Like

- Arabic, dialectal Arabic, and English answers are sent in their original
  language and exact extracted text form after the Feature 01 HTML-tag cleanup.
- The configured model is exactly `Qwen/Qwen3-Embedding-8B`.
- Every stored row has dtype `float32`, dimension `4096`, finite values, and L2
  norm approximately `1.0` using `rtol=1e-5` and `atol=1e-6`; stored values
  have not been application-side renormalized.
- The in-memory vector array and row map preserve the exact answer-to-vector relationship for the active run.
- Two executions over the same workbook reuse compatible exact-answer cache
  entries without additional provider calls.
- Repeated answers retain all respondent-row references even if the API request is deduplicated.
- A valid zero-answer dataset produces a reusable empty artifact without a
  provider call.
- A missing vector, unexpected dimension, response-order mismatch, or invalid number stops the stage without producing a successful partial result.
- `pytest` tests with mocked HTTP responses verify request preservation,
  response-index mapping, shape, dtype, finite values, unchanged provider
  values, unit-norm validation, in-memory row alignment, cache reuse and
  invalidation without calling the live Nebius API.

## Not Included

- Translation.
- Existing-choice decisions.
- PCA or clustering.
- Gemini calls.
- Workbook mutation.
