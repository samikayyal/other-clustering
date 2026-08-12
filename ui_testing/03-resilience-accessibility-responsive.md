# V4 analyst review workspace: resilience, accessibility, responsive, and read-only-state browser test

Date: 2026-08-12 (Asia/Amman, UTC+03:00)

Overall result: partial pass. The core exclusion, restore, structural mutation, persistence, and stale-revision protections behaved correctly on a copied V4 review. The changes dialog has a focus-management defect and a mobile-width horizontal-clipping defect. Completion/locking was not available in the served fixture and is therefore blocked.

## Test environment

- Application URL: `http://127.0.0.1:5000/#question-food_items_explain`
- Browser: Google Chrome controlled through the connected Chrome browser-control extension; a second in-app browser connection was used only to check the same local endpoint after Chrome setup.
- Host: Windows/PowerShell workspace at `D:\Personals\Mindset\AI Coding`.
- Browser zoom: default session; `Ctrl+0` was sent before the desktop responsive check. The browser-control surface did not expose the Chrome UI zoom percentage. Reported device-pixel ratio was approximately `1.10`.
- Default/desktop observed CSS viewport: approximately `1309 × 818` after requesting a `1440 × 900` override.
- Tablet requested viewport: `768 × 900`; observed CSS viewport approximately `698 × 818`.
- Mobile requested viewport: `320 × 800`; observed CSS viewport approximately `291 × 727` after the browser-control scale was applied.
- Browser tabs: tab A and tab B were Chrome tabs connected to the same review fixture for the stale-revision check. A separate Chrome tab was used for responsive overrides.
- The browser page was inspected through DOM snapshots, semantic locators, read-only DOM evaluation, keyboard interaction, screenshots, and captured console logs. No application source file was edited.

## Fixture and setup

The latest existing V4 review file at setup time was copied before the server was started:

- Original, left untouched: `D:\Personals\Mindset\AI Coding\reviews\not_coded_wfp_-_fsom_q2_2026_-_coding_sheet_a7ace7d1-333f-4d59-8979-f45ca881aac1.json`
- Disposable copy used by the server: `C:\Users\kayya\AppData\Local\Temp\other-clustering-v4-ui-71e52931-31ab-408b-b911-e4e53abc0d5f.json`
- Original size observed before testing: `2,256,142` bytes.
- The disposable copy was the only review file mutated by browser actions. Its final observed size was `2,272,467` bytes.
- Server command: `uv run other-cluster review --review-file C:\Users\kayya\AppData\Local\Temp\other-clustering-v4-ui-71e52931-31ab-408b-b911-e4e53abc0d5f.json`
- Server endpoint: `http://127.0.0.1:5000`.
- Starting Q5 (`food_items_explain`) state: 58 unique answers / 58 responses, 5 active needs-review groups, 0 needs-attention answers, and 0 excluded answers.

The fixture was deliberately changed during testing. Those changes are confined to the temporary copy and are not production-data or original-file results.

## Test-case summary

| Case | Status | Result |
|---|---|---|
| 1. Exclude selected answers | PASS | Excluded totals and answer placement updated correctly; excluded answers left their prior groups and no longer appeared in Needs attention. |
| 2. Restore excluded answers | PASS | Restored answers appeared in Needs attention, not in their former groups or saved decisions. |
| 3. Structural mutation, reload, undo state | PASS, with coverage note | A single new group persisted across reload and no Undo affordance was present after reload. The create-group mutation did not expose an Undo affordance even before reload. |
| 4. Review changes dialog | FAIL | Name, close control, initial focus, Escape, Enter, and focus return worked; Tab from Close moved focus to `body`, causing focus loss. |
| 5. Keyboard-only workflow and names | PASS, with caveat | Tab, Shift+Tab, Enter, and Space reached and operated the main controls. See the duplicate-name finding in case 6. |
| 6. Accessibility tree/DOM semantics | FAIL | No empty buttons or missing labels were found, but repeated group controls expose duplicate standalone accessible names. |
| 7. Responsive layout | FAIL | Page layout fit at mobile, tablet, and desktop widths without page-level horizontal overflow; the mobile Review changes dialog itself had horizontal overflow and visibly clipped long identifiers. |
| 8. Two-tab stale revision | PASS | Tab B received a clear stale-revision message and did not overwrite tab A's newer exclusion. |
| 9. Complete and lock | BLOCKED | No completion or lock control, Completed status transition, or read-only guidance was exposed by this fixture. |
| 10. Harmless repeated mutation/completion clicks | PASS for mutation; BLOCKED for completion | Repeated Create group activation created one group and one history event only. Completion controls were unavailable to exercise. |
| 11. Console, network, images, truncation, and error exposure | FAIL | Console errors/warnings were empty and there were no images, but the mobile dialog visibly truncated content; network request enumeration was not available through the selected browser surface. |

