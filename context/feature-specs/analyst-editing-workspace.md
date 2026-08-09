# Analyst Editing Workspace

## Status

Accepted behavior contract; not yet implemented. Use this document as the
source for the implementation specification and tickets.

## Problem Statement

Reviewers currently receive fixed automatic clusters and can only choose a
coding disposition for each fixed cluster or unresolved answer. They cannot
repair membership, create or merge groups, exclude invalid answers, search and
bulk-select answers, understand respondent impact, or safely recover from an
edit. Progress is therefore hard to interpret and correcting automatic output
requires work outside the review artifact.

## Solution

Replace the immutable schema-version-3 review experience for new analyses with
an accessible schema-version-4 analyst editing workspace. Reviewers can move
canonical answers between active groups and Needs attention, create and merge
groups, exclude and restore answers, explicitly confirm current group decisions,
search and filter questions, inspect complete impact counts, undo the latest
structural edit, and finish through a validated review summary. The server owns
all revisioned mutations and persists compact audit history in the single review
artifact. Ground-truth benchmarking remains a separate developer-only concern.

## User Stories

1. As a reviewer, I want each sidebar question to show resolved and remaining
   work, so that I can see where effort is still required.
2. As a reviewer, I want unique-answer and respondent-response counts shown
   separately, so that I understand both coding effort and respondent impact.
3. As a reviewer, I want a question-level completion summary, so that I can see
   confirmed groups, groups needing review, Needs attention, and exclusions.
4. As a reviewer, I want Next undecided to move to the next outstanding target,
   so that I do not repeatedly scan the page for unfinished work.
5. As a reviewer, I want Next undecided to respect my question filters, so that
   a filtered set of questions behaves as a deliberate work queue.
6. As a reviewer, I want to filter questions by Not started, In progress, or
   Complete, so that I can focus on the appropriate workflow stage.
7. As a reviewer, I want a Modified filter, so that I can find questions whose
   current state differs from the analyzed starting state.
8. As a reviewer, I want Has exclusions and Provider warning filters, so that I
   can inspect those special conditions directly.
9. As a reviewer, I want answer search within the current question, so that I
   can find canonical answer text across every current location.
10. As a reviewer, I want search results to retain group and section context, so
    that finding an answer does not hide its current coding meaning.
11. As a reviewer, I want to select one or many canonical answers, so that I can
    perform high-volume corrections efficiently.
12. As a reviewer, I want bulk selection to span active groups and Needs
    attention within one question, so that I can consolidate related answers.
13. As a reviewer, I want hidden selected answers disclosed during search, so
    that no bulk operation has invisible impact.
14. As a reviewer, I want all occurrences of a canonical answer edited together,
    so that identical answer text cannot receive inconsistent coding.
15. As a reviewer, I want every action to show selected unique answers and
    affected respondent responses, so that I can judge its impact before acting.
16. As a reviewer, I want to move selected answers into an existing group, so
    that I can correct automatic membership.
17. As a reviewer, I want to move selected answers to Needs attention, so that I
    can defer their destination without losing them.
18. As a reviewer, I want to create a group from selected answers, so that I can
    split or regroup automatic output.
19. As a reviewer, I want reviewer-created groups to allow one canonical answer,
    so that a distinct singleton can receive its own category.
20. As a reviewer, I want to merge one complete group into another, so that I
    can consolidate groups without moving every answer individually.
21. As a keyboard or assistive-technology user, I want explicit selection and
    action controls, so that every edit is accessible without drag-and-drop.
22. As a reviewer, I want to exclude canonical answers without entering a
    reason, so that invalid coding material can be resolved quickly.
23. As a reviewer, I want exclusions to count as completed resolutions, so that
    deliberately excluded answers do not block completion.
24. As a reviewer, I want excluded answers retained in a collapsible section, so
    that exclusions remain visible and auditable.
25. As a reviewer, I want to restore excluded answers to Needs attention, so
    that mistaken exclusions can be reconsidered safely.
26. As a reviewer, I want groups to use only needs-review and confirmed states,
    so that the meaning of current approval is unambiguous.
