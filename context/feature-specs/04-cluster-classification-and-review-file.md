# Feature 04: Cluster Classification and Review-File Creation

## Objective

Ask Gemini once for each proposal-eligible cluster, then create one
schema-version-2 UTF-8 review file. Existing-choice reuse occurs here at
cluster level. This stage never allocates final values or writes a workbook.

## Gemini requests

Use `gemini-3.5-flash-lite` with schema-constrained structured output. Each
request contains the question ID and bilingual question text, every
same-question existing choice with its stored value and bilingual labels, and a
deterministic member sample. A sample member contains only exact cleaned text,
occurrence count, and membership probability. Respondent keys and workbook
locations are never sent.

Sampling is deterministic: send every member for clusters of at most 50
distinct texts; for larger clusters send the 25 highest-probability and 25
lowest-probability members, breaking ties by processing ID.

The response is:

```json
{
  "decision": "existing_choice | new_category | reject_cluster",
  "selected_choice_value": "integer | null",
  "english_label": "string | null",
  "arabic_label": "string | null",
  "rejection_reason": "mixed_meanings | insufficient_common_meaning | unsafe_to_label | null"
}
```

`existing_choice` requires one integer value from the same question and null
labels/reason. `new_category` requires null value/reason and valid concise
English/Arabic labels. `reject_cluster` requires null value/labels and one
allowed reason. Unknown choices and all cross-field violations are invalid.
Gemini may reuse a choice only when it captures the common meaning of the
cluster as a whole. Ambiguous, mixed, unsafe, or incoherent clusters must be
rejected.

Labels retain the existing checks: 1–6 words, English/Arabic scripts,
prohibited generic wording and sensitive details, and no same-question
normalized duplicate of an existing or proposed label.

Transport has five attempts for network errors, timeouts, HTTP 408, 429, and
5xx. A cluster may use up to three structured generations when schema,
cross-field, or label validation fails. A valid rejection is final. After
exhaustion, record a fixed `provider_error` cluster proposal and a safe warning
and continue the analysis. Do not expose credentials in warnings.

No proposal-eligible clusters means no Gemini key is required and no Gemini
request is made.

## Review file

Write exactly one file to:

```text
./reviews/<normalized_source_stem>_<analysis_run_id>.json
```

The top level is:

```json
{
  "schema_version": 2,
  "analysis_run_id": "lowercase UUIDv4",
  "status": "in_review",
  "created_at_utc": "timestamp",
  "updated_at_utc": "timestamp",
  "completed_at_utc": null,
  "analyst_name": null,
  "source_workbook": {
    "input_kind": "local_xlsx | google_sheets",
    "source_locator": "string",
    "display_name": "string",
    "size_bytes": 123,
    "sha256": "lowercase sha256"
  },
  "questions": [],
  "warnings": []
}
```

Each question stores bilingual metadata, all same-question choices, canonical
answers with occurrence counts and row mappings, discovery evidence, fixed
member clusters, each cluster's Gemini proposal, and unresolved canonical
answers. A cluster has exactly one nullable authoritative analyst decision:

```json
{
  "decision": "existing_choice | new_category | unresolved",
  "selected_choice_value": "integer | null",
  "english_label": "string | null",
  "arabic_label": "string | null",
  "allocated_value": "integer | null"
}
```

Noise/rare decisions use only `existing_choice` or `unresolved` and cannot
contain labels or allocated values. Provider-error clusters remain fixed and
the analyst may manually choose existing/new/unresolved for the whole cluster.

The file is evidence and editable state; it contains no proposal/final
duplicate, review-item disposition arrays, override log, approval ID, review
hash, receipt, replay state, merge graph, or final answer snapshot. Arrays and
objects use deterministic ordering, Arabic is not ASCII-escaped, and schema
version 1 artifacts are rejected with a message requiring a new analysis.
