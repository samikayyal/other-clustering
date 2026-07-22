# Feature 06: Analyst Review Web Application and Approval Gate

## Objective

Provide a web application in which an analyst reviews every categorization result and explicitly confirms the complete run before any new `Code` row or respondent output value is written to the workbook.

This feature is a mandatory safety and quality gate, not an optional reporting screen. Feature 05 may prepare proposed workbook changes, but only a complete structured approval from Feature 06 authorizes finalization.

## Delivery Sequence

The review contract is delivered in two stages:

1. **Interim terminal workflow** — `other-cluster` prints a structured review package to the terminal. The analyst reviews it and supplies a matching structured approval response to a separate finalization step. The analysis command never pauses for interactive input.
2. **Review web application** — the web application presents the same logical review package through a browser and emits the same logical structured approval after the analyst completes every required decision.

The interim and web workflows must enforce the same completeness and validation rules so the web application does not change the meaning of approval.

[INPUT REQUIRED: Define the exact CLI mechanism for supplying the interim structured analyst response, such as a JSON file argument or standard input to a separate finalization command.]

## Review Package

Each review package must be tied to one analysis run and one exact source workbook. At minimum it contains:

- an analysis run ID;
- a source-workbook identity or fingerprint;
- every supported question ID and bilingual question text;
- every respondent answer with its stable `KEY` and workbook row mapping;
- each proposed existing-choice assignment and the evidence used to propose it;
- each proposed new category with its English label, Arabic label, workbook-wide unique value greater than `100`, member answers, and available clustering evidence;
- each system-generated semantic-merge suggestion, including the proposed source clusters and combined member set;
- every noise point, rare one-off meaning, rejected cluster, and uncertain existing-choice match; and
- validation errors that prevent the package from being reviewable.

The review package has no authority to mutate the workbook.

[INPUT REQUIRED: Define the exact structured review-package schema and serialization format.]

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

At minimum, the analyst must explicitly approve or reject every proposed assignment and new category, explicitly confirm or reject every merge suggestion, and explicitly acknowledge every unresolved answer. The analyst may not approve the run while any item lacks a disposition.

[INPUT REQUIRED: Define whether the analyst may edit bilingual labels, move answers between categories, create a category manually, split a cluster, or assign an unresolved answer to an existing category.]

The system proposes merges for semantically overlapping clusters. The analyst must explicitly confirm a merge before it is applied. An approved merge becomes one category with one English label, one Arabic label, one workbook-wide value, and one combined member set.

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

## Finalization Gate

Before writing, the finalizer must validate all of the following:

1. The approval belongs to the same analysis run and source workbook.
2. Every review item has an explicit analyst disposition.
3. Every approved assignment refers to an allowed existing choice or an approved new category.
4. Every approved new category has an English label, Arabic label, and integer value greater than `100`.
5. Every generated value greater than `100` is unique across the entire workbook and approval package.
6. The source workbook has not changed in a way that invalidates row mappings, `Code` blocks, or allocated values.

If a value collision exists, finalization stops and reports the duplicated value plus every conflicting workbook row or proposed category. It does not silently renumber or partially write the workbook.

Only after every validation passes may the finalizer:

- add approved new rows to the matching reserved blocks in `Code`;
- apply approved respondent results through the output destination defined by the later output contract; and
- save the final output workbook according to the agreed output policy.

Noise, rare meanings, rejected clusters, and uncertain matches receive no automatic value. Their source cells remain unchanged unless the analyst explicitly assigns and approves a category through the later output contract.

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
- For a valid complete approval, authorization for one finalization attempt and the resulting coded workbook.

## Success Looks Like

- The interim CLI prints a structured package containing every item that requires review without prompting during analysis.
- The web application presents the same complete review scope in a question-centered browser interface.
- The analyst cannot confirm the run while any assignment, new category, or unresolved answer lacks a disposition.
- No `Code` or respondent output cell changes before complete approval.
- A partial, stale, malformed, or mismatched response fails with details and leaves the workbook unchanged.
- A generated-value collision fails with the duplicated value and all conflicting rows or proposals.
- A valid complete response results in exactly the analyst-approved `Code` rows and respondent output records.
- Raw answers and unrelated workbook content remain unchanged.
- Automated tests cover terminal-package completeness, approval completeness, stale/mismatched approvals, value collisions, zero-write failures, and successful finalization.

## Not Included

- Automatic approval.
- Writing any coding result before full analyst confirmation.
- Translation of respondent answers.
- General survey editing.
- Collaboration or administration features not explicitly selected above.
