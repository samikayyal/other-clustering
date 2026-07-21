# Feature 02: Original-Language Embeddings

## Objective

Create a stable vector representation for every eligible answer using Nebius Token Factory's `Qwen/Qwen3-Embedding-8B` model without translating or otherwise changing the answer language.

## Detailed Description

The embedding stage receives the answer records created by Feature 01. It sends their exact text to the Nebius embeddings API through `httpx` and requests embeddings from `Qwen/Qwen3-Embedding-8B`.

The provider integration needs a complete request contract:

- [INPUT REQUIRED: Provide the Nebius API base URL and embeddings endpoint.]
- [INPUT REQUIRED: Define the API-key environment variable name and authorization-header format.]
- [INPUT REQUIRED: Define request and response schemas if they differ from an OpenAI-compatible embeddings endpoint.]
- [INPUT REQUIRED: Define maximum batch size, request timeout, retry policy, and retryable failure classes.]
- [INPUT REQUIRED: Confirm any required model-specific input prefix or instruction for survey-answer embeddings.]

For every returned embedding, the application must:

1. verify the response maps to the requested input in the original order;
2. verify the vector has exactly `4096` finite numeric values;
3. convert it to NumPy `float32`;
4. L2-normalize it;
5. store it in a fixed-shape NumPy memory map; and
6. write a row-map entry that connects the memory-map row to the stable answer ID and workbook location.

The memory map has logical shape `(processing_answer_count, 4096)`, where each processing answer is one distinct exact text scoped to one question. The row map must preserve the relationship between each canonical processing answer and its vector, including the complete fan-out list of original respondent locations represented by that deduplicated answer.

Repeated exact text is embedded once per question. The corresponding row-map entry contains the question ID, exact answer text, and all stable row-level answer IDs and workbook source/target references sharing that question/text key. Any embedding, assignment, or discovery result is applied to each of those row-level records through this fan-out mapping.

[INPUT REQUIRED: Define the memmap and row-map filenames, storage directory, row-map format, and overwrite/collision rules.]

[INPUT REQUIRED: Decide whether completed vector artifacts are reusable across runs, and if so define how input workbook, model, normalization, and answer-order compatibility are validated.]

An empty or zero-norm embedding cannot support cosine comparison and must stop or remain unresolved according to an explicit policy.

[INPUT REQUIRED: Define the required behavior for empty, zero-norm, or otherwise invalid embeddings.]

The stage must not translate, transliterate, summarize, spell-correct, or normalize away dialectal content before the provider call. Any minimal whitespace handling must be defined by the workbook eligibility contract rather than silently changing the source value.

## Outputs

- A `float32` memory map with exactly `4096` columns.
- L2-normalized rows suitable for cosine calculation.
- A row map aligned exactly with memory-map order.
- A failure result that prevents categorization when the provider response is incomplete, malformed, or misaligned.

## Success Looks Like

- Arabic, dialectal Arabic, and English answers are sent in their original language and exact agreed text form.
- The configured model is exactly `Qwen/Qwen3-Embedding-8B`.
- Every stored row has dtype `float32`, dimension `4096`, finite values, and L2 norm approximately `1.0` within an agreed numeric tolerance.
- Reopening the memory map and row map reproduces the exact answer-to-vector relationship.
- Repeated answers retain all respondent-row destinations even if the API request is deduplicated.
- A missing vector, unexpected dimension, response-order mismatch, or invalid number stops the stage without producing a successful partial result.
- `pytest` tests with mocked HTTP responses verify request preservation, shape, dtype, normalization, persistence, and row alignment without calling the live Nebius API.

[INPUT REQUIRED: Define the numeric tolerance used to test L2 normalization.]

## Not Included

- Translation.
- Existing-choice decisions.
- PCA or clustering.
- Gemini calls.
- Workbook mutation.
