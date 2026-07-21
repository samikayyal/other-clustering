# Feature 03: Conservative Existing-Choice Assignment

## Objective

Assign an answer to one of its question's already existing choices only when the meaning is sufficiently plausible and a structured Gemini decision verifies the match. Answers that cannot be safely assigned remain available for new-category discovery.

## Detailed Description

This feature consumes the original answer records, their normalized embeddings, and the existing choices extracted for the same question. It must never compare or assign an answer to choices belonging to another question.

The supplied plan does not define whether Gemini receives every allowed existing choice for the question or a semantic shortlist. That decision affects whether existing choice labels also need embeddings and cosine candidate selection.

- [INPUT REQUIRED: Decide whether Gemini evaluates every existing choice for the question or only a candidate shortlist.]
- [INPUT REQUIRED: If a shortlist is used, decide whether existing-choice labels are embedded with Nebius, which label fields are embedded, and the candidate count and/or cosine threshold.]
- [INPUT REQUIRED: If a shortlist is used, define behavior when no choice passes the candidate-selection rule.]

For an answer with allowed choices to evaluate, the application calls the direct Google Gemini API using `gemini-3.5-flash`. The prompt includes the question text, the exact original answer, and the allowed existing choices selected by the agreed rule. Gemini returns a structured decision that either selects exactly one supplied existing choice or marks the answer as not safely matched.

The verification contract remains incomplete:

- [INPUT REQUIRED: Provide the Gemini API endpoint/version and API-key environment variable name.]
- [INPUT REQUIRED: Define the structured response schema and which field identifies the selected existing choice.]
- [INPUT REQUIRED: Define the conservative decision criteria that the prompt must enforce, including treatment of ambiguity, partial overlap, negation, and multi-meaning answers.]
- [INPUT REQUIRED: Define sampling settings and timeout/retry behavior.]
- [INPUT REQUIRED: Decide whether Gemini returns a confidence or reason and whether either affects acceptance.]

Gemini is not allowed to invent a choice, rewrite a stored choice value, or generate a new category in this feature. A response that names an unavailable choice, violates the schema, or expresses uncertainty does not produce an existing-choice assignment.

Accepted assignments retain the exact stored value of the existing choice for later writing to `_Coded`. Rejected and uncertain answers are passed unchanged to Feature 04.

[INPUT REQUIRED: Confirm that this feature runs before discovery and that rejected answers, rather than all answers, form the discovery input.]

## Outputs

- Existing-choice assignments keyed by stable answer ID.
- The exact stored choice value for each accepted assignment.
- An unchanged set of unassigned answer IDs for discovery.
- Structured verification results sufficient to distinguish accepted, rejected, and invalid provider responses during the run.

## Success Looks Like

- An answer is considered only against choices belonging to its own question.
- The "Other" choice is never an assignment target.
- Gemini can select only from the candidate values supplied in the request or explicitly reject all of them.
- Accepted assignments preserve the workbook's exact existing-choice value.
- Ambiguous, uncertain, invalid, or out-of-schema responses do not force an assignment.
- Rejected answers remain mapped to their exact respondent rows and continue to discovery without text modification.
- Repeated answers receive one shared Gemini decision per question/text key, while retaining and populating every destination row through the row-level fan-out mapping.
- Mocked-provider tests cover an accepted match, rejection, ambiguity, an invented choice, a malformed response, and question-boundary isolation.

Every exact duplicate occurrence within a question shares one existing-choice decision. Gemini evaluates the canonical question/text processing item once, and an accepted, rejected, uncertain, or invalid result is fanned out to all row-level answer records with that key.

## Not Included

- Creating or labeling new categories.
- PCA or density clustering.
- Allocating values greater than `100`.
- Workbook mutation.
