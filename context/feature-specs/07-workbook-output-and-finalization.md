# Feature 07: Workbook Output and Gated Finalization

## Objective

After Feature 06 returns a complete structured approval, validate that approval
against the same analysis run and source workbook, apply the approved `Code`
and respondent-output changes, and save a separate final workbook without
corrupting unrelated workbook content.

Feature 07 is the only feature that mutates or saves a coded workbook. No
partial, stale, mismatched, or invalid approval may produce workbook output.

## Inputs and Finalization Preconditions

Feature 07 consumes:

- the Feature 05 structured review package;
- the matching complete structured approval from Feature 06;
- the exact source workbook used for the analysis; and
- the resolved output path and overwrite setting defined by Feature 01.

Before writing, the finalizer must validate all of the following:

1. The approval belongs to the same analysis run, exact review-package
   SHA-256, and source-workbook identity.
2. Every review item has an explicit analyst disposition.
3. Every processing answer has exactly one final disposition and refers to an
   allowed same-question existing choice, one final new category, or an
   explicit unresolved reason.
4. Every final new category has an English label, Arabic label, at least one
   member, and integer value greater than `100`; its member list exactly
   matches the answer dispositions that reference it.
5. Every generated value greater than `100` is unique across the entire workbook and approval package.
6. The source workbook has not changed in a way that invalidates row mappings, `Code` blocks, or allocated values.
7. Every original review-item disposition, analyst override, final category,
   and final answer disposition is internally consistent. Feature 07 validates
   the final snapshot directly and does not replay the override list.
8. Every approved merge suggestion has both endpoints in the same final
   category, every rejected suggestion has endpoints in different final
   categories, and manually combined categories without a Feature 04
   suggestion remain allowed.
9. Retained, merged, split, and analyst-created category values follow Feature
   06's deterministic allocation rules; released proposal values are not
   recycled.
10. The approval ID has no completed finalization receipt.
11. The output path differs from the source path.
12. An existing output path is used only when overwrite was explicitly enabled.

If any validation fails, finalization stops before workbook mutation and reports
the relevant details. A generated-value collision reports the duplicated value
plus every conflicting workbook row or proposed category; it does not silently
renumber or partially write the workbook.

## Code-List Writes

For each approved new category, the application adds exactly one row to the
matching question's reserved `Code` block using this schema:

```text
list_name | value | label:english | label:arabic
```

Categories created by this program use workbook-wide unique values greater than
`100`. Existing choice rows and values are not changed. New rows use the first
available row in the matching question's reserved `Code` block rather than an
unrelated question's block or the global end of the sheet.

Rejected clusters, unresolved answers, noise, rare meanings, and uncertain
existing-choice matches receive no automatic `Code` row or value.

## Respondent Output

Feature 01 retains each answer's exact `Data` source cell but does not define a
respondent-output destination. Feature 07 may write approved respondent
assignments only after that destination and its preservation rules are defined.

- Approved existing-choice and new-category assignments retain the exact respondent `KEY`, source row, source answer column, and source cell mapping.
- Repeated exact answers write to every corresponding respondent row.
- Noise, rare meanings, rejected clusters, and uncertain existing-choice matches receive no automatic respondent output value.
- [INPUT REQUIRED: Define the respondent-output destination and whether existing non-empty output cells are preserved, replaced, validated, or treated as an error.]

## Save and Preservation Behavior

Finalization always writes a separate output workbook; in-place source
modification is invalid. The source workbook is never overwritten by the
finalizer. The output path and overwrite policy are resolved by Feature 01.

The writer must preserve all unrelated workbook sheets, cells, formulas,
styles, workbook structure, and source answer cells. It must not write a
partially finalized workbook as a successful output. If a write or save fails,
the operation reports failure and does not claim a successful coded workbook.

Finalization writes through a temporary output in the destination directory
and publishes it atomically. A preflight or pre-publication failure leaves the
approval reusable. A successful publication creates a receipt under
`./review_receipts/<approval_id>_finalization.json` containing the approval ID,
analysis-run ID, final output path, output SHA-256, and completion timestamp.
Later reuse of that approval is rejected. A pending receipt is created before
publication so a process interruption after publication can compare the exact
output hash and complete the receipt without applying workbook mutations
again.

Macro-enabled workbooks are not supported. The Feature 01 input contract and
Feature 07 output contract accept `.xlsx` only; `.xlsm` and other macro-enabled
formats are rejected before analysis.

## Outputs

- A saved final workbook at the resolved output path after all validations pass.
- A durable finalization receipt that prevents successful approval replay.
- Exactly the approved new `Code` rows and approved respondent-output values.
- No output workbook for incomplete, rejected, stale, invalid, mismatched, or collision-failing approvals.
- A failure that identifies the validation or write conflict without mutating the source workbook.

## Success Looks Like

- A valid complete approval produces one final output workbook at a path
  different from the source workbook.
- The workbook contains exactly one new `Code` row for each approved new
  category and no new row for rejected or unresolved clusters.
- Every approved assignment is written to the exact respondent rows captured
  during ingestion, including all repeated-answer occurrences.
- Existing `Code` rows, source answer cells, unrelated cells, worksheets,
  formulas, styles, and workbook structure remain unchanged except for the
  explicitly approved output changes.
- Missing, partial, stale, mismatched, invalid, or value-colliding approvals
  leave the source workbook unchanged and produce no successful output.
- An end-to-end `pytest` test with a representative workbook and mocked
  provider/review inputs confirms exact `Code` rows, exact respondent-output
  mappings, preservation of unrelated workbook content, and separate-output
  behavior.

## Not Included

- Label generation or review-package preparation, which are Feature 05.
- The analyst review interface and approval capture, which are Feature 06.
- Automatic approval.
- Survey-form updates.
- Translation of source answers.