27. As a reviewer, I want group confirmation to be an explicit action, so that
    editing a decision never silently approves it.
28. As a reviewer, I want membership or applied decision edits to reset affected
    groups to needs review, so that stale approval never survives a change.
29. As a reviewer, I want valid provider proposals to prefill editable decisions,
    so that accepting a good proposal requires only inspection and confirmation.
30. As a reviewer, I want category edits drafted and applied before confirmation,
    so that incomplete typing does not enter history or saved state.
31. As a reviewer, I want empty groups retired automatically, so that the active
    workspace contains no meaningless containers.
32. As a reviewer, I want immediate Undo for the latest structural mutation, so
    that routine edits do not require confirmation dialogs.
33. As a reviewer, I want lightweight question history, so that I can understand
    moves, grouping, exclusions, decision edits, confirmations, and Undo.
34. As a reviewer, I want Review changes available throughout the workflow, so
    that I can inspect net changes and outstanding problems before finishing.
35. As a reviewer, I want completion blocked by unfinished or invalid state, so
    that a locked artifact is internally consistent.
36. As a reviewer, I want similar-label and provider-warning cautions to remain
    non-blocking, so that heuristics do not override my coding judgment.
37. As a reviewer, I want an explicit Complete and lock review action, so that
    confirming the last group does not unexpectedly make the file read-only.
38. As a reviewer, I want the workspace to omit analyst identity, so that review
    does not require names or attribute actions to individuals.
39. As a reviewer, I want stale browser tabs prevented from overwriting newer
    work, so that autosave cannot silently lose edits.
40. As a reviewer, I want schema-version-3 artifacts to remain viewable but
    read-only, so that historical evidence is preserved without migration risk.
41. As a reviewer, I want completed version-4 artifacts to retain original and
    edited evidence, so that the single JSON remains auditable.
42. As a developer, I want ordinary evaluation to report current workspace state,
    so that I can inspect the artifact reviewers actually produced.
43. As a developer, I want ground-truth evaluation to score immutable automatic
    discovery only, so that human corrections never inflate model accuracy.
44. As a reviewer, I want no ground-truth data or metrics in the workspace, so
    that developer benchmark material cannot influence analyst coding.

## Implementation Decisions

### Affected application boundaries

The successor changes the review-document builder, strict review validation,
atomic review persistence, server-owned mutation command processor, local Flask
review boundary, analyst HTML/CSS/JavaScript workspace, ordinary evaluator,
developer-only ground-truth evaluator, and CLI behavior. Automatic workbook
ingestion, answer canonicalization, representation, discovery, and provider
classification remain upstream producers whose evidence is preserved rather
than edited.

### Group review state

An active group has exactly one review state:

- `needs_review`: the group's current membership and coding decision have not
  been explicitly confirmed together by the reviewer.
- `confirmed`: the reviewer explicitly confirmed the group's current membership
  and coding decision together.

Creating a group or changing its membership, coding destination, or bilingual
category labels sets it to `needs_review`. A group becomes `confirmed` only
when the reviewer uses the explicit **Confirm group** action; editing a decision
never confirms it implicitly.

The workspace does not use a separate `needs_reconfirmation` state. Group size
remains visible through counts but creates no filter, quality warning, or
completion effect.

### Confirmable group

An active group can be confirmed only when it contains at least one canonical
answer and has a valid coding destination: either one same-question existing
choice or one valid reviewer-created bilingual category. An active group cannot
be confirmed as unresolved.

Answers that cannot yet be coded belong in **Needs attention**. Answers that
are invalid for coding belong in **Excluded from coding**.

### Canonical answer

A canonical answer is the smallest editable unit. Moving, grouping, excluding,
restoring, or undoing it affects all of its respondent occurrences together;
the workspace does not support occurrence-level exceptions. Before an action,
the interface shows both the selected canonical-answer count and the affected
respondent-response count.

### Answer location

Every canonical answer occupies exactly one current location: one active group,
**Needs attention**, or **Excluded from coding**. A move is one atomic transfer
between locations, never a copy. Historical locations are audit evidence and
do not count as current membership; retired groups contain no current answers.

### Exclusion restoration

