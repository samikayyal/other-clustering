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

The interim workflow supplies the approval as an explicit JSON file to a
separate finalization command:

```text
other-cluster finalize --review-package REVIEW_JSON --approval APPROVAL_JSON --output OUTPUT_XLSX [--overwrite]
```

`REVIEW_JSON` and `APPROVAL_JSON` must be existing regular files. Standard
input, implicit neighboring-file discovery, and interactive prompts are not
supported. The existing `other-cluster --input ... --output ...` analysis
invocation remains valid; `finalize` is a distinct command mode. Configuration
may still supply the output path and overwrite setting under Feature 01's
normal precedence, but explicit finalization arguments take precedence.

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

At minimum, the analyst must explicitly dispose of every original review item.
An existing-choice assignment is `approved`, `rejected`, or `overridden`; a
proposed category is `approved`, `rejected`, `modified`, `merged`, or `split`;
a merge suggestion is `approved` or `rejected`; and an unresolved answer is
`acknowledged` or `assigned`. The analyst may not approve the run while any
item lacks exactly one allowed disposition.

For an approved merged category, the analyst must explicitly confirm the
default label pair inherited from its smallest-value component or supply edited
final English and Arabic labels. Edited merged labels must pass Feature 05's
label validation rules.

The analyst has full control over the final categorization within each
question. The review application must allow the analyst to:

- edit the bilingual labels of any proposed or analyst-created category;
- move an answer between proposed or analyst-created categories;
- create a category manually;
- split a proposed category into two or more categories;
- combine categories even when Feature 04 did not propose a merge;
- assign an unresolved answer to an existing choice or a new category;
- override a proposed existing-choice assignment with another existing choice,
  a new category, or an acknowledged unresolved disposition; and
- leave any answer unresolved with an explicit acknowledgement.

These controls do not permit the analyst to alter the raw answer text, source
row mappings, question identity, source-workbook identity, or the definitions
and stored values of existing workbook choices. An answer may not be moved
between questions. Every final new category must contain at least one
processing answer and have a valid bilingual label pair. Every processing
answer must end in exactly one final state: assigned to one existing choice,
assigned to one final new category, or explicitly acknowledged as unresolved.
The final structured approval, rather than the original automated proposal, is
authoritative for Feature 07, while retaining the original proposal and every
analyst override as audit evidence.

### Final Category Values

Feature 06 assigns values automatically; the analyst does not type or edit
stored workbook values.

- A surviving proposed category retains its Feature 05 proposed value even
  when its label or membership is edited.
- A merged category retains the smallest proposed value among all component
  categories.
- When one proposed category is split, the child containing the
  lexicographically smallest member processing ID retains the parent's
  proposed value. Additional children are ordered by their smallest member
  processing ID.
- Categories created manually and additional split children receive the
  smallest unused workbook-wide integer greater than `100`. After all retained
  values are reserved, additional split children are allocated first in
  ascending `(question_id, parent_proposed_value,
  smallest_member_processing_id)` order, followed by manual categories in
  ascending `(question_id, stable_analyst_category_id)` order.
- Values released by rejected or superseded proposals remain unused gaps for
  that review and are not recycled.

Every analyst-created category receives a stable ID when it is first created.
The ID and creation sequence are persisted in the draft so reopening the
review cannot reorder categories or change their final allocation.

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

The analyst response is a hybrid audit-and-final-state document. It contains
both a disposition for every original review item and one authoritative final
snapshot for Feature 07. It uses this top-level schema:

```json
{
  "schema_version": 1,
  "approval_id": "lowercase UUIDv4",
  "analysis_run_id": "matching lowercase UUIDv4",
  "review_package_sha256": "SHA-256 of the exact review-package JSON bytes",
  "source_workbook": {
    "input_kind": "local_xlsx | google_sheets",
    "source_locator": "matching source locator",
    "display_name": "matching .xlsx display name",
    "size_bytes": 123,
    "sha256": "matching source-workbook SHA-256"
  },
  "analyst": {
    "name": "required non-empty self-declared name"
  },
  "approved_at_utc": "application-generated RFC 3339 UTC timestamp ending in Z",
  "review_item_dispositions": [],
  "questions": [],
  "complete_review_confirmed": true,
  "authorize_finalization": true
}
```

There is no electronic-signature field. Because the application has no
authentication, `analyst.name` is audit metadata rather than verified
identity. The web application generates `approval_id` and `approved_at_utc`.
An interim file produced outside the web application must supply valid values;
the finalizer validates them but does not treat them as cryptographic proof.

`review_item_dispositions` contains exactly one entry for every review item in
the original package:

```json
{
  "review_item_id": "matching review item ID",
  "disposition": "allowed disposition for that item type",
  "note": "analyst note | null"
}
```

Each question entry contains:

```json
{
  "question_id": "matching question ID",
  "final_categories": [],
  "answer_dispositions": [],
  "analyst_overrides": []
}
```