## Detailed results

### 1. Select and exclude answers — PASS

Expected behavior:

- Selecting answers should expose the selection action bar.
- Excluding selected answers should update excluded unique/response totals.
- Excluded answers should leave their previous location and should not remain outstanding in Needs attention.

Steps and observed result:

1. Open Q5, `food_items_explain`.
2. Select the first answer checkbox in Review group 1 and the first answer checkbox in Review group 2.
3. Confirm the action bar exposed `Move selected answers`, `Create group from selection`, `Exclude selected answers`, and `Clear selection`.
4. Click `Exclude selected answers` once.
5. The selection cleared automatically.
6. The page reported `Excluded: 2 unique · 2 responses` and `Needs attention: 0 unique · 0 responses`.
7. The source groups changed from 15 to 14 unique answers and from 4 to 3 unique answers, respectively; the two selected answers were absent from those groups.
8. The `Excluded from coding` disclosure reported `2 unique answers · 2 respondent responses` and exposed two `Restore answer ...` checkboxes.

The group-level “Outstanding” line continued to describe the five needs-review groups; the answer-level needs-attention total correctly dropped to zero. This is consistent with excluded answers no longer contributing answer-level outstanding work while their source groups remain reviewable.

### 2. Restore excluded answers — PASS

Expected behavior: restoring excluded answers should put them into Needs attention rather than returning them to their former group or saved decision.

Steps and observed result:

1. Expand `Excluded from coding`.
2. Select both `Restore answer ...` controls. One control was initially below the viewport; scrolling the page brought it into view. The controls remained keyboard/DOM reachable.
3. Click `Restore selected answers`.
4. The page reported `Needs attention: 2 unique · 2 responses` and `Excluded: 0 unique · 0 responses`.
5. Both restored answers appeared in the Needs attention list.
6. The former source groups remained at their post-exclusion counts; the answers did not return to those groups or their previous decisions.
7. History recorded: `Restored 2 answers to Needs attention · revision 6 · 2 unique / 2 responses`.

### 3. Structural mutation, reload, and browser-only Undo — PASS, with coverage note

Expected behavior: a structural mutation should persist after reload, while a browser-only Undo affordance should not survive reload.

Steps and observed result:

1. Select the two restored answers from Needs attention.
2. Activate `Create group from selection` with a repeated/double activation to exercise duplicate submission behavior.
3. Exactly one new `Review group 6` appeared, containing two unique answers. No second group was created.
4. The mutation history showed one event: `Created Review group 6 · revision 7 · 2 unique / 2 responses`.
5. The page surfaced a stale-state banner after the second request: `stale review revision 6; current revision is 7. Reload latest state to continue. Reload latest state`.
6. Reload the page. It opened at the default question, so navigate back to Q5.
7. `Review group 6` and its two answers were still present; the Q5 header reported six needs-review groups. The history still contained the create-group event.
8. No button whose text began with `Undo` was present after the reload.

Coverage note: creating a group did not expose a browser-only Undo button before reload either. The later exclusion operation did expose `Undo exclusion`, but that was a separate mutation and was not used as evidence that create-group Undo had disappeared.

### 4. Review changes dialog — FAIL

Expected behavior: the dialog should have an accessible name, a usable Close control, sensible initial focus, predictable keyboard close behavior, and no focus loss.

Steps and observed result:

1. Click `Review changes`.
2. The DOM snapshot exposed one native dialog with the accessible name `Review changes`, derived from `aria-labelledby="review-changes-title"`.
3. The dialog contained a visible `Close` button. On opening, focus was placed on `Close`.
4. Press `Escape`: the dialog closed and focus returned to the invoking `Review changes` button.
5. Reopen with `Enter`: the dialog opened and focus again landed on `Close`.
6. Press `Enter` on `Close`: the dialog closed and focus returned to `Review changes`.
7. Failure: from the focused `Close` button, press `Tab`. `document.activeElement` became `BODY`, outside the dialog. Pressing `Shift+Tab` then focused the dialog container rather than a usable dialog control.

Exact reproduction:

1. Open `http://127.0.0.1:5000/#question-food_items_explain`.
2. Click `Review changes`.
3. Press `Tab` while `Close` is focused.
4. Inspect focus with a screen reader or browser accessibility tooling; focus is on the page body, not a usable control in the dialog.