The persistent **Restore** action moves an excluded canonical answer to **Needs
attention**. It does not reinstate the answer's former group membership or
coding decision, which may have become stale while the answer was excluded.
Immediate Undo is distinct: when exclusion is the latest mutation, Undo restores
the exact pre-exclusion location and state.

### Exclusion

Excluding a canonical answer requires no reason code, explanation, or note.
The workspace contains no exclusion-reason fields, validation, filters, or
completion checks. Timestamp and respondent impact are recorded by the question
change history.

An excluded canonical answer is a completed resolution. It contributes to
question completion and is skipped by **Next undecided**. Restoring it to
**Needs attention** makes it outstanding again.

### Immediate Undo

The workspace offers one-level Undo for the most recent successful move,
exclusion, restoration, group creation or split, or merge. Undo restores the
exact pre-action memberships, coding decisions, active or retired groups, and
group review states. Navigating between questions preserves the opportunity;
another mutation replaces it, while refresh, browser close, or review
completion clears it. Undo is autosaved and recorded in question history.
History does not support arbitrary older rollback.

### Question change history

Question history records saved actions that change coding meaning: answer
moves; group creation, split, merge, or retirement; exclusion and restoration;
coding-destination or bilingual-label changes; group confirmation; resets from
`confirmed` to `needs_review`; and Undo. Each entry identifies the timestamp,
affected canonical-answer count, affected respondent-response count, and a
concise before-and-after description.

Selection, search, filtering, panel expansion, and navigation are transient UI
activity and are not recorded.

History entries remain compact. They store operation type, revision, timestamp,
affected canonical-answer IDs, source and destination group IDs or locations,
applicable before-and-after decision values, and impact counts. Display resolves
answer text, respondent mappings, and group presentation from authoritative
records. History does not duplicate raw answer text, row mappings, discovery
evidence, or provider payloads. Only the current transient Undo payload retains
the exact inverse state for the latest mutation.

### Review schema and identity

The editable workspace uses review schema version 4. New analyses create
version-4 reviews. Every version-3 review remains readable and read-only,
regardless of whether its stored status is complete or in review. There is no
migration or upgrade path; editable version-4 work starts with a new analysis.

Version 4 contains no analyst identity. The workspace has no analyst-name input,
schema field, validation rule, history attribution, exclusion attribution, or
completion requirement.

Version 4 has a monotonically increasing review revision. Every mutation
includes the revision last loaded by the browser and commits atomically only if
it is still current. Success increments the revision and returns current state.
A stale browser stops editing and offers **Reload latest state**; it never
automatically retries its mutation against changed data. State, history, and
the immediate-Undo record commit in the same atomic save.

The browser submits narrow revisioned commands for answer moves, group
creation and merge, exclusion and restoration, coding-decision edits, group
confirmation, immediate Undo, and review completion. The server validates and
applies each command to the authoritative artifact. The browser never submits
replacement memberships, review states, history, timestamps, or whole edited
review documents.

### Question completion

A question is complete when **Needs attention** is empty and every active group
is `confirmed`. Excluded canonical answers do not block completion, so a
question whose answers are all excluded is complete. Completion is derived
continuously from current locations and group states; there is no separate
question-level completion action.

### Review completion

Confirming the final outstanding group does not complete or lock the review.
When every question is complete, **Finish review** opens the final review
summary. The reviewer must then explicitly choose **Complete and lock review**
to set the artifact to `complete` and make it read-only. Until that action, the
reviewer may return to the workspace or use any still-available immediate Undo.

Before locking, completion is blocked when any canonical answer remains in
**Needs attention**, any active group is `needs_review`, a canonical answer is
missing or currently duplicated, an active group is empty, a reviewer-created
category lacks a valid English or Arabic label, two reviewer-created categories
in one question have the same normalized English or Arabic label, a
reviewer-created category duplicates either normalized label of a same-question
existing choice, or the review otherwise violates the version-4 schema.
Exclusions do not block completion, and multiple groups may intentionally map
to the same existing choice.

The final summary may show two non-blocking cautions: similar but non-identical
reviewer-created category labels compared with both other new categories and
same-question existing choices, and persisted provider warnings as provenance.
Large groups and exclusion volume do not generate cautions. Cautions never
prevent completion.