`final_categories` contains every final new category:

```json
{
  "final_category_id": "stable unique ID",
  "origin": "proposed | modified | merged | split | manual",
  "value": 101,
  "english_label": "validated string",
  "arabic_label": "validated string",
  "component_cluster_ids": ["zero or more original cluster IDs"],
  "member_processing_ids": ["one or more processing IDs"]
}
```

`answer_dispositions` contains exactly one authoritative final state for every
processing answer in the question:

```json
{
  "processing_id": "matching processing ID",
  "decision": "existing_choice | new_category | unresolved",
  "choice_value": "integer | null",
  "final_category_id": "string | null",
  "unresolved_reason": "analyst-confirmed reason | null"
}
```

Exactly one decision target is populated: `existing_choice` requires one
same-question existing `choice_value`; `new_category` requires one
same-question `final_category_id`; and `unresolved` requires a non-empty
`unresolved_reason`. A final category's member list must exactly equal the
processing answers that reference it.

`analyst_overrides` is generated by comparing the final state with the
immutable review package. It records every `edit_label`, `move_answer`,
`create_category`, `split_category`, `merge_category`,
`override_existing_assignment`, or `mark_unresolved` operation, with stable
override ID, affected review-item IDs, affected processing IDs, and a nullable
note:

```json
{
  "override_id": "stable unique ID",
  "operation": "edit_label | move_answer | create_category | split_category | merge_category | override_existing_assignment | mark_unresolved",
  "source_review_item_ids": ["zero or more matching review item IDs"],
  "affected_processing_ids": ["one or more matching processing IDs"],
  "note": "analyst note | null"
}
```

Feature 07 validates that the override records and original-item dispositions
agree with the final snapshot; it writes from the final snapshot, not by
replaying the operation list.

A response is incomplete if even one review item is missing, undecided, or refers to an unknown item. An incomplete response produces no workbook mutation.

Every field described by the approval schema is required unless explicitly
nullable. Unrecognized fields are invalid. IDs and cross-references must
resolve exactly once, arrays use the deterministic order of the review package
and final value-allocation rules, and JSON uses the same UTF-8, Arabic,
indentation, line-ending, and terminal-newline rules as the review package.

### Preserved Review Artifacts and Drafts

The first system-produced clusters, labels, assignments, evidence, and
unresolved items remain permanently preserved in the original immutable file:

```text
./review_packages/<normalized_source_stem>_<analysis_run_id>_review.json
```

Neither the web application nor finalization modifies or replaces that file.
The application verifies its exact SHA-256 whenever a draft or approval is
loaded.

The web application saves the analyst's latest valid in-progress state after
every accepted edit to:

```text
./review_state/<normalized_source_stem>_<analysis_run_id>_draft.json
```

Drafts may be incomplete and do not authorize workbook mutation. Each draft is
bound to the analysis-run ID and exact review-package SHA-256 and contains the
stable analyst-created category IDs, current dispositions, final-state work in
progress, and latest save timestamp. Draft writes use a temporary file in the
same directory followed by atomic replacement, so a failed write preserves the
last valid draft. Reopening the same package resumes that draft.

Completion writes the immutable approval to:

```text
./review_approvals/<normalized_source_stem>_<analysis_run_id>_approval.json
```

An existing approval filename is never overwritten. Draft completion does not
delete the draft or original package.

## Handoff to Feature 07

A complete approval authorizes one successful gated finalization by Feature
07. A validation failure or save failure before atomic output publication does
not consume the approval. After successful publication, Feature 07 writes a
durable finalization receipt tied to the approval ID and rejects later reuse.
If the process stops between output publication and receipt completion, a
pending receipt plus the exact output hash is used to recover the completed
state without applying the approval a second time.
Feature 06 does not write `Code` rows, respondent output values, or an output
workbook. Feature 07 validates the approval again against the same analysis run
and source workbook before making any changes.

## Web Application Boundary

The review application is local-only and binds to `127.0.0.1`. It uses Flask
with server-rendered Jinja templates and focused vanilla JavaScript for the
interactive category editor. It does not use a SPA framework, database, job
queue, or hosted service. Review packages, atomic draft JSON files, immutable
approval JSON files, and finalization receipts are the complete persistence
model.

- No authentication, login, role, or authorization distinction is required.
  Any person who can access the review application may review a package and
  authorize finalization.
- The application supports one analyst editing one analysis run at a time.
  Multi-analyst collaboration, concurrent editing, conflict merging, and
  concurrent finalization are not supported.

No collaboration, notification, dashboard, or administration feature is included unless required by one of these decisions.

## Outputs

- A complete structured analyst approval or an explicit incomplete/rejected state.
- No workbook changes for incomplete, rejected, stale, invalid, or mismatched approvals.
- For a valid complete approval, authorization for one successful
  finalization by Feature 07.

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
