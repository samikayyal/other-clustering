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

1. The approval belongs to the same analysis run and source-workbook identity.
2. Every review item has an explicit analyst disposition.
3. Every approved assignment refers to an allowed existing choice or an approved new category.
4. Every approved new category has an English label, Arabic label, and integer value greater than `100`.
5. Every generated value greater than `100` is unique across the entire workbook and approval package.
6. The source workbook has not changed in a way that invalidates row mappings, `Code` blocks, or allocated values.
7. Every approved merge group equals one connected component of approved merge
   edges, uses the union of its component members, retains the smallest
   component proposed value, and has no rejected edge whose endpoints both
   belong to the group.
8. Every merged component has the `merged` disposition and is not separately
   approved or rejected; discarded component values are not reassigned.
9. The output path differs from the source path.
10. An existing output path is used only when overwrite was explicitly enabled.

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

[INPUT REQUIRED: Define whether workbook macros are supported; `openpyxl`
handling differs for `.xlsx` and macro-enabled files.]

## Outputs

- A saved final workbook at the resolved output path after all validations pass.
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
