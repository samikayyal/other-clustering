# Cluster-First Review Contract

> **Current implementation contract:** New analyses create the delivered
> schema-version-4 analyst workspace slices for opening a review, drafting and
> applying a coding decision, explicitly confirming a group, reviewing net
> changes and completion blockers, explicitly completing and locking the
> artifact with deterministic final category values, selecting and
> atomically moving canonical answers between active groups and Needs attention,
> creating, splitting, and merging active groups, excluding and restoring
> canonical answers, inspecting compact question history, and exactly undoing
> the latest structural mutation, plus navigating the derived review work queue
> through progress counts, question filters, contextual answer search, and Next
> undecided.
> The broader accepted workspace remains defined in
> `context/feature-specs/analyst-editing-workspace.md`; behavior beyond this
> delivered slice is not yet shipped.

## Outcome and boundary

`other-cluster` turns supported SurveyCTO `Other` answers into one UTF-8,
schema-version-4 review JSON file. Analysis creates it at revision `0` with
`status: "in_review"`, immutable automatic-discovery provenance, and a mutable
question workspace. The review file remains the sole output and source of
truth. Schema-version-3 artifacts remain viewable but are always read-only;
there is no migration or upgrade path.

V1 analysis reads only `Survey`, `Code`, and `Data`; the optional read-only
ground-truth evaluation may inspect `Work` only after a review file exists. No
command writes or saves `Work`, and V1 never creates a workbook, CSV, package,
draft, approval, receipt, or finalization artifact. Translation, free-standing
categories, value editing, and
respondent output are out of scope.

## Commands and secrets

```text
other-cluster analyze --input PATH_OR_GOOGLE_SHEETS_URL
other-cluster review --review-file REVIEW_JSON
other-cluster evaluate --review-file REVIEW_JSON
other-cluster evaluate --review-file REVIEW_JSON --ground-truth XLSX_OR_GOOGLE_SHEET
```

`analyze` prints detailed human-readable progress, including stage totals and
per-batch, per-question, and per-cluster completion, to stderr. Its final
machine-readable run summary remains the only output written to stdout.
Gemini diagnostics on stderr include the question, cluster, generation, and
transport-attempt context for every JSON-escaped response body and every
secret-safe provider error. Provider errors expose only the exception type and
HTTP status, when available; they never include API keys or request URLs.

`evaluate` is read-only. It validates one review JSON file and prints one
section per question with canonical-answer cluster counts and sizes, clustered
versus unresolved percentages, largest-cluster share, representative member
texts, and the persisted Gemini acceptance, rejection, or provider-error result
for each cluster. Percentages use canonical answer texts as their denominator;
exact duplicate responses remain visible through each answer's occurrence count
in the review file.

With `--ground-truth`, `evaluate` additionally reads the reference workbook's
`Work` tab strictly as benchmark data. It aligns rows by `KEY`, reads each
question's raw / `_Coded` / `_C1` triplet, and reports label-invariant Adjusted
Rand Index plus pairwise precision, recall, and F1 for canonical answer texts
and respondent occurrences. Blank human codes, missing keys, source-text
mismatches, sentinel ground-truth codes `-9998` and `-9999`, and conflicting
duplicate-text codes are excluded and reported. The report also includes
equal-question-weight canonical-answer ARI and pairwise metrics across
questions with at least one aligned answer.
This evaluation-only path never supplies `Work` values to analysis,
representation, clustering, classification, review, or completion.

Ground truth is developer-only evaluation input. The `review` command does not
accept it, and the analyst workspace contains no ground-truth metrics, groups,
drawers, filters, labels, or review input.

Only `NEBIUS_API_KEY` and `GEMINI_API_KEY` are loaded from the process
environment or an optional current-directory `.env`. Nebius supplies
Qwen semantic embeddings for discovery; Gemini classifies the resulting fixed
clusters. There is no TOML,
ordinary `OTHER_CLUSTER_*` setting, output flag, overwrite flag, or
finalization command. Google Sheets exports use the operating system temporary
directory and are cleaned up after the run.

