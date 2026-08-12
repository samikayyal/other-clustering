# Other-cluster V4 core review workflow

Date: 2026-08-12

## Test environment

- Browser: Google Chrome controlled through the Chrome browser-control extension.
- URL: `http://127.0.0.1:54931/`.
- The requested `[APP_URL]` value was not supplied. The repository exposes a local-only Flask review app, so the latest real review artifact was served on an isolated loopback port.
- Viewport: 1745 × 907 CSS pixels; device pixel ratio 1.1.
- Application title: `Review survey answers · NOT CODED WFP - FSOM Q2 2026 - Coding Sheet.xlsx`.
- Initial review state: schema version 4, `status: in_review`, revision 4, 23 questions, 6/23 questions complete.
- No application source files or shared production data were edited.

## Fixture and setup

The newest JSON file by modification time was copied before testing:

- Original: `D:\Personals\Mindset\AI Coding\reviews\not_coded_wfp_-_fsom_q2_2026_-_coding_sheet_a7ace7d1-333f-4d59-8979-f45ca881aac1.json`
- Disposable copy used by the browser: `D:\Personals\Mindset\AI Coding\.temp\ui_testing_latest_review_copy.json`
- Original SHA-256 at verification: `A992B140A7D689B05B5DA737E65AA8B4E1C32E0508077140FC241FD479D2B881`.
- The copy was the only review file served and was mutated by the test commands. Its final state was revision 11 and remained `in_review`.

The main workflow question was `in_src_1st_other` (question 9). At the start of the browser run it contained 48 canonical answers, 49 respondent responses, eight active groups, and nine answers in Needs attention. All eight active groups needed review. Representative cards included 2 unique/2 responses, 10 unique/10 responses, and 11 unique/11 responses, providing enough data for selection, movement, creation, and merge operations. The source artifact already contained earlier review history and net changes; those are distinguished below from actions performed in this run.

## Test cases

### 1. Initial review workspace — PASS

Expected: The workspace loads with the sidebar, progress banner, group cards, answer counts, respondent-response counts, and an initial in-review status.

Observed:

- Header showed `All changes saved` and `In review`.
- Sidebar showed `6/23 questions complete`.
- Question 9 sidebar entry showed `Resolved 0 · Remaining 17` and `48 unique · 49 responses`.
- The question banner showed `0/8 confirmed groups`, `8 needs-review groups`, `Needs attention: 9 unique · 9 responses`, and `Excluded: 0 unique · 0 responses`.
- Active group cards exposed canonical-answer checkboxes, saved/provider decisions, confirmation controls, and merge controls. Counts were shown in both unique answers and respondent responses.

### 2. Local decision draft before Apply — PASS

Expected: Changing Edit coding decision creates only a browser-local draft. Durable state, history, status, and completion progress remain unchanged until Apply decision changes.

Steps and observations:

1. On question 9, selected `10 · Education` in `Review group 1`.
2. The `Unsaved decision draft` region appeared with Apply and Discard controls; Confirm group and merge controls for that group were disabled.
3. The copy remained at revision 4 with `status: in_review`; its saved decision remained `Existing choice 9`, history remained empty, and the sidebar remained `6/23`.

### 3. Apply decision and reload persistence — FAIL (durable state passed; selector rehydration failed)

Expected: Applying shows success, updates saved state, and reload displays the persisted decision.

Observed:

- `Decision changes applied.` appeared.
- The saved decision changed to `Existing choice 10`; the group remained `Needs review`; history gained `apply_decision`; and the revision advanced to 5.
- After reload, the saved-decision text still displayed `Existing choice 10`, and history remained present, proving durable persistence.
- Failure: the `Edit coding decision` control reset to `Choose a decision…` instead of selecting the saved `10 · Education` option. The durable value and the visible saved-decision text disagree with the editable control.
- Screenshot: [decision selector after reload](<D:/Personals/Mindset/AI Coding/.temp/ui_testing_decision_selector_reload.png>).

Exact reproduction:

1. Open the disposable copy and navigate to question 9, `in_src_1st_other`.
2. In `Review group 1`, set `Edit coding decision` to `10 · Education`.
3. Click `Apply decision changes` and wait for `Decision changes applied.`.
4. Reload the page and return to question 9.
5. Observe `Saved decision: Existing choice 10` while the edit selector shows `Choose a decision…` with no selected decision.

### 4. Separate group confirmation — PASS

Expected: Confirmation is distinct from applying a decision, changes the group to confirmed, and updates progress.

Observed:

- Clicking `Confirm group` after Apply produced `Group confirmed.` as a separate action.
- The group became `Confirmed`; history contained `apply_decision, confirm_group`; and the revision advanced to 6.
- The banner changed to `1/8 confirmed groups · 7 needs-review groups`.
- The sidebar changed to `Resolved 1 · Remaining 16`.

### 5. Selection impact totals — PASS

