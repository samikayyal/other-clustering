# Feature 05: Simplified Analyst Review and Completion

## Objective

Provide a local Flask/Jinja/vanilla-JavaScript browser review for the one V2
review file. The analyst reviews every fixed cluster and every unresolved
canonical answer, then completes that same JSON file atomically.

## Permissions

For a system cluster, membership is immutable and the analyst chooses the
whole cluster's final disposition:

- `existing_choice`: one same-question existing-choice value;
- `new_category`: one bilingual category label for every member; or
- `unresolved`.

The analyst may not split, merge, move members, create a free-standing
category, edit values, or change question/source evidence. Noise, rare,
low-probability, and rejected-small-cluster canonical answers allow only
`existing_choice` or `unresolved`.

The UI remains question-centered and shows bilingual question text, choices,
raw canonical answers, occurrence counts, row mappings, discovery evidence,
fixed cluster members, and the Gemini proposal/provider warning. It provides a
cluster-level selector, a question-scoped existing-choice dropdown, bilingual
inputs for new categories, unresolved controls for noise/rare answers, an
analyst-name input, and a completion button with concise validation messages.

There are no routes or controls for free-standing categories, split/merge/move
operations, merge edges, value editing, override logs, drafts, approvals, or
finalization.

## Completion validation

Completion requires a nonblank analyst name and exactly one valid decision for
every cluster and unresolved canonical answer. It validates:

- schema version 2 and required types;
- same-question existing-choice references;
- immutable cluster membership;
- cluster and noise/rare decision cross-fields;
- valid 1–6-word bilingual labels, scripts, prohibited wording, and no
  same-question normalized duplicate new-category labels; and
- no unknown or unsupported fields that cross a concrete safety boundary.

Until this succeeds, `status` remains `in_review` and `completed_at_utc` is
null. The application writes the completed state back to the same file through
an atomic replacement, setting `status: complete`, `completed_at_utc`, and the
final update timestamp together.

## Value allocation

Only final `new_category` cluster decisions receive values, and allocation
happens during completion. For each question independently, collect integers
greater than `100` already used by that question's existing `Code` choices.
Process accepted new categories by stable cluster ID and assign each the
smallest unused integer greater than `100`. Rejected/unresolved clusters
consume no value. Values may repeat across different question lists.

The allocated value is written into the authoritative decision in the same
atomic save. The browser displays allocated values only after completion.

## Completed files

A completed file is read-only in the application. Reopening it displays final
results without edit controls. V1 has no reopen or amendment workflow; a
changed result requires another analysis run.
