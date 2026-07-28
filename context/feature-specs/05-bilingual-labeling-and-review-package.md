# Feature 05: Bilingual Labeling and Review-Package Preparation

## Objective

Turn discovered clusters into proposed bilingual categories, allocate workbook-wide unique proposed values, and prepare the complete review package. This feature performs no workbook mutation. Feature 06 reviews the package and Feature 07 applies approved changes after a complete structured approval.

## Detailed Description

### New-Category Labeling

For each accepted cluster from Feature 04, the application sends Gemini enough original-language member answers and question context to generate:

- one concise English category label; and
- one concise Arabic category label.

The request includes the question ID, bilingual question text, every existing
choice for that question, and a deterministic selection of the cluster's
distinct accepted member answers. Each selected answer includes its exact
Feature 01-cleaned text, occurrence count, and HDBSCAN membership probability.
Respondent keys and workbook cell locations are review evidence and are not
sent to Gemini for labeling.

When a cluster contains at most `50` distinct accepted member answers, all of
them are sent. For a larger cluster, the application sends `50` distinct
answers: the `25` members with the highest accepted membership probabilities
and the `25` members with the lowest accepted membership probabilities.
Ties are ordered by stable processing-answer ID. This deterministic core-and-
boundary sample exposes both the strongest examples and the least certain
accepted members. Random sampling is not used because it would make identical
runs produce different prompts and potentially different labels.