Similar-label cautions reuse the existing label normalization and compare
English only with English and Arabic only with Arabic using Python's
standard-library sequence similarity. A normalized score of at least `0.85`
in either language produces a caution. Exact matches remain blockers. The
similarity check is deterministic and does not call a model or embedding
provider.

Provider warnings are immutable analysis provenance associated with the
canonical answers from the warned original discovery group. They follow those
answers through moves, splits, merges, exclusions, and restorations. A current
group shows a provider-warning badge when it contains an affected answer; the
question filter matches when any current or excluded answer is affected. The
final summary retains the warning, which never blocks confirmation or
completion.

### Ground-truth boundary

Ground-truth benchmark data is developer/testing input only. The analyst
workspace contains no ground-truth metrics, groups, drawers, filters, labels,
or live evaluation, and review commands do not accept or expose ground truth.
Ground truth remains available only through the separate read-only evaluation
path and is never persisted in the review artifact or supplied to analysis,
workspace state, mutation commands, progress, history, or completion.

When the developer-only evaluator reads a version-4 artifact, it scores the
immutable automatic discovery memberships and ignores reviewer moves,
exclusions, group creation, merges, decisions, and confirmations. Human edits
are never reported as automatic clustering accuracy.

Without ground truth, ordinary version-4 evaluation reports the current
workspace state: active and retired groups, group review states, **Needs
attention**, exclusions, unique-answer and respondent-response counts, current
coding destinations, provider warnings, and net modifications.

### Question workflow status

A question is **Not started** when it has no coding-relevant history entry. It
is **Complete** when it satisfies the derived question-completion rule. It is
**In progress** when coding-relevant history exists but the question is not
complete. Opening, searching, filtering, selecting, or navigating does not
start a question. Undo remains in history, so returning to the initial state
does not return a question to **Not started**.

### Modified question

The **Modified** filter matches a question whose current state diverges from its
analyzed starting state through changed group membership, a reviewer-created or
retired group, an exclusion, a coding destination different from the persisted
provider proposal, or edited reviewer-created bilingual labels. Confirming an
otherwise unchanged proposal does not count. An exact Undo that restores the
starting state removes the question from this filter without erasing history.

There is no **Large groups** filter, threshold, warning, or completion rule.
Current group size remains visible through unique-answer and
respondent-response counts.

### Next undecided

**Next undecided** traverses all incomplete questions when no question filters
are active and only matching incomplete questions when filters are active. If
the filtered view has no undecided target, the workspace says so and offers
**Clear filters**. Current-question answer search does not constrain this
navigation; the workspace clears the search when needed to reveal the target.

Within that queue, **Next undecided** continues after the current position,
visits active `needs_review` groups in visible order, then individual canonical
answers in **Needs attention**, and then later matching questions in workbook
order. It wraps once to earlier unfinished targets before reporting that none
remain. Landing on one answer does not prevent selecting it with others for a
bulk action.

### Question filters

Question filters have one mutually exclusive **Status** selection—All, Not
started, In progress, or Complete—and independent **Modified**, **Has
exclusions**, and **Provider warning** flags. Selected flags combine with the
status and with each other using AND. **Clear filters** restores Status to All
and clears every flag.

### Answer search

Answer search applies only to the current question's canonical-answer text and
uses case-insensitive Unicode substring matching. It searches active groups,
**Needs attention**, and **Excluded from coding**, preserving each match's
current context and expanding collapsed sections that contain matches. The UI
highlights matched text. It does not search respondent identifiers, source-cell
metadata, provider explanations, category labels, or history, and it provides
no fuzzy or semantic matching.

### Answer selection

Selection is limited to the current question. Canonical answers in active
groups and **Needs attention** may be selected together for Move, Create group,
or Exclude. Excluded answers use a separate Restore-only selection mode and
cannot be mixed with active answers. Navigating to another question or
completing an action clears selection. Changing search preserves selection, but
the action bar discloses how many selected answers are hidden by search. Every
bulk action shows both selected canonical answers and affected respondent
responses.