Expected: Selecting canonical answers reports both unique-answer and respondent-response totals.

Observed: Selecting `سائق` (1 response) and `خياط` (2 responses) displayed `2 unique answers · 3 respondent responses` in the selection action bar. The bar also exposed Move, Create group, Exclude, and Clear selection controls.

### 6. Move selected answers to another active group — PASS

Expected: Move transfers membership atomically, resets affected review states, clears selection, reports success, and persists after reload.

Observed:

- Moved `سائق` from Review group 1 and `خياط` from Review group 4 into Review group 8.
- `Selected answers moved.` appeared and the selection action bar disappeared.
- The source groups no longer contained the selected answers; Review group 8 contained both and showed `4 unique answers · 5 respondent responses`.
- Affected groups were `Needs review`; the move history entry reported 2 unique answers and 3 responses; revision advanced to 7.
- Reload confirmed the source/destination membership and the history remained persisted.

### 7. Create and merge a reviewer group — PASS

Expected: Selected answers can form a new reviewer group with no inherited decision; if supported, merging it into an active group retires the source and resets the destination state.

Observed:

- Selected `تستلم بصمه عين` and `غسيل سيارات` and clicked `Create group from selection`.
- `Group created from selected answers.` appeared; Review group 9 was created with 2 unique answers, 2 responses, `Needs review`, and `No saved decision`.
- The source/Needs-attention memberships were removed and selection was cleared.
- Selected Review group 9’s merge destination as Review group 7. `Groups merged.` appeared; Review group 9 disappeared into retired history, and Review group 7 contained the two answers with 13 unique answers/13 responses and `Needs review`.

### 8. Undo exact restoration and replacement — PASS

Expected: Undo restores the exact previous membership and decision state; a later structural mutation replaces the older Undo opportunity.

Observed:

- After merge, `Undo merge` restored Review group 9 with exactly `تستلم بصمه عين` and `غسيل سيارات`, no saved decision, and `Needs review`.
- Review group 7 no longer contained either answer and remained `Needs review`. The merge Undo opportunity was cleared.
- A second structural move transferred `غسيل سيارات` from the restored reviewer group to Needs attention. The action bar showed `1 unique answer · 1 respondent response`; the source retained `تستلم بصمه عين`; and the successful mutation exposed `Undo move`.
- `Undo merge` was no longer available, demonstrating replacement of the older Undo payload.

### 9. Review changes projection — PASS

Expected: Review changes reflects outstanding work, net moves, created/retired groups, and respondent impact, without counting undone structure as current net change.

Observed:

- The dialog showed `75 groups need review · 34 answers need attention` across the real artifact.
- Net current changes showed `5 moved canonical answers · 6 respondent responses`.
- The total includes two pre-existing `enm_commnets` moves from the source artifact plus this run’s net moves: `تستلم بصمه عين` (1), `خياط` (2), and `سائق` (1), for 5 answers and 6 responses overall.
- It showed one current reviewer-created group (`in_src_1st_other:reviewer:8`) with one answer/one response after the later move, zero retired original groups, zero exclusions, and one group whose confirmation had been invalidated by a later membership change.
- The undone merge did not appear as a current retired-group/net-change result. No Complete and lock review button was offered because blocking work remained.

### 10. Complete and lock / read-only reload — BLOCKED

Expected, if the fixture can be completed: a local draft blocks completion; after applying or discarding it, Finish review permits the permanent-lock confirmation and the completed artifact is read-only after reload.

Observed limitation: This real review copy was not completion-ready. It contained 75 groups needing review and 34 Needs-attention answers across 23 questions; the Review changes dialog correctly had no Complete and lock review control. The permanent lock and completed read-only reload could not be exercised without performing a large unrelated review of the real artifact. Draft behavior was tested in case 2, but the completion-specific draft gate was not independently testable on this incomplete real fixture.

## Console and network diagnostics

- Chrome console logs: no error, warning, info, or log entries were captured for the tested page.
- Local server command requests: all observed `POST /api/commands` requests returned HTTP 200.
- Initial page/static requests returned HTTP 200; cached reloads returned HTTP 304 for the static CSS/JavaScript.
- One non-functional request returned HTTP 404: `/favicon.ico`.
- One browser automation wait timed out during the Needs-attention move while a DOM rerender detached the previous locator. A fresh locator and retry succeeded with HTTP 200; this was an automation synchronization issue, not an application/network failure.

## Limitations

- No public `[APP_URL]` was provided, so testing used the repository’s local Flask server and an isolated copy of the latest real review JSON.
- The source artifact already contained revision/history/net changes. Review changes therefore includes those pre-existing changes; the report separates them from this run’s actions.
- Completion/locking was not tested because the real copy was materially incomplete.
- No visual-only failures were found beyond the selector-state mismatch documented in case 3; the screenshot linked there is the only screenshot captured.
