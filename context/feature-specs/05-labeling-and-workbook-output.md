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
list_name | value | label:english | label:arabic
```

Categories created by this program use workbook-wide unique values greater than `100`; the application must not change existing choice rows or values. New rows use the first available row in the matching question's reserved `Code` block.

### Respondent Output Boundary

Feature 01 retains each answer's exact `Data` source cell but does not expose a
respondent-output destination. After complete analyst approval, this feature
may prepare approved assignment records, but it must not write respondent cells
until a replacement output destination and its preservation rules are defined.

- Noise, rare meanings, rejected clusters, and uncertain existing-choice matches receive no automatic respondent output value.
- [INPUT REQUIRED: Define the respondent-output destination and whether existing non-empty output cells are preserved, replaced, validated, or treated as an error.]

### Save Behavior

All provider calls, labels, allocations, and assignment validations complete before a structured review package is produced. Feature 05 does not authorize workbook mutation by itself. Feature 06 must return a complete structured analyst approval tied to the same analysis run and source workbook before finalization begins. A failure must not be presented as a successful partially coded workbook. Source answer cells and unrelated workbook content remain unchanged; extracted answer text retains its original language and Feature 01's HTML-tag cleanup.

The output path and overwrite policy are defined by Feature 01. Finalization always writes a separate output workbook; the source and output paths may not be the same. An existing output path causes failure unless overwrite was explicitly enabled through the resolved run settings.
- A complete structured analyst approval is mandatory before values are committed.
- The structured review package and matching analyst response form the required review record.

## Outputs

- A structured review package containing proposed English and Arabic labels, workbook-wide unique values, member answers, existing-choice assignments, and all unresolved cases.
- No workbook mutation before Feature 06 returns complete approval.
- After approval, new code-list rows that follow the exact workbook schema.
- After approval, approved assignment records retain the exact respondent rows for the later output writer.
- After approval, a saved workbook at the agreed destination.

## Success Looks Like

- Every proposed new cluster has exactly one English label, one Arabic label, and one workbook-wide unique proposed integer value greater than `100`.
- Before complete approval, the source workbook has no new `Code` rows or application-written respondent output values.
- Missing, partial, stale, or invalid approval prevents all workbook mutation.
- The workbook contains exactly one new code-list row for each accepted new category and no new row for rejected/unresolved clusters.
- Existing-choice and new-category assignments retain the approved English label and exact respondent-row mapping for the later output writer.
- Repeated answers populate all corresponding respondent rows.
- Noise, rare meanings, and uncertain answers follow the agreed unresolved policy and are not silently forced into categories.
- Source answer cells, existing code rows, unrelated cells, worksheets, formulas, and styles remain unchanged except where the agreed append/write behavior necessarily applies.
- The source workbook is recoverable according to the agreed save policy.
- An end-to-end `pytest` test with a representative workbook and mocked Nebius/Gemini responses confirms exact new code rows and exact respondent-row mappings.

Full acceptance cannot be tested until the review schemas, deterministic allocation ordering, and remaining labeling decisions are supplied.

## Not Included

- The analyst review interface itself, which is Feature 06.
- Survey-form updates.
- Translation of source answers.
- Categories outside the output rules defined here.
