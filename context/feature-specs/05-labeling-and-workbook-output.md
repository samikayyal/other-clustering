# Feature 05: Labeling and Workbook Output

## Objective

Turn discovered clusters into proposed bilingual categories, allocate workbook-wide unique proposed values, and prepare all workbook changes for the analyst-review gate. No workbook coding result is written until Feature 06 returns a complete structured approval.

## Detailed Description

### New-Category Labeling

For each accepted cluster from Feature 04, the application sends Gemini enough original-language member answers and question context to generate:

- one concise English category label; and
- one concise Arabic category label.

The direct Google Gemini API model is `gemini-3.5-flash`, and its response must use a structured schema. Labels describe the common meaning of the cluster; they must not translate or alter the source answers.

When a merge suggestion is confirmed by the analyst, the merged member set is represented as one category with one English label, one Arabic label, and one workbook-wide value. The component clusters do not produce separate approved code-list rows for that merge.

- [INPUT REQUIRED: Define the structured labeling response schema.]
- [INPUT REQUIRED: Define how many and which member answers are included when a cluster is too large for one prompt.]
- [INPUT REQUIRED: Define label length, wording, script, capitalization, and dialect/formal-Arabic rules.]
- [INPUT REQUIRED: Define prohibited labels, including whether a generated label may duplicate or overlap an existing choice or another new category.]
- [INPUT REQUIRED: Define whether Gemini must verify cluster coherence and may reject a cluster before labeling.]
- [INPUT REQUIRED: Define what happens after an invalid, empty, duplicate, unsafe, or low-quality label response.]

### New Code Allocation

Every proposed and successfully labeled new category receives a proposed integer value greater than `100`. A typical first row is:

```text
B5_other | 101 | Lebanese | لبناني
```

- Generated values must be unique across the entire workbook, regardless of `list_name`.
- `101` is the conventional first allocation candidate but is not a required starting value.
- Allocation considers all existing workbook values greater than `100` plus every value proposed in the current run and selects an unused value.
- A detected duplicate is a fatal pre-write error. The application reports the duplicated value and every conflicting existing row or proposal; it does not silently renumber after detecting the collision.
- [INPUT REQUIRED: Define deterministic ordering when multiple new categories receive values in the same run.]

### Code-List Writes

After complete analyst approval, the application adds one row per approved new category to the `Code` sheet using this exact schema:

```text
list_name | value | label | label:arabic
```

Categories created by this program use workbook-wide unique values greater than `100`; the application must not change existing choice rows or values. New rows use the first available row in the matching question's reserved `Code` block.

### Respondent Writes

After complete analyst approval, the application writes each approved existing-choice or new-category English label to the `_Coded` column paired with the original answer. The stable answer-to-cell mapping from Feature 01 is authoritative, and the adjacent `_C1` formula remains unchanged.

- `_Coded` stores the approved English `Code.label`, not the numeric value.
- Noise, rare meanings, rejected clusters, and uncertain existing-choice matches receive no automatic `_Coded` value. Their cells remain unchanged unless the analyst explicitly assigns and approves a category.
- [INPUT REQUIRED: Define whether existing non-empty `_Coded` cells are preserved, replaced, validated, or treated as an error.]

### Save Behavior

All provider calls, labels, allocations, and assignment validations complete before a structured review package is produced. Feature 05 does not authorize workbook mutation by itself. Feature 06 must return a complete structured analyst approval tied to the same analysis run and source workbook before finalization begins. A failure must not be presented as a successful partially coded workbook. Source answer text and unrelated workbook content remain unchanged.

The output path and overwrite policy are defined by Feature 01. Finalization always writes a separate output workbook; the source and output paths may not be the same. An existing output path causes failure unless overwrite was explicitly enabled through the resolved run settings.
- A complete structured analyst approval is mandatory before values are committed.
- The structured review package and matching analyst response form the required review record.

## Outputs

- A structured review package containing proposed English and Arabic labels, workbook-wide unique values, member answers, existing-choice assignments, and all unresolved cases.
- No workbook mutation before Feature 06 returns complete approval.
- After approval, new code-list rows that follow the exact workbook schema.
- After approval, `_Coded` labels written to the exact respondent rows for all analyst-approved assignments.
- After approval, a saved workbook at the agreed destination.

## Success Looks Like

- Every proposed new cluster has exactly one English label, one Arabic label, and one workbook-wide unique proposed integer value greater than `100`.
- Before complete approval, the source workbook has no new `Code` rows and no application-written `_Coded` values.
- Missing, partial, stale, or invalid approval prevents all workbook mutation.
- The workbook contains exactly one new code-list row for each accepted new category and no new row for rejected/unresolved clusters.
- Existing-choice and new-category assignments write the approved English label; the preserved `_C1` formula resolves its numeric value.
- Every written `_Coded` cell belongs to the same source answer and respondent row that produced the assignment.
- Repeated answers populate all corresponding respondent rows.
- Noise, rare meanings, and uncertain answers follow the agreed unresolved policy and are not silently forced into categories.
- Source answer cells, existing code rows, unrelated cells, worksheets, formulas, and styles remain unchanged except where the agreed append/write behavior necessarily applies.
- The source workbook is recoverable according to the agreed save policy.
- An end-to-end `pytest` test with a representative workbook and mocked Nebius/Gemini responses confirms exact new code rows and exact `_Coded` cell values.

Full acceptance cannot be tested until the review schemas, deterministic allocation ordering, and remaining labeling decisions are supplied.

## Not Included

- The analyst review interface itself, which is Feature 06.
- Survey-form updates.
- Translation of source answers.
- Categories outside the output rules defined here.
