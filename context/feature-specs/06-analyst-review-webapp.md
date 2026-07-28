# Feature 06: Analyst Review Web Application and Approval Gate

## Objective

Provide a web application in which an analyst reviews every categorization result and explicitly confirms the complete run before Feature 07 may write any new `Code` row or respondent output value.

This feature is a mandatory safety and quality gate, not an optional reporting screen. Feature 05 prepares the review package, and only a complete structured approval from Feature 06 authorizes the gated finalization performed by Feature 07.

## Delivery Sequence

The review contract is delivered in two stages:

1. **Interim terminal workflow** — `other-cluster` writes the complete review
   package to a UTF-8 JSON file and prints a compact JSON summary containing the
   absolute package path, analysis run ID, source-workbook hash, and review-item
   counts. The analyst reviews the file and supplies a matching structured
   approval response to a separate finalization step. The analysis command
   never pauses for interactive input.
2. **Review web application** — the web application presents the same logical review package through a browser and emits the same logical structured approval after the analyst completes every required decision.

The interim and web workflows must enforce the same completeness and validation rules so the web application does not change the meaning of approval.

[INPUT REQUIRED: Define the exact CLI mechanism for supplying the interim structured analyst response, such as a JSON file argument or standard input to a separate finalization command.]

## Review Package

A successful analysis writes:

```text
./review_packages/<normalized_source_stem>_<analysis_run_id>_review.json
```

`analysis_run_id` is a newly generated lowercase UUID version 4. The filename
normalization follows the Feature 01 source-name rules. A UUID filename
collision is a failure and is never overwritten.

The file uses UTF-8 without a byte-order mark, preserves Arabic characters
rather than ASCII-escaping them, uses two-space indentation and LF line
endings, and ends with one newline. Every object field described below is
required, nullable fields use explicit JSON `null`, and unrecognized fields are
invalid. Arrays use the deterministic order defined below.

The top-level schema is:

```json
{
  "schema_version": 1,
  "analysis_run_id": "lowercase UUIDv4",
  "created_at_utc": "RFC 3339 UTC timestamp ending in Z",
  "source_workbook": {
    "input_kind": "local_xlsx | google_sheets",
    "source_locator": "absolute local path or canonical Google Sheets URL",
    "display_name": "source filename ending in .xlsx",
    "size_bytes": 123,
    "sha256": "64 lowercase hexadecimal characters"
  },
  "questions": [],
  "warnings": []
}
```

The source fingerprint is SHA-256 over the exact XLSX byte stream used by
Feature 01. `size_bytes` is the length of the same byte stream. For local input,
`source_locator` is the resolved absolute source path. For Google Sheets input,
it is the canonical spreadsheet URL used to create the export. Feature 07 must
resolve or re-export the same locator and require both its byte length and
SHA-256 to match before writing. A mismatching Google re-export fails safely
and requires a new analysis, even if the visible sheet appears unchanged. The
temporary Google XLSX remains subject to Feature 01 cleanup and is not retained
as a second source snapshot.

Each `questions` entry has this schema:

```json
{
  "question_id": "string",
  "question_text": {
    "english": "string",
    "arabic": "string"
  },
  "source_column": "string",
  "existing_choices": [],
  "answers": [],
  "existing_choice_assignments": [],
  "proposed_categories": [],
  "merge_suggestions": [],
  "unresolved_answers": []
}
```

`existing_choices` contains:

```json
{
  "value": 1,
  "english_label": "string",
  "arabic_label": "string",
  "code_row": 12
}
```

`answers` contains one entry per canonical question/text processing item.
Repeated respondent answers are represented once here and retain every
row-level mapping:

```json
{
  "processing_id": "string",
  "text": "exact Feature 01-cleaned answer",
  "occurrence_count": 2,
  "row_mappings": [
    {
      "answer_id": "string",
      "respondent_key": "string",
      "sheet": "Data",
      "row": 14,
      "column": 8,
      "coordinate": "H14"
    }
  ],
  "discovery_evidence": {
    "raw_cluster_label": 0,
    "membership_probability": 0.91,
    "status": "accepted_cluster",
    "cluster_id": "string"
  }
}
```

All four `discovery_evidence` fields are nullable when Feature 03 assigned the
answer before discovery. Otherwise, `status` is exactly one of
`rare_insufficient_distinct_texts`, `noise`, `low_probability`,
`rejected_cluster`, or `accepted_cluster`, matching Feature 04.
`occurrence_count` must equal the number of `row_mappings`.

`existing_choice_assignments` contains:

```json
{
  "review_item_id": "existing_assignment:<processing_id>",
  "processing_id": "string",
  "proposed_choice_value": 1,
  "provider_decision": "assign"
}
```

`proposed_categories` contains:

```json
{
  "review_item_id": "proposed_category:<cluster_id>",
  "cluster_id": "string",
  "proposed_value": 101,
  "english_label": "string",
  "arabic_label": "string",
  "member_processing_ids": ["string"]
}
```

`merge_suggestions` contains:

```json
{
  "review_item_id": "merge:<first_cluster_id>:<second_cluster_id>",
  "first_cluster_id": "string",
  "second_cluster_id": "string",
  "cosine_similarity": 0.93,
  "combined_member_processing_ids": ["string"]
}
```

The two cluster IDs use Feature 04's deterministic ascending pair order.

`unresolved_answers` contains one entry for every canonical answer that is not
proposed for an existing choice or accepted new category:

```json
{
  "review_item_id": "unresolved:<processing_id>",
  "processing_id": "string",
  "reason": "noise | rare_insufficient_distinct_texts | low_probability | rejected_cluster | label_rejected_mixed_meanings | label_rejected_insufficient_common_meaning | label_rejected_unsafe_to_label",
  "cluster_id": "string | null"
}
```