Expected: focus should remain managed within the modal until it closes, or the next/previous focus transition should be a documented, usable dialog control. Observed: focus loss to `body`.

### 5. Keyboard-only main workflow — PASS, with caveat

Keyboard sequences used:

- `Tab` from the Survey review home link traversed Status, Modified, Has exclusions, Provider warning, Clear filters, and the question links.
- `Tab` from `Next undecided` reached `Review changes`, the Q5 search field, `Undo exclusion`, answer checkboxes, and the group decision selects.
- `Shift+Tab` was used to move backward through the focus sequence. A reverse traversal from `Next undecided` reached the Data notes disclosure, confirming that the disclosure itself was keyboard reachable.
- `Enter` on question links navigated from Q5 to Q1 and back to Q5.
- `Space` on an answer checkbox changed it from unchecked to checked and a second `Space` changed it back to unchecked.
- `Space` on an expanded `Restore answer ...` checkbox changed it from unchecked to checked; `Clear selection` was then activated so the temporary restore selection was not left pending.
- `Enter` on `Review changes` opened the dialog; `Enter` on `Close` closed it.
- `Escape` closed the dialog.

Accessible names observed:

- Buttons: visible text names such as `Next undecided`, `Review changes`, `Exclude selected answers`, `Create group from selection`, `Clear selection`, `Restore selected answers`, `Undo exclusion`, `Confirm group`, `Merge group`, and `Close`.
- Status select: `Status`.
- Decision selects: `Edit coding decision`.
- Merge selects: names include the group count, for example `Merge this group (14 unique answers · 14 respondent responses) into`.
- Checkboxes: filter labels `Modified`, `Has exclusions`, and `Provider warning`; answer checkboxes were named `Select answer <answer text>`; restore checkboxes were named `Restore answer <answer text>`.
- Search: `Search answers in this question`.
- Question links: numbered question name, status/resolved count, remaining count, unique count, and response count.
- Group cards: exposed in the DOM as labelled `article` elements such as `Review group 1`; their contained answer checkboxes and controls were reachable by keyboard.

### 6. Accessibility tree and DOM semantics — FAIL

Positive observations:

- The DOM snapshot exposed `header`, `aside`, `nav`, `main`, `section`, `region`, `banner`, list, article, native dialog, native details/summary, buttons, selects, checkboxes, and a labelled searchbox.
- The visible heading hierarchy was sensible for the tested screen: file heading `h2`, page heading `h1`, question heading `h2`, and `h3` headings for Active groups and Needs attention.
- The visible controls audit found 118 visible controls, all with a non-negative tab index in the tested state.
- No visible empty buttons were found.
- No visible answer or restore control lacked an accessible name.

Finding:

- Six group cards each expose the same standalone accessible names for `Edit coding decision`, `Confirm group`, and `Merge group`. The group context is visually present and the controls are nested inside labelled articles, but the control names themselves are duplicates in the page-wide accessibility inventory. A screen-reader user navigating by button name alone cannot distinguish the six `Confirm group` or six `Merge group` controls without moving to the surrounding group context.

Exact reproduction:

1. Open Q5 with six active groups.
2. Enumerate buttons and selects in the accessibility tree/DOM.
3. Observe six `Edit coding decision` combobox names, six `Confirm group` button names, and six `Merge group` button names.

### 7. Responsive layout — FAIL

#### Mobile: requested 320px wide; observed CSS viewport about 291px wide

Positive observations:

- Page/body width was approximately 277px and did not exceed the viewport; no page-level horizontal overflow was observed.
- The sidebar stacked above the main content, and the main content occupied the available width.
- Arabic question text remained visible and wrapped.
- The answer search field and visible action controls remained present.
- The long question navigation list became an internal horizontally scrollable region (`nav.question-nav`), rather than creating page-level overflow.

Finding:

- The Review changes dialog was approximately 239px wide with a 226px client width but a 366px scroll width and `overflow-x: auto`. The screenshot shows long review identifiers visibly clipped at the right edge and a horizontal scrollbar inside the dialog. The Close control remained visible and reachable, but the dialog content was not fully usable without horizontal scrolling.

Evidence:

- Main mobile screenshot: `C:\Users\kayya\AppData\Local\Temp\other-clustering-v4-ui-mobile.png`
- Mobile dialog screenshot showing clipped content and horizontal scrollbar: `C:\Users\kayya\AppData\Local\Temp\other-clustering-v4-ui-mobile-dialog.png`