### Move interaction

The workspace provides no drag-and-drop. Accessible selection and explicit
action-bar controls are the complete interaction model for Move, Create group,
Exclude, and Restore operations.

### Group creation

**Create group from selection** atomically moves the selected canonical answers
into a new active `needs_review` group with no coding decision. Every non-empty
source group becomes `needs_review`; an emptied source group is retired. The
new group never inherits a source group's coding decision implicitly.

Initial groups retain analysis order and reviewer-created groups append in
creation order. Moving answers does not reorder groups; merging retires the
source while the destination stays in place; Undo restores a group to its
original identity and position. Answers within groups, **Needs attention**, and
**Excluded from coding** retain original canonical-answer order. Search filters
that order without changing it.

For a new version-4 analysis, every automatically discovered group starts as
`needs_review`. A valid provider proposal for an existing choice or new
category prefills the group's editable coding decision but does not confirm it.
A rejected, invalid, or provider-error proposal leaves the group without a
coding decision. Ungrouped canonical answers start in **Needs attention**. The
original provider proposal remains immutable provenance after later edits.

### Coding-decision editing

Choosing a different existing choice or editing reviewer-created bilingual
labels first changes a browser-local draft. **Apply decision changes** submits
one validated command, returns the group to `needs_review`, and creates one
history entry. Invalid or incomplete bilingual labels cannot be applied.
**Confirm group** is a separate action after the saved decision is visible. An
untouched valid provider-prefilled decision requires only confirmation. Leaving
an unapplied draft presents inline Apply or Discard controls, not a modal.

Only one unapplied decision draft may exist at a time. Confirming or
structurally changing its group is disabled until Apply or Discard. Navigation
may leave the draft in place, with persistent Return, Apply, and Discard
controls. Draft values never affect saved state, history, progress, validation,
or Undo, and review completion is unavailable while a draft exists.

When a membership change leaves an existing group non-empty, the group retains
its current existing-choice assignment or reviewer-created bilingual labels but
returns to `needs_review`. The retained decision does not count as approved for
the changed membership until the reviewer explicitly confirms it again.

### Group merge

**Merge this group into...** moves every canonical answer from one source group
into one destination group in the same question and retires the empty source.
The destination preserves its coding decision and returns to `needs_review`.
The source decision is neither copied nor combined; it remains only in history.
Before applying the merge, the workspace shows affected canonical-answer and
respondent-response counts.

### Singleton group

A reviewer-created group may contain exactly one canonical answer regardless
of whether it represents one or many respondent responses. Human grouping is
not constrained by automatic discovery's minimum distinct-text rule.

### Mutation confirmation

Move, Create group, Exclude, Restore, and Merge apply without confirmation
dialogs after the reviewer chooses the action and any destination. Impact is
visible in the action bar before execution, and immediate Undo is offered after
success. Only **Complete and lock review** uses an irreversible confirmation
step.

### Progress counts

**Resolved items** equals confirmed active groups plus excluded canonical
answers. **Remaining items** equals `needs_review` active groups plus canonical
answers in **Needs attention**. Because those are heterogeneous units, the UI
also shows confirmed groups out of total active groups, needs-review groups,
Needs attention and Excluded unique-answer and respondent-response counts, and
total unique-answer and respondent-response counts. It does not calculate a
percentage from combined item counts. The progress bar uses complete questions
out of total questions.

Each sidebar question entry shows its resolved and remaining item counts plus
total canonical-answer and respondent-response counts. Each question header
shows confirmed groups, `needs_review` groups, **Needs attention** counts, and
Excluded counts; answer-based sections show both canonical-answer and
respondent-response totals.

### Final review summary

**Review changes** opens the current summary at any time without changing state
or creating history. While work remains, it shows outstanding groups, **Needs
attention** answers, net changes, and validation failures without offering a
lock action. Once every question is complete, **Finish review** opens the same
summary with **Complete and lock review** enabled.

The final summary reports net current divergence from the analyzed starting
state: canonical answers currently moved and their respondent impact, current
reviewer-created groups, original groups currently retired through splits or
merges, currently excluded answers, and groups whose confirmation was
invalidated at least once by a later edit. An action reversed by Undo does not
inflate these net totals, although both events remain in question history. The
summary also shows blocking validation results and the agreed non-blocking
cautions.