`warnings` contains non-fatal run warnings:

```json
{
  "code": "safe machine-readable reason code",
  "message": "human-readable message",
  "source_cell": "Data!H14 | null"
}
```

Questions are ordered by `question_id`. Existing choices are ordered by
`(value, code_row)`, answers and their assignment/unresolved items by
`processing_id`, proposed categories by `cluster_id`, merge suggestions by
their two cluster IDs, row mappings by `answer_id`, and warnings by
`(code, source_cell, message)`. Every `review_item_id` must be unique across the
complete package, and every referenced processing ID, cluster ID, choice value,
and answer ID must resolve exactly once within the same question.

A validation failure prevents the package from being reviewable, so Feature 05
does not write a partial package containing validation errors. It reports the
failure normally and removes any incomplete package file. A successfully
written package has no authority to mutate the workbook.

## Web Review Experience

The web application presents results by question so the analyst can understand each answer in its survey context. The analyst must be able to inspect:

- the English and Arabic question text;
- existing allowed choices;
- raw original-language answers and their occurrence counts;
- proposed existing-choice assignments;
- proposed new categories and all member answers;
- proposed English and Arabic labels;
- proposed workbook-wide values;
- cluster membership probabilities or other available discovery evidence; and
- all unresolved/noise cases.

At minimum, the analyst must explicitly approve or reject every proposed
assignment, give every proposed category an `approved`, `rejected`, or `merged`
disposition, explicitly confirm or reject every merge suggestion, and
explicitly acknowledge every unresolved answer. The analyst may not approve the
run while any item lacks a disposition.

For an approved merged category, the analyst must explicitly confirm the
default label pair inherited from its smallest-value component or supply edited
final English and Arabic labels. Edited merged labels must pass Feature 05's
label validation rules.

[INPUT REQUIRED: Define whether the analyst may edit a non-merged category's
bilingual labels, move answers between categories, create a category manually,
split a cluster, or assign an unresolved answer to an existing category.]

The system proposes merges for semantically overlapping clusters. The analyst
must explicitly confirm or reject every merge edge. Approved edges are
undirected and transitive: all clusters connected by approved edges form one
merged category. That category receives the deduplicated union of the component
members, retains the smallest component proposed value, and defaults to that
component's label pair. Other component values are left unused and are not
reallocated.

Every component category in an approved merged group receives a `merged`
disposition and cannot also be separately approved or rejected. An approval is
invalid when a merged component was separately rejected or when an explicitly
rejected merge edge has both endpoints inside the same approved connected
group. The analyst must revise such conflicting dispositions before the review
can be completed.

## Complete Structured Approval

The analyst response must contain:

- the matching analysis run ID and source-workbook identity;
- analyst identity;
- an explicit disposition for every proposed assignment, category, merge suggestion, and unresolved answer;
- the final approved category labels, values, memberships, and respondent assignments;
- confirmation that the analyst reviewed the entire run; and
- approval for one gated finalization attempt.

A response is incomplete if even one review item is missing, undecided, or refers to an unknown item. An incomplete response produces no workbook mutation.

[INPUT REQUIRED: Define the exact structured analyst-response schema, analyst identity requirements, and whether a timestamp or electronic signature is required.]

## Handoff to Feature 07

A complete approval authorizes one gated finalization attempt by Feature 07.
Feature 06 does not write `Code` rows, respondent output values, or an output
workbook. Feature 07 validates the approval again against the same analysis run
and source workbook before making any changes.

## Web Application Boundary

The simplest implementation that satisfies the review workflow should be used. The project intentionally defers the web technology, browser UI approach, review-state storage, and local or hosted deployment model until this feature is implemented.

- [DECISION DEFERRED: Select the Python web framework and browser UI approach during Feature 06 implementation.]
- [DECISION DEFERRED: Decide whether the web application is local-only or hosted during Feature 06 implementation.]
- [DECISION DEFERRED: Define how review packages and in-progress analyst decisions are stored during Feature 06 implementation.]
- [INPUT REQUIRED: Define authentication and authorization requirements, including who is allowed to finalize a workbook.]
- [INPUT REQUIRED: Define whether multiple analysts or concurrent reviews must be supported.]

No collaboration, notification, dashboard, or administration feature is included unless required by one of these decisions.

## Outputs

- A complete structured analyst approval or an explicit incomplete/rejected state.
- No workbook changes for incomplete, rejected, stale, invalid, or mismatched approvals.
- For a valid complete approval, authorization for one finalization attempt by Feature 07.

## Success Looks Like

- The interim CLI writes a complete UTF-8 JSON package containing every item
  that requires review and prints only its compact structured summary without
  prompting during analysis.
- The web application presents the same complete review scope in a question-centered browser interface.
- The analyst cannot confirm the run while any assignment, new category, or unresolved answer lacks a disposition.
- No `Code` or respondent output cell changes before complete approval.
- A partial, stale, malformed, or mismatched response fails with details and leaves the workbook unchanged.
- A generated-value collision fails with the duplicated value and all conflicting rows or proposals.
- A valid complete response gives Feature 07 exactly the analyst-approved `Code` rows and respondent output records to validate and write.
- Raw answers and unrelated workbook content remain unchanged.
- Automated tests cover terminal-package completeness, approval completeness, stale/mismatched approvals, value collisions, zero-write failures, and successful finalization.

## Not Included

- Automatic approval.
- Writing any coding result; workbook mutation is owned by Feature 07.
- Final output-workbook save policy and workbook-write mechanics, which are Feature 07.
- Translation of respondent answers.
- General survey editing.
- Collaboration or administration features not explicitly selected above.