#### Tablet: requested 768px wide; observed CSS viewport about 698px wide

- No page-level horizontal overflow was observed.
- Sidebar and main content stacked into a usable single-column layout.
- Q5 question header, Arabic text, search field, answer lists, selects, and group cards fit within their containers.
- Group cards were approximately 613px wide with no internal horizontal overflow.
- The question navigation remained an internal horizontal scroller, which is expected for the long list of question summaries.
- The Review changes dialog was approximately 647px wide with no measured content overflow; its Close control remained visible.

#### Desktop: requested 1440px wide; observed CSS viewport about 1309px wide

- Sidebar was approximately 340px wide and main content approximately 955px wide.
- Six tested answer group cards were approximately 823px wide with no internal horizontal overflow.
- Arabic text, answer lists, selects, buttons, and action bars fit without page-level clipping or overlap.
- No page-level horizontal overflow or overflowing visible group containers was measured.

### 8. Two-tab stale revision — PASS

Setup: tab A and tab B loaded the same copied review fixture at Q5.

Steps:

1. Keep tab B at revision 7.
2. In tab A, select one answer from Review group 4 and click `Exclude selected answers`.
3. Tab A advanced to revision 8 and reported `Excluded: 1 unique · 1 responses`.
4. Without reloading tab B, select the same still-visible answer and click `Exclude selected answers`.

Observed conflict message in tab B:

> stale review revision 7; current revision is 8. Reload latest state to continue. Reload latest state

The stale action did not add an exclusion in tab B. The answer remained selectable, tab B's excluded summary remained `Excluded from coding (0 unique answers · 0 respondent responses)`, and its history did not gain a new event. Tab A retained its newer exclusion. Reloading tab B and navigating back to Q5 removed the stale banner and loaded current server state.

### 9. Complete and lock — BLOCKED

Expected behavior: completion should set Completed status, disable or remove mutation controls, show read-only guidance, and preserve the locked state on reload.

Observed:

- The top-level status remained `In review`.
- The overview/sidebar exposed a Status filter with an option named `Complete`, but no action to complete or lock the review.
- No button/link/input/select named `Complete review`, `Lock review`, `Mark complete`, or equivalent was present.
- No read-only guidance was present.
- Mutation controls remained available because the review was still in review.

Because the fixture exposed no completion or lock entry point, completion, post-lock mutation state, and locked-state persistence could not be tested.

### 10. Repeated mutation and completion controls — PASS for mutation; BLOCKED for completion

Mutation check:

- Double-activating `Create group from selection` for the same selected answers produced one group (`Review group 6`) and one history event only.
- The second request surfaced the stale-revision message rather than creating a second group.
- No duplicate group, duplicate answer membership, or duplicate create-group history event was observed after reload.

Completion check:

- BLOCKED because no completion/lock control was available to click repeatedly.

### 11. Console, request, images, truncation, and error exposure — FAIL

Positive observations:

- Chrome tab A console warnings/errors: none captured.
- Chrome tab B console warnings/errors: none captured.
- Responsive test tab console warnings/errors: none captured.
- The document contained no image elements, so no broken image was observed.
- No error message exposed file-system paths, credentials, tokens, or other sensitive implementation data.

Failures/limitations:

- The mobile Review changes dialog visibly clipped long identifiers and exposed an internal horizontal scrollbar; see the mobile dialog screenshot path above.
- The selected Browser control exposed console/dev logs but did not expose a network-request inspector. Therefore, a complete failed-request inventory and exact HTTP status capture could not be collected from the browser surface.
- Before the server was started, the first navigation attempt returned Chrome `ERR_CONNECTION_REFUSED` for `127.0.0.1:5000`. This was a setup precondition; after starting the requested `uv run other-cluster review` process, the endpoint loaded normally.
- The Q5 survey question text itself visibly contains the literal `${food_items_total_per_capita}` placeholder. It was treated as fixture/question content rather than an application error or implementation-detail leak.

## Limitations

- Completion and locking were unavailable in the served fixture, so case 9 and the completion portion of case 10 remain blocked.
- The Chrome viewport capability applies a browser-control scale; the requested dimensions and observed CSS `innerWidth` values differed as recorded above. The tests report both requested and observed values.
- Network requests were not directly inspectable through the selected browser-control API. Console logs and visible UI conflict/error messages were collected instead.
- No source code, review source file, or shared production data was edited. Only the temporary copied fixture was mutated by the browser journey, and only the requested report was added to the workspace.
