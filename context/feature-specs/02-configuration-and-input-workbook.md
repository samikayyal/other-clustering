# Spec 02 — Configuration and Input Workbook

**Status:** Planned
**Dependencies:** Spec 01
**Implementation order:** 02 of 11

## Outcome

The CLI can generate a valid starter workbook/configuration and validate a user-supplied workbook and TOML configuration completely locally. Validation rejects structural, schema, profile, redaction, credential, and budget-configuration errors before any semantic provider call.

## Input workbook contract

The input must contain exactly these sheets:

1. `Question` — exactly one data row with:
   - `question_id`: required, nonblank stable string;
   - `question_text`: required, nonblank wording;
   - `pure_discovery`: required boolean.
2. `Choices` — always present. Nonblank rows contain unique `choice_id`, required `choice_label`, and optional `choice_description` and newline-delimited `choice_examples`.
3. `Answers` — required `answer_id` string, required `answer_text` column with blank cells allowed, optional `answer_language`, and any additional columns as local passthrough metadata.

Rules:

- `pure_discovery = false` requires at least one valid choice row.
- `pure_discovery = true` permits an empty `Choices` sheet.
- Required IDs and answer values are read as strings so leading zeroes survive.
- Additional answer columns are copied to `Assignments`, never used as clustering features, and never sent to providers.
- Reject missing/extra required structure, duplicate IDs, additional `Question` data rows, invalid booleans, invalid language-code syntax, formulas in required fields, and inconsistent pure-discovery settings.
- A blank individual answer is valid input and receives an explicit downstream status; it is not a schema failure.

Use `openpyxl` for reading and writing. The source workbook is never modified.

## TOML configuration contract

Use a versioned TOML schema with explicit, editable profiles. Required sections are:

- `run`: schema version, fixed random seed, selected profile set, output location, and preview size;
- `models.nebius`: exact `Qwen/Qwen3-Embedding-8B` ID, direct Token Factory base/route policy, 2048 output dimension, `float32`, L2 normalization, fixed instruction, batch/concurrency/timeouts/retries, and pricing metadata;
- `models.google`: direct `gemini-3.5-flash` ID, direct Google base/`generateContent` route policy, structured-output and safety settings, batch/verification budgets, timeouts/retries, and pricing metadata;
- `clustering`: `min_cluster_size = 3`, `max_new_categories = 50`, `expansion_cap = 20`, PCA target dimension, working-memory ceiling, HDBSCAN parameters, and membership threshold;
- `choice_matching`: configurable similarity and margin thresholds, initially `0.80` and `0.08`, plus the requirement for structured verification;
- `normalization`: NFC/symbol cleanup policy, pinned Unicode/emoji data identifier, and cleanup hash inputs;
- `nonsemantic`: exact markers and regular expressions;
- `redaction`: deterministic email/phone/URL/ID and analyst-supplied patterns;
- `budget`: hard per-run limit and retry reserve policy;
- `failures`: retry settings and circuit-breaker thresholds;
- `cache`: workspace-relative directory and persistent plaintext retention policy.

Credentials are environment-only:

- `NEBIUS_API_KEY`;
- optional non-secret `NEBIUS_AI_PROJECT_ID`;
- `GEMINI_API_KEY`.

Load them with `python-dotenv` into a small frozen, secret-safe dataclass. Required-key validation may report a missing variable name but must never echo a value.

## Commands delivered

### `template --output INPUT.xlsx`

- Creates the three exact input sheets with documented headers and representative non-sensitive examples.
- Preserves the workbook contract without adding hidden semantic fields.
- Writes or points to a documented example TOML configuration without credentials.

### `validate --input INPUT.xlsx --config CONFIG.toml`

- Parses and validates the entire workbook and configuration.
- Validates model/profile completeness, provider identity separation, redaction rules, credential presence, and pricing metadata requirements.
- Performs no semantic API calls and does not create a paid request plan.
- Returns a typed validation result and a meaningful nonzero exit category on failure.

## Implementation tasks

1. Implement workbook schema/header constants and string-preserving `openpyxl` readers.
2. Detect formulas in required fields before converting values into domain records.
3. Implement the versioned TOML loader and canonical config representation.
4. Implement secret-safe environment loading and missing-key diagnostics.
5. Add template generation and example configuration output.
6. Add validation reports that identify sheet/row/field/reason without leaking raw sensitive text.

## Tests

- Exact sheet and header validation.
- Required string-ID preservation, including leading zeroes.
- Pure-discovery/empty-choice rules.
- Formula rejection in required fields.
- Duplicate IDs, extra question rows, invalid booleans, invalid language hints, and missing required columns.
- Passthrough metadata is accepted locally and excluded from provider-bound models.
- TOML section/profile/threshold/budget validation and missing-pricing rejection for `estimate` readiness.
- Secret-safe `repr` and error messages for environment settings.
- `template` output can be read back by the validator.
- `validate` makes zero provider calls when a provider spy is installed.

## Acceptance criteria

- A generated template validates without semantic calls.
- A valid user workbook and configuration produce a typed validation success.
- Every documented structural error is detected before any provider request.
- The original workbook remains byte-for-byte unmodified by validation/template workflows except for the newly created template output.
- Later specs can consume typed `QuestionSpec`, `ChoiceAnchor`, and `AnswerRecord` values without reopening XLSX cells.

## Non-goals

- Semantic normalization, language detection, redaction execution, cost estimation, provider health checks, or output workbook generation.
