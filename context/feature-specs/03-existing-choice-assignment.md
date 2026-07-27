# Feature 03: Conservative Existing-Choice Assignment

## Objective

Assign an answer to one of its question's already existing choices only when the meaning is sufficiently plausible and a structured Gemini decision verifies the match. Answers that cannot be safely assigned remain available for new-category discovery.

## Detailed Description

This feature consumes the original answer records, their validated unit-length
embeddings, and the existing choices extracted for the same question. It must
never compare or assign an answer to choices belonging to another question.

Gemini receives every allowed existing choice belonging to the answer's
question. There is no semantic shortlist, existing-choice labels are not
embedded, and no cosine candidate count or threshold is used.

For an answer with allowed choices to evaluate, the application calls the
stable Gemini Interactions API through the official `google-genai` Python SDK
using `gemini-3.5-flash`. The client explicitly selects API version `v1`.
`GEMINI_API_KEY` is loaded from the process environment or optional `.env` file
and passed explicitly to the SDK client. The application does not accept
`GOOGLE_API_KEY` as an alternative credential name.

The SDK request must use Gemini's schema-constrained structured-output support,
as documented in [Gemini structured
output](https://ai.google.dev/gemini-api/docs/structured-output?hl=en). The
application must receive the decision through that structured response
contract; asking for free-form JSON and parsing it afterward is not sufficient.

The prompt includes the bilingual question text, the exact original answer, and
every allowed existing choice with its exact stored value and bilingual labels.
Gemini returns this structured JSON decision:

```json
{
  "decision": "assign | no_match",
  "selected_choice_value": "integer | null"
}
```

Both fields are required and additional fields are forbidden. `decision` is an
enum with exactly `assign` and `no_match`. For `assign`,
`selected_choice_value` must be an integer that maps to exactly one choice
supplied in the same request. For `no_match`, `selected_choice_value` must be
null. The application validates these cross-field and allowed-choice rules
after schema parsing; a schema-valid but semantically invalid response is an
invalid provider result. It stops Feature 03 without reporting a successful
partial assignment set or continuing to discovery. Gemini returns no confidence
score and no reason.

No sampling parameters are sent; the selected model's defaults apply. Each SDK
request has a `120`-second timeout per attempt and at most five total attempts,
including the initial request. Retries use exponential backoff with an initial
delay of approximately `1` second, multiplier `2`, maximum delay `60` seconds,
and jitter. Only timeouts, network failures, HTTP `408`, `429`, and `5xx`
responses are retried. Authentication errors, malformed requests, schema
violations, and semantically invalid structured decisions are not retried.

The prompt enforces this conservative meaning rule: assign only when exactly
one supplied choice captures the answer's complete asserted meaning. Gemini
must return `no_match` for ambiguity, respondent uncertainty, negation, partial
or merely related overlap, multiple meanings that one choice does not fully
represent, insufficient context, or more than one plausible choice. For
example, if `Lebanese` is an allowed choice, a direct statement or synonym may
be assigned, while `not Lebanese`, `maybe Lebanese`, `Lebanese and Syrian`,
`Arab`, `from Beirut`, and `Lebanese mother` remain unmatched unless one
supplied choice captures the complete asserted meaning.

The exact Feature 01-cleaned answer, bilingual question text, and every
bilingual existing-choice label and stored value are approved for transmission
to Google Gemini. No translation or redaction beyond Feature 01's HTML-tag
cleanup is applied.

Duplicate existing-choice values within one question are a workbook error
detected before any Gemini request for that question. The structured response
identifies a choice by its stored value, so one value must identify exactly one
choice within the question. Reusing the same stored value in different
questions remains valid.

When a question has no allowed existing choices after excluding the "Other"
choice, the application makes no Gemini request for that question and passes
its answers unchanged to Feature 04.

Gemini is not allowed to invent a choice, rewrite a stored choice value, or
generate a new category in this feature. A valid `no_match` decision passes the
answer to discovery. A response that names an unavailable choice, violates the
schema, or violates the cross-field rules is a provider failure that stops the
stage after the configured request retries have already been exhausted where
applicable; it is not converted into an ordinary `no_match`.

Accepted assignments retain the exact stored value of the existing choice for the later output stage. Rejected and uncertain answers are passed unchanged to Feature 04.

This feature runs before discovery. Only answers that Gemini rejects or cannot
safely match form Feature 04's discovery input; accepted existing-choice
assignments do not proceed to discovery.

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
- Ambiguous or uncertain meanings produce a valid `no_match` and do not force
  an assignment; invalid or out-of-schema provider responses stop the stage.
- Rejected answers remain mapped to their exact respondent rows and continue to discovery without text modification.
- Repeated answers receive one shared Gemini decision per question/text key, while retaining every respondent row through the row-level fan-out mapping.
- Mocked-provider tests cover an accepted match, rejection, ambiguity, an invented choice, a malformed response, and question-boundary isolation.

Every exact duplicate occurrence within a question shares one existing-choice
decision. Gemini evaluates the canonical question/text processing item once,
and an accepted or `no_match` result is fanned out to all row-level answer
records with that key. An invalid provider result stops the stage and is not
fanned out as a discovery result.

## Not Included

- Creating or labeling new categories.
- PCA or density clustering.
- Allocating values greater than `100`.
- Workbook mutation.