### Category value allocation

Existing-choice assignments retain their existing values. During **Complete
and lock review**, each confirmed active group with a reviewer-created category
receives the smallest unused integer greater than `100`, after reserving
same-question existing integer values greater than `100`. Eligible groups are
processed in stable creation order. Retired groups receive no value, and values
may repeat between questions. No value is allocated or renumbered while the
review remains editable.

### Completed artifact evidence

The completed version-4 artifact retains original analysis and provider
provenance, canonical answers and respondent mappings, current active groups
and final coding decisions, excluded answers, retired groups and their last
saved decisions, full compact question histories including Undo events, final
completion-summary data, the completion timestamp, and the final revision.
Locking removes only the transient immediate-Undo payload.

## Testing Decisions

Tests assert external behavior and persisted contracts rather than private
helper structure. State-transition coverage belongs at the highest server
boundary that accepts the same commands as the browser; browser-only interaction
behavior belongs in a small set of real end-to-end journeys.

### Primary Flask command seam

Use the existing local Flask application's test client with a temporary review
artifact. Issue revisioned mutation commands, reload the persisted artifact, and
assert returned state plus durable JSON. This seam covers answer-location
invariants, canonical-answer atomicity, group creation and retirement, move and
merge semantics, exclusions and restoration, decision application,
confirmation resets, history, one-level Undo, progress, completion, locking,
revision conflicts, malformed commands, and read-only artifacts.

Existing Flask test-client coverage of review updates, completion, read-only
files, state loading, and optional review presentation is the prior art. Replace
whole-document update expectations with server-owned command behavior rather
than keeping both mutation models.

### Browser journey seam

Add Playwright as a development-only dependency through `uv` and run a small
number of end-to-end journeys against the real local Flask application. Cover
keyboard-accessible selection and action controls, question filters, answer
search, Next undecided, search-hidden selections, unique and respondent impact
counts, draft Apply/Discard controls, immediate Undo presentation, collapsible
Excluded and history sections, Review changes, final locking, responsive focus
management, and the absence of analyst-identity and ground-truth UI.

Browser tests should exercise complete representative journeys rather than one
test per DOM element. They must use accessible roles and visible labels instead
of CSS implementation selectors wherever practical.

### CLI and evaluation seam

Extend existing CLI-level tests to prove that new analysis writes version 4,
review treats every version-3 artifact as read-only, review no longer accepts
ground truth, ordinary evaluation reports current version-4 workspace state,
and developer-only ground-truth evaluation reconstructs immutable automatic
membership while ignoring reviewer edits.

### Direct boundary tests

Keep focused direct tests for strict version-4 schema validation, command schema
validation, deterministic category-label normalization and exact-duplicate
rules, and the same-language `0.85` similarity caution. These tests cover input
partitions that would be unnecessarily verbose through a browser while still
asserting public validation behavior.

All tests run through `uv`. Provider calls are replaced with deterministic test
fixtures or fakes; this feature's test suite must not spend provider credits or
require live API credentials.

## Explicitly out of scope

- Analyst identity or attribution.
- Exclusion reasons, notes, or reason-based validation.
- Occurrence-level editing of a canonical answer.
- Drag-and-drop.
- A Large groups filter or size-based warning.
- Migration or upgrade of schema-version-3 artifacts.
- Arbitrary rollback from question history.
- Ground-truth data or metrics in the analyst workspace.

## Further Notes

- The existing schema-version-3 contract remains the shipped behavior until
  implementation of this specification is complete.
- Version 4 starts only from a new analysis; preserving version-3 editability is
  intentionally not a compatibility requirement.
- The completed review JSON remains the sole output and source of truth. This
  specification does not add workbook mutation, respondent export, CSV output,
  or a second finalization artifact.
- The accepted behavior contract and durable successor decisions are recorded
  in the repository context documents. Ticket creation should preserve the
  blocking order between schema/command foundations, browser workflow, and
  completion/evaluation integration.