## Workbook ingestion

Required headers are `Survey(type, name, label:english, label:arabic)`,
`Code(list_name, value, label:english, label:arabic)`, and `Data(KEY` plus
supported answer columns). Fixed headers are case-insensitive; dynamic question
IDs are case-sensitive. `Code.list_name` is the exact Data-column identifier;
deterministic normalization is only for matching `Survey.name` metadata. The
`_other` suffix is removed for that lookup; `_exp` and `_explain` try both the
exact ID and the suffix-stripped ID before applying numeric-separator
normalization.

`value: -96`, `-9999`, and `-9998` are excluded from existing choices.
One-sided bilingual labels use the nonblank side;
two blank labels are invalid. Blank or HTML-empty answers are skipped; numeric
answers are warned and skipped; formula, merged, and error cells are invalid.
Hidden Data rows are processed. Original-language answer text is retained,
exact duplicates are canonicalized once per question, and each canonical answer
retains its occurrence count and complete respondent/cell mappings.

## Analysis pipeline

1. Represent every answer in a question with at least two canonical texts using
   `Qwen/Qwen3-Embedding-8B` through Nebius. Each answer receives an
   instruction-aware clustering vector. Questions with 2-20 or 51-100 answers
   also receive an answer-only vector. Exact provider inputs and validated unit
   vectors are cached in `./embedding_cache/cache.sqlite3`; missing vectors
   require `NEBIUS_API_KEY`, while fully cached runs do not.
2. Independently build normalized Arabic and Unicode character TF-IDF features
   over 2-5 character word-boundary n-grams. Reduce each question to at most 50
   deterministic SVD components (seed 42), capped by its answer and feature
   counts.
3. Cluster every question independently with an observable answer-count policy:
   2-20 answers use equal answer-only and instruction-aware semantic distance,
   complete linkage, and threshold `0.60`; 21-50 use 20% lexical and 80%
   instruction-aware semantic distance, average linkage, and threshold `0.40`;
   51-100 use equal answer-only and instruction-aware semantic distance,
   average linkage, and threshold `0.475`; 101-200 use 40% lexical and 60%
   instruction-aware semantic distance, average linkage, and threshold `0.55`;
   larger questions use 60% lexical and 40% instruction-aware semantic
   distance, average linkage, and threshold `0.70`. A proposal requires two
   distinct canonical texts; singleton clusters remain unresolved. Embedding
   or cache failure stops analysis before review creation.
4. Call Gemini `gemini-3.5-flash-lite` once for each proposal-eligible fixed
   cluster, pacing all requests and transport retries at no more than 15 per
   rolling 60 seconds per process. It may select a same-question choice,
   propose one valid bilingual category, or reject the cluster. Transport
   exhaustion becomes a safe, reviewable provider-error warning. Exhausting
   corrective generations for locally invalid responses instead leaves the
   cluster unresolved with an invalid-response warning; it is not reported as
   a provider outage. Arabic category labels may contain ASCII or Arabic-Indic
   digits when they also contain Arabic letters.
5. Write a strict schema-version-4
   `./reviews/<normalized_source_stem>_<analysis_run_id>.json` with the source
   byte size and SHA-256.

Provider responses, workbooks, and cached vectors are validated at their
boundaries. Synchronous frozen stage results are trusted; persisted review JSON
and browser HTTP input are validated strictly.

## Version-4 review workspace

`questions[].answers` is the sole detailed canonical-answer store: text,
occurrence count, row mappings, and discovery evidence live there. Immutable
`automatic_groups` retain analyzed membership and provider proposals. Each
question's mutable `workspace` contains active groups, Needs attention,
exclusions, retired groups, compact history, and transient Undo storage.

Every automatic group starts `needs_review`. A valid provider proposal for a
same-question existing choice or bilingual new category prefills the saved
decision without confirming it. Rejected, invalid, or failed proposals do not
prefill a decision. Canonical answers outside automatic groups start in Needs
attention. Version 4 has no analyst identity or attribution fields.

