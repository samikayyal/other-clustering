# Progress queue, filters, and navigation browser test report

## Outcome

Overall result: **PASS** for the requested progress-queue, question-filter, answer-search, selection, and Next-undecided journeys. No confirmed product failure was reproduced.

One attached-server launch attempt failed because the PowerShell argument path was split at the workspace space; the application itself was then started successfully with `uv run other-cluster review`. One synthetic rapid-click trace briefly sampled `BODY` focus at a cross-question boundary; the same transition passed with a 700 ms settle and is recorded as a timing observation, not a product failure.

## Test environment

- Test date: 2026-08-12, Asia/Amman.
- Application URL: `http://127.0.0.1:5000/`.
- Application command: `uv run other-cluster review --review-file .temp\\ui_testing_progress_latest_copy.json`.
- Source checkout: `main`, commit `817d96f` (`origin/main` at test time).
- Primary browser: Chrome through the Chrome extension control surface.
- Secondary smoke browser: Codex in-app Browser control surface.
- Chrome viewport: `1745 x 856` CSS pixels, device pixel ratio `1.1000000238`.
- In-app Browser viewport: `1280 x 720` CSS pixels, device pixel ratio `1`.
- Page title: `Review survey answers · NOT CODED WFP - FSOM Q2 2026 - Coding Sheet.xlsx`.
- The final Chrome viewport was visually inspected. No clipping, overlap, unreadable Unicode, or broken control layout was observed. No visual-failure screenshot was saved because no visual failure occurred.

## Fixture and setup

The latest real V4 review file was selected by filesystem timestamp:

`reviews/not_coded_wfp_-_fsom_q2_2026_-_coding_sheet_a7ace7d1-333f-4d59-8979-f45ca881aac1.json` (PowerShell timestamp: 2026-08-10 14:15:11 local).

It was copied to the disposable fixture:

`.temp/ui_testing_progress_latest_copy.json`

The original review file was not opened for mutation and was not changed. No application source file or shared data file was changed. The `ui_testing` directory already existed; this report is the only new Markdown report created for this task.

The copied artifact was schema version 4, `status: in_review`, with 23 questions. Before UI setup, its real-data projection contained 16 Not started questions, 1 In progress question (`enm_commnets`), and 6 Complete questions. The latest real file already supplied Arabic/Unicode answer text, real review history, active groups, and complete/empty questions, but did not contain an exclusion, a provider-error proposal, or a mixed-case Latin answer suitable for every requested search partition. Only the disposable copy was instrumented as follows:

- In `other_support_text`, one real canonical answer was given the test text `MixedCase Café ملاحظات`.
- In the same question, automatic group `other_support_text:cluster:0` was marked with the valid provider proposal `decision: provider_error` and `provider_error: fixture provider timeout warning`.
- Through the UI, the answer `نفقة` was selected and **Exclude selected answers** was activated. This produced the real persisted exclusion workflow, an Excluded section, and an Undo exclusion control in the disposable copy.

After the UI exclusion, the projected status counts were 15 Not started, 2 In progress (`enm_commnets` and `other_support_text`), and 6 Complete. The overall completion projection remained `6/23`.

## Test cases

### T01 — Sidebar metrics and overall progress — PASS

Expected: every question link shows resolved and remaining item counts plus unique-answer and respondent-response totals; the progress card shows complete questions out of total questions.

Observed:

- The initial All queue rendered 23 question links with the expected metric pattern, including `HHAsstAccessWhat_other: Resolved 0 · Remaining 1; 1 unique · 1 responses` and `enm_commnets: Resolved 0 · Remaining 20; 194 unique · 196 responses`.
- After excluding `نفقة`, `other_support_text` rendered `Resolved 1 · Remaining 3; 13 unique · 13 responses` in the sidebar.
- The sidebar progress card rendered `6/23 questions complete` before and after the exclusion.
- The current-question summary for `other_support_text` rendered `0/3 confirmed groups · 3 needs-review groups · Needs attention: 0 unique · 0 responses · Excluded: 1 unique · 1 responses`.

### T02 — Status filter values — PASS

Exact control values used: `all`, `not_started`, `in_progress`, and `complete` in the `Status` combobox.

| Status value | Expected matching questions | Observed visible queue |
| --- | --- | --- |
| `all` | All workbook questions | 23 questions |
| `not_started` | Questions with no coding-relevant review progress | 15 questions |
| `in_progress` | `enm_commnets`, `other_support_text` | Exactly those 2 questions |
| `complete` | The six empty/complete questions | `lv_coping_early_marriage_conf`, `lv_coping_wdr_children_conf`, `lv_coping_wrk_children_conf`, `other_support_1_explain`, `staff_respect_where_other`, `unhcr_id_manual_why_other` |