The direct Google Gemini API model is `gemini-3.5-flash`, and its response must
use Gemini's schema-constrained structured-output support described in [Gemini
structured output](https://ai.google.dev/gemini-api/docs/structured-output?hl=en).
Free-form text followed by application-side JSON parsing is not sufficient.
Labels describe the common meaning of the cluster; they must not translate or
alter the source answers.

Gemini returns this structured JSON object:

```json
{
  "decision": "label | reject",
  "english_label": "string | null",
  "arabic_label": "string | null",
  "rejection_reason": "mixed_meanings | insufficient_common_meaning | unsafe_to_label | null"
}
```

All four fields are required and additional fields are forbidden. For
`decision: "label"`, both labels must be non-empty strings and
`rejection_reason` must be null. For `decision: "reject"`, both labels must be
null and `rejection_reason` must be one of the three defined reason codes. A
valid rejection becomes rejected-cluster evidence in the review package; its
members remain unresolved and receive no proposed value.

The prompt requires Gemini to verify that the selected members have one
coherent common meaning before labeling them. It must reject a cluster when
the selected evidence mixes meanings, does not provide enough common meaning,
or cannot be labeled safely. It must not force a generic label merely to
produce a category.

Each label must contain between `1` and `6` words after trimming and collapsing
internal whitespace. Wording must be short, professional, plain, and specific
to the shared meaning rather than ornate or academic. English labels use Latin
letters; digits, spaces, apostrophes, and hyphens are allowed when meaningful.
Arabic labels use Arabic script without diacritical marks. Arabic should use
clear formal wording by default, while a familiar Jordanian term may be used
when it is the most faithful concise expression of the members' shared
meaning. English labels use normal title capitalization rather than all caps.

The labels `Other`, `Miscellaneous`, `Various`, `Unknown`, `Unclear`, their
Arabic equivalents, cluster numbers, internal IDs, respondent identifiers, and
labels containing unsupported personal or sensitive details are prohibited.
Clusters are labeled in ascending `(question_id, cluster_id)` order.
After Unicode normalization, case folding for English, Arabic-diacritic
removal, punctuation removal, and whitespace collapse, neither side may exactly
duplicate an existing choice label for the same question or another proposed
new-category label for that question. A possible semantic overlap that is not
an exact normalized duplicate is retained as a review warning rather than
being treated as a mechanically provable error; the analyst decides whether
the meanings truly overlap.

The application detects objectively invalid or low-quality output through the
structured-response cross-field rules, non-empty and word-count checks, script
checks, prohibited-label checks, exact normalized duplicate checks, and the
model's explicit coherence decision. Subjective quality beyond those checks
cannot be reliably automated and remains part of analyst review.

An invalid, empty, script-invalid, prohibited, duplicate, unsafe-content
`label` decision, or otherwise mechanically low-quality label result is
regenerated with the failed validation reasons included in the corrective
prompt. Feature 05 allows the initial generation plus two corrective
generations for that cluster. Each generation uses the established Gemini
transient-transport retry policy. If all three generations fail validation,
Feature 05 fails without emitting a successful partial review package. A
schema-valid `decision: "reject"`, including `unsafe_to_label`, is not retried
because it is a valid coherence outcome, not a bad label response.

Feature 05 labels and allocates values for the individual proposed clusters
that exist before analyst review. A confirmed merge must still be represented
as one category with one English label, one Arabic label, and one value, and
its component clusters must not produce separate approved `Code` rows.

Feature 05 does not make extra Gemini calls or allocate extra values for
possible merge combinations. It emits the individual proposed categories and
Feature 04's pairwise merge suggestions. Feature 06 resolves approved merges
using these rules:

- approved merge suggestions are treated as undirected edges between clusters;
- all clusters connected by approved edges form one merged category;
- the merged category contains the deduplicated union of every component
  cluster's processing-answer and row-level member IDs;
- the merged category keeps the smallest proposed value among its component
  clusters;
- the other component values become unused gaps and are not reallocated to
  another proposal in the same run;
- the label pair belonging to the retained smallest-value component is the
  default merged label, but the analyst must explicitly confirm it or provide
  an edited final English and Arabic label;
- the final merged labels must pass the same length, script, prohibited-label,
  and exact-normalized-duplicate checks as generated labels; and
- component categories receive a `merged` disposition and cannot also be
  separately approved or rejected.

Overlapping approvals are transitive. Approving `A-B` and `B-C` creates one
`A+B+C` category. If a merge suggestion between any two clusters in that
connected group was explicitly rejected, the approval is inconsistent and
cannot be completed until the analyst revises the conflicting disposition.
Approving a merge that includes a separately rejected component category is
also invalid.

### New Code Allocation

Every proposed and successfully labeled new category receives a proposed integer value greater than `100`. A typical first row is:

```text
B5_other | 101 | Lebanese | لبناني
```

- Generated values must be unique across the entire workbook, regardless of `list_name`.
- `101` is the conventional first allocation candidate but is not a required starting value.
- Allocation considers all existing workbook values greater than `100` plus every value proposed in the current run and selects an unused value.
- A detected duplicate is a fatal pre-write error. The application reports the duplicated value and every conflicting existing row or proposal; it does not silently renumber after detecting the collision.
- Proposed clusters are allocated in ascending `(question_id, cluster_id)`
  order. For each cluster in that order, the allocator selects the smallest
  unused integer greater than `100`. This is the deterministic ordering rule:
  it prevents the same set of clusters from swapping values merely because a
  dictionary, provider response, or internal collection was traversed in a
  different order.

### Review-Package Preparation

The labeling stage completes all provider calls, label validation, value
allocation, and assignment validation before emitting a structured review
package. The package contains the proposed categories, labels, allocated
values, existing-choice assignments, exact respondent-row mappings, merge
suggestions, and every unresolved case required by Feature 06.

The package is serialized through Feature 06's version `1` UTF-8 JSON contract
under `./review_packages`. Feature 05 generates the analysis-run UUID, computes
the exact source-XLSX byte length and SHA-256 fingerprint, builds every
question-scoped review item and row reference, validates all cross-references
and unique review-item IDs, and writes the file only after the complete package
is valid. A failed build leaves no partial package. The CLI prints the absolute
package path and compact counts rather than printing raw respondent answers to
the terminal.

Feature 05 has no authority to mutate the source workbook or create the final
output workbook. The source workbook remains unchanged while the package is
prepared; extracted answer text retains its original language and Feature
01's HTML-tag cleanup.

## Outputs

- A structured review package containing proposed English and Arabic labels, workbook-wide unique values, member answers, existing-choice assignments, exact respondent-row mappings, and all unresolved cases.
- No workbook mutation or output-workbook save.
- A package and deterministic allocation result that Feature 06 can review and Feature 07 can validate during finalization.

## Success Looks Like

- Every cluster that passes Gemini's coherence decision and local label
  validation has exactly one English label, one Arabic label, and one
  workbook-wide unique proposed integer value greater than `100`.
- The source workbook has no new `Code` rows or application-written respondent output values after Feature 05.
- Every emitted proposed category has exactly one bilingual label and one
  workbook-wide unique value greater than `100`; a coherently rejected cluster
  remains unresolved review evidence and receives neither.
- Existing-choice and new-category proposals retain exact respondent-row mappings for review and later finalization.
- Repeated answers retain all corresponding respondent rows in the package.
- Noise, rare meanings, and uncertain answers follow the agreed unresolved policy and are not silently forced into categories.
- Source answer cells, existing code rows, unrelated cells, worksheets, formulas, and styles remain unchanged.
- An end-to-end `pytest` test with a representative workbook and mocked Nebius/Gemini responses confirms exact labels, allocations, review-package contents, and respondent-row mappings.

The Feature 05 labeling, allocation, package, and cross-feature merge contracts
are fully specified. Full end-to-end acceptance still depends on Feature 06's
analyst-response contract and Feature 07's respondent-output destination.

## Not Included

- The analyst review interface and approval gate, which are Feature 06.
- Writing `Code` rows, writing respondent output values, and saving the final workbook, which are Feature 07.
- Survey-form updates.
- Translation of source answers.
- Categories outside the labeling and review-package rules defined here.