The browser holds at most one local decision draft. Discarding it does not
change durable state. Applying a valid existing-choice or bilingual
new-category decision sends one narrow `apply_decision` command with the
browser's expected revision. Explicit confirmation sends a separate
`confirm_group` command. Each successful command increments the global
revision and atomically persists current state plus compact history. A stale
revision returns a conflict and never replays or overwrites newer state. The
browser cannot submit a replacement review document.

Within one question, accessible checkbox and action-bar controls can select
whole canonical answers across active groups and Needs attention. The action
bar shows selected unique-answer and affected respondent-response counts before
one revision-checked `move_answers` command transfers them to an active group
or Needs attention. Every respondent occurrence follows its canonical answer.
Affected non-empty groups preserve their decisions and return to
`needs_review`; emptied source groups retain their evidence and decision as
retired groups. Membership remains exhaustive and exclusive, and group,
group-identity, and canonical-answer ordering remain stable. Successful moves
clear the browser selection and persist compact before/after history atomically.

The same selection can create a reviewer group through one revision-checked
`create_group` command. Reviewer groups append in stable creation order, may
contain a single canonical answer, start `needs_review`, and have no decision;
they never inherit a source decision. A `merge_groups` command moves every
member of one active group into a same-question destination, retires the source,
preserves only the destination decision, and resets the destination to
`needs_review`. Create, split, merge, and retirement evidence is recorded in
compact history without changing automatic-discovery provenance.

The same active selection can exclude canonical answers without a reason or
reason-related schema field. Excluded answers occupy their own resolved
location, use a separate Restore-only selection mode, and are omitted from
outstanding work. Restore always moves selected excluded answers to Needs
attention; it never reinstates earlier membership or decisions. The collapsible
Excluded section shows unique-answer and respondent-response totals plus the
latest exclusion timestamp recorded in question history.

Every successful move, create, split, merge, exclusion, or restoration replaces
the one available immediate Undo payload. Undo is revision-checked, restores
the exact prior memberships, decisions, active and retired groups, stable
positions, and review states, then appends its own compact history event.
Decision changes and confirmations clear an older Undo opportunity. Refresh or
browser close loses the browser affordance, and completed artifacts may not
retain the transient payload. History contains IDs, locations, applicable
before/after decisions, timestamps, and impact counts without duplicating raw
answer text, row mappings, discovery evidence, or provider payloads.

The review sidebar derives resolved and remaining heterogeneous item counts,
total unique-answer and respondent-response counts, and complete-question
progress without persisting presentation state. Status is one of All, Not
started, In progress, or Complete; Modified, Has exclusions, and Provider
warning are independent AND-combined filters. Modified compares current state
with immutable analyzed provenance, so an exact Undo removes the flag while its
coding-relevant history keeps the question In progress. Provider-warning
provenance follows affected canonical answers into current groups, Needs
attention, and exclusions.

Current-question answer search performs case-insensitive Unicode substring
matching only on canonical-answer text, preserves section and group context,
expands matching collapsed sections, highlights matches, and retains selections
hidden by a later query. Next undecided follows the filtered workbook-order
queue, visits needs-review groups before individual Needs attention answers,
clears answer search to reveal its target, wraps once, and reports when the
filtered view has no undecided target. The progress bar remains based only on
complete questions out of total questions; there is no size-based filter,
warning, or completion effect.

Review changes is a read-only projection available throughout editing. It
reports outstanding work, net current moves and respondent impact,
reviewer-created and retired original groups, exclusions, invalidated
confirmations, blocking failures, and non-blocking similar-label and provider
cautions. Undo-restored structure does not inflate the net current totals.

Finish review opens that same projection after all questions are complete. A
separate confirmed Complete and lock review command increments the revision,
allocates each confirmed active new category the smallest unused same-question
integer above 100 in stable creation order, persists the final summary and UTC
completion timestamp, clears transient Undo state, and makes all later mutation
commands fail read-only. Existing-choice values are retained and exclusions do
not block completion.