Only matching question links remained visible for each status. The current main question changed to an appropriate matching question when the prior current question was filtered out.

### T03 — Independent Modified, Has exclusions, and Provider warning filters — PASS

Status was reset to `All` for these checks.

| Filter state | Exact controls | Observed queue |
| --- | --- | --- |
| Modified only | `Modified=true`, other flags false | `enm_commnets`, `other_support_text` |
| Has exclusions only | `Has exclusions=true`, other flags false | `other_support_text` |
| Provider warning only | `Provider warning=true`, other flags false | `other_support_text` |

The Modified result included the existing real-history question and the instrumented/excluded disposable-copy question. Provider-warning provenance was visible on the affected active group.

### T04 — AND combinations — PASS

Exact combinations used:

- `Modified=true`, `Has exclusions=true`, `Provider warning=false` → only `other_support_text`.
- `Modified=false`, `Has exclusions=true`, `Provider warning=true` → only `other_support_text`.
- All three flags true → only `other_support_text`.
- `Status=in_progress` plus all three flags → only `other_support_text`.
- `Status=complete` plus all three flags → no question links.

The observed results were logical AND intersections; unrelated questions did not remain visible.

### T05 — Clear filters — PASS

After using **Clear filters**, the observed state was:

- `Status=all`.
- `Modified=false`.
- `Has exclusions=false`.
- `Provider warning=false`.
- All 23 question links visible.
- Status message: `Question filters cleared.`

### T06 — Answer search matching partitions — PASS

Search was performed in `other_support_text` using the exact values below. Matching was observed on canonical answer text only.

| Search value | Expected | Observed |
| --- | --- | --- |
| `MIXEDCASE` | Case-insensitive match | `MixedCase Café ملاحظات (1)` remained visible; `<mark>` text was `MixedCase`. |
| `mixedcase` | Same result as uppercase variant | Same one answer and same highlighted canonical substring. |
| `ملاحظات` | Unicode/Arabic substring match | Same answer remained visible; `<mark>` text was `ملاحظات`. |
| `Case Caf` | Partial substring match spanning the mixed-case answer | Same answer remained visible; `<mark>` text was `Case Caf`. |
| `please` | No canonical answer match even though the question title contains “please” | No canonical answer label or mark. |
| `zzzz-no-match` | No answer match | No canonical answer labels or marks in the active/Needs attention result lists. |

The generic `No matching answers` fallback is rendered inside the empty Needs attention section even when another section has a match; answer-label and mark presence were used to distinguish section-local emptiness from a whole-question search result.

### T07 — Search highlighting, context, and collapsed-section expansion — PASS

For `MIXEDCASE`, the answer stayed inside active group `other_support_text:cluster:0`; the group header, group state, provider-warning badge, group totals, and provider-proposal context remained visible. The matching text was highlighted without replacing the original mixed-case/Unicode text.

The Excluded section was initially collapsed (`open` absent). Searching for `نفقة` produced:

- Search value `نفقة`.
- Highlighted mark `نفقة`.
- Excluded section `open=true`.
- Restore-only checkbox with accessible name `Restore answer نفقة`.
- No active-group match for the excluded answer.

### T08 — Selection retained while a different answer is searched — PASS

Exact sequence:

1. Search `MIXEDCASE`.
2. Check `Select answer MixedCase Café ملاحظات`.
3. Search `طرد`.

Observed while `طرد` was active:

- The visible matching answer was `طرد غذائي (1)`.
- The original selected answer remained selected in browser state.
- The selection action region rendered `1 unique answers · 1 respondent responses` and `1 selected answer hidden by search`.

Changing the query back to `MIXEDCASE` showed the original checkbox still checked.

### T09 — Next undecided ordering, search clearing, focus, keyboard activation, and wrap — PASS

Exact filter state: `Status=all`, `Modified=true`, `Has exclusions=false`, `Provider warning=false`. The filtered queue was `enm_commnets` followed by `other_support_text`, matching workbook order.

In `enm_commnets`, the observed Next-undecided target sequence visited all 17 active `needs_review` groups before the three individual Needs attention answer targets. The group target IDs were observed in the page’s active-group order, including `group:enm_commnets:cluster:0`, `:1`, `:11`, `:13`, `:14`, `:15`, `:16`, `:17`, `:18`, `:2`, `:3`, `:4`, `:5`, `:6`, `:7`, `:8`, and `:9`; answer targets followed only after those groups.

Before navigation, the current answer search was `zzzz-no-match`. The first Next action cleared it to an empty value. A settled replay with 700 ms between actions showed:

- Group targets focused an `ARTICLE` with the corresponding `data-undecided-target`.
- Individual Needs attention targets focused their `INPUT` checkbox.
- The settled q3-to-q17 transition focused `group:other_support_text:cluster:0`, not the question body.
- After traversing the filtered outstanding targets, navigation wrapped to `group:enm_commnets:cluster:0`.

Keyboard observation: focusing the **Next undecided** button and pressing `Enter` produced the same first group target, cleared `zzzz-no-match`, and placed focus on the target article.

### T10 — No undecided target in filtered view — PASS

Exact filter state: `Status=complete`, all three independent flags false. The queue contained the six Complete questions but no outstanding target. Activating **Next undecided** left the filtered queue unchanged and rendered the status message `No undecided items in this view.`

### T11 — Selection isolation between questions — PASS

Exact sequence:

1. In `other_support_text`, leave search empty and select `MixedCase Café ملاحظات`.
2. Navigate to `food_items_explain` through the sidebar.
3. Navigate back to `other_support_text`.

Observed:

- The selection action region existed before navigation.
- `food_items_explain` had zero selection action regions and zero checked answer-selection inputs.
- On returning to `other_support_text`, zero answer-selection inputs were checked, zero selection action regions remained, and the answer search was empty.

### T12 — No stale counts, answer results, or highlights after filter/question changes — PASS

Exact sequence:

1. In `other_support_text`, search `MIXEDCASE` and confirm the answer label and `<mark>`.
2. Enable `Provider warning`; the same q17 answer label and mark remained visible.
3. Disable `Provider warning` and select `Status=complete`, removing q17 from the filtered queue.

Observed after q17 was removed:

- The main view switched to Complete question 12.
- The new question’s search value was empty.
- `main mark` count was zero.
- The visible queue contained exactly the six Complete question IDs.
- The sidebar q17 metrics remained `Resolved 1 · Remaining 3; 13 unique · 13 responses` when All filters were restored; no stale pre-exclusion `Resolved 0` value remained in the active Chrome page.

### T13 — In-app Browser smoke comparison — PASS

The same URL loaded in the Codex in-app Browser. It rendered `6/23 questions complete`, default filters `Status=all` with all flags false, 23 question links, and the instrumented q17 sidebar metric after reload: `Resolved 1 · Remaining 3; 13 unique · 13 responses`.

The in-app tab was initially loaded before Chrome performed the exclusion and therefore showed its pre-mutation q17 count until reloaded. After an explicit reload, it matched the persisted disposable-copy state. Cross-tab live synchronization was not part of the requested single-tab workflow and was not treated as a product failure.

## Focus and keyboard-navigation observations

- The filter controls were exposed as an accessible `Status` combobox and named checkboxes.
- The Next button was activated both by click and by pressing `Enter` while it was focused.
- Group targets received focus on their focusable `ARTICLE`; individual answer targets received focus on their checkbox `INPUT`.
- Answer search was cleared before the Next target received focus.
- Navigating by sidebar link cleared the current question’s selection and answer search.
- A 120 ms synthetic click loop produced one intermediate `BODY` focus sample at the q3-to-q17 boundary. Repeating the same boundary with 700 ms settling focused q17 group 0 correctly; no confirmed focus failure remained.
- A complete tab-order/screen-reader audit was not performed.

## Console, network, and server evidence

- Chrome browser console logs: no `error` or `warn` entries; no captured all-level console entries.
- In-app Browser console logs: no `error` or `warn` entries.
- No visible browser network failure occurred; page navigation, static asset loading, UI commands, and state refreshes completed.
- Network response-status events were not exposed by the browser-control API used here, so individual HTTP status codes were not independently recorded.
- A failed preliminary background launch wrote this harness stderr, not an application error: `other-cluster: error: unrecognized arguments: Coding\\.temp\\ui_testing_progress_latest_copy.json`. The attached foreground command using the exact quoted review-file path started the intended Flask server on `127.0.0.1:5000`, and the browser tests then completed.

## Visual evidence

No visual failure was observed, so there is no screenshot path to report. The final Chrome viewport was inspected at `1745 x 856`; the progress card, filter controls, q17 metrics, mixed-case/Arabic text, provider-warning badge, active groups, and exclusion controls were legible and visually contained.

## Limitations and untested cases

- The real latest review file did not itself contain all requested special conditions, so provider-warning and mixed-case search coverage required instrumentation in the disposable copy. The exclusion was created through the actual UI command path.
- No mutation was made to the original review file, shared source data, or application source.
- Cross-tab live synchronization was not tested beyond observing that a pre-mutation tab required reload to see the persisted exclusion.
- No mobile/responsive breakpoint run, full keyboard tab-order audit, assistive-technology/screen-reader run, or automated network-status capture was performed.
- No application source fixes were made for any observation.
