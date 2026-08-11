from __future__ import annotations

import copy
import json
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from other_cluster.review_file import load_review_file
from other_cluster.review_webapp import create_review_app

from .test_review_completion import _complete_ready_review
from .test_review_file import _review


def test_review_changes_draft_gate_and_explicit_locking_journey(tmp_path: Path) -> None:
    document = _complete_ready_review(tmp_path)
    review_path = tmp_path / "browser-ready-review.json"
    review_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            finish = page.get_by_role("button", name="Finish review")
            finish.click()
            dialog = page.get_by_role("dialog", name="Review changes")
            expect(dialog.get_by_text("No blocking failures.")).to_be_visible()
            dialog.get_by_role("button", name="Close").click()

            page.get_by_label("Edit coding decision").first.select_option(
                label="1 · Lebanese · لبناني"
            )
            finish.click()
            complete = dialog.get_by_role("button", name="Complete and lock review")
            expect(complete).to_be_disabled()
            expect(dialog).to_contain_text("local decision draft")
            dialog.get_by_role("button", name="Close").click()
            page.get_by_role("button", name="Discard draft").click()

            finish.click()
            complete = dialog.get_by_role("button", name="Complete and lock review")
            complete.click()
            expect(dialog.get_by_text("permanently locks")).to_be_visible()
            dialog.get_by_role("button", name="Yes, complete and lock review").click()
            expect(page.locator("#review-status")).to_have_text("Completed")
            expect(page.get_by_text("Review completed and locked.")).to_be_visible()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert load_review_file(review_path)["status"] == "complete"


def _append_provider_warning_question(review_path: Path) -> None:
    document = json.loads(review_path.read_text(encoding="utf-8"))
    question = copy.deepcopy(document["questions"][0])
    question["question_id"] = "B6_other"
    question["source_column"] = "B6_other"
    question["question_text"] = {
        "english": "Second question",
        "arabic": "السؤال الثاني",
    }
    proposal = question["automatic_groups"][0]["provider_proposal"]
    proposal.update(
        {
            "decision": "provider_error",
            "selected_choice_value": None,
            "english_label": None,
            "arabic_label": None,
            "rejection_reason": None,
            "provider_error": "HTTP 503",
        }
    )
    question["workspace"]["active_groups"][0]["decision"] = None
    document["questions"].append(question)
    review_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _append_question(review_path: Path, question_id: str) -> None:
    document = json.loads(review_path.read_text(encoding="utf-8"))
    question = copy.deepcopy(document["questions"][0])
    question["question_id"] = question_id
    question["source_column"] = question_id
    question["question_text"] = {"english": question_id, "arabic": question_id}
    document["questions"].append(question)
    review_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def test_progress_filters_search_and_next_undecided_journey(tmp_path: Path) -> None:
    _, review_path = _review(tmp_path)
    _append_provider_warning_question(review_path)
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            expect(page.locator("#sidebar-completion-count")).to_have_text("0/2")
            first = page.get_by_role("link", name="1. B5_other", exact=False)
            expect(first).to_contain_text("Resolved 0 · Remaining 2")
            expect(first).to_contain_text("4 unique · 5 responses")

            second = page.get_by_role("link", name="2. B6_other", exact=False)
            second.click()
            header = page.get_by_role("banner", name="Question progress")
            expect(header).to_contain_text("0/1 confirmed groups")
            expect(header).to_contain_text("1 needs-review group")
            expect(header).to_contain_text("Needs attention: 1 unique · 1 response")
            expect(header).to_contain_text("Excluded: 0 unique · 0 responses")
            page.get_by_role("article", name="Review group 1").get_by_text(
                "Provider warning", exact=True
            ).wait_for()

            filters = page.get_by_role("region", name="Question filters")
            filters.get_by_label("Provider warning").check()
            expect(
                page.get_by_role("link", name="1. B5_other", exact=False)
            ).to_have_count(0)
            expect(
                page.get_by_role("link", name="2. B6_other", exact=False)
            ).to_have_count(1)
            filters.get_by_label("Status").select_option(label="Not started")
            expect(
                page.get_by_role("link", name="2. B6_other", exact=False)
            ).to_have_count(1)

            search = page.get_by_label("Search answers in this question")
            search.fill("A")
            expect(page.get_by_text("a", exact=True)).to_be_visible()
            expect(page.locator("mark")).to_have_text("a")
            expect(page.get_by_text("b", exact=True)).to_have_count(0)
            page.get_by_label("Select answer a").check()
            page.get_by_label("Search answers in this question").fill("d")
            expect(page.get_by_label("Select answer d")).to_be_visible()
            actions = page.get_by_role("region", name="Selection actions")
            expect(actions).to_contain_text("1 selected answer hidden by search")

            page.get_by_role("button", name="Next undecided").click()
            expect(page.get_by_label("Search answers in this question")).to_have_value(
                ""
            )
            expect(page.get_by_role("article", name="Review group 1")).to_be_focused()
            page.get_by_role("button", name="Next undecided").click()
            expect(page.get_by_label("Select answer d")).to_be_focused()
            page.get_by_role("button", name="Next undecided").click()
            expect(page.get_by_role("article", name="Review group 1")).to_be_focused()

            page.get_by_role("button", name="Clear filters").click()
            page.get_by_label("Select answer d").check()
            page.get_by_role("region", name="Selection actions").get_by_role(
                "button", name="Exclude selected answers"
            ).click()
            page.get_by_text("Selected answers excluded.").wait_for()
            expect(
                page.get_by_role("link", name="2. B6_other", exact=False)
            ).to_contain_text("Resolved 2 · Remaining 1")

            combinations = [
                ("all", True, False, False, 1),
                ("all", False, True, False, 1),
                ("all", True, True, False, 1),
                ("all", True, False, True, 1),
                ("all", False, True, True, 1),
                ("not_started", True, False, False, 0),
                ("in_progress", True, True, True, 1),
            ]
            for (
                status,
                modified,
                exclusions,
                provider_warning,
                expected,
            ) in combinations:
                filters.get_by_label("Status").select_option(status)
                filters.get_by_label("Modified").set_checked(modified)
                filters.get_by_label("Has exclusions").set_checked(exclusions)
                filters.get_by_label("Provider warning").set_checked(provider_warning)
                expect(
                    page.get_by_role("link", name="1. B5_other", exact=False)
                ).to_have_count(0)
                expect(
                    page.get_by_role("link", name="2. B6_other", exact=False)
                ).to_have_count(expected)
            expect(
                page.get_by_role("link", name="2. B6_other", exact=False)
            ).to_have_count(1)
            page.get_by_label("Search answers in this question").fill("b")
            expect(page.get_by_role("article", name="Review group 1")).to_contain_text(
                "b"
            )
            page.get_by_label("Search answers in this question").fill("A")
            excluded = page.get_by_role("group", name="Excluded from coding")
            expect(excluded).to_have_attribute("open", "")
            expect(excluded.get_by_label("Restore answer a")).to_be_visible()
            excluded.get_by_label("Restore answer a").check()
            page.get_by_label("Search answers in this question").fill("b")
            expect(page.get_by_role("region", name="Restore actions")).to_contain_text(
                "1 selected answer hidden by search"
            )

            filters.get_by_label("Status").select_option(label="Complete")
            page.get_by_role("button", name="Next undecided").click()
            page.get_by_text("No undecided items in this view.").wait_for()
            page.get_by_role("button", name="Clear filters").click()
            expect(filters.get_by_label("Status")).to_have_value("all")
            expect(filters.get_by_label("Provider warning")).not_to_be_checked()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_next_undecided_clears_selection_when_crossing_questions(
    tmp_path: Path,
) -> None:
    _, review_path = _review(tmp_path)
    _append_provider_warning_question(review_path)
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            next_button = page.get_by_role("button", name="Next undecided")

            next_button.click()
            next_button.click()
            page.get_by_label("Select answer d").check()
            next_button.click()
            expect(page.get_by_role("article", name="Review group 1")).to_be_focused()
            next_button.click()
            next_button.click()

            expect(page.get_by_role("article", name="Review group 1")).to_be_focused()
            expect(page.get_by_label("Select answer d")).not_to_be_checked()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_next_undecided_advances_from_complete_question_in_workbook_order(
    tmp_path: Path,
) -> None:
    _, review_path = _review(tmp_path)
    _append_question(review_path, "B6_other")
    _append_question(review_path, "B7_other")
    document = json.loads(review_path.read_text(encoding="utf-8"))
    first_workspace = document["questions"][0]["workspace"]
    first_workspace["active_groups"][0]["member_processing_ids"].extend(
        first_workspace["needs_attention"]
    )
    first_workspace["active_groups"][0]["review_state"] = "confirmed"
    first_workspace["needs_attention"] = []
    review_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            page.get_by_role("button", name="Next undecided").click()
            expect(page.get_by_role("heading", name="B6_other")).to_be_visible()
            expect(page.get_by_role("article", name="Review group 1")).to_be_focused()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_next_undecided_continues_after_resolving_current_target(
    tmp_path: Path,
) -> None:
    _, review_path = _review(tmp_path)
    _append_question(review_path, "B6_other")
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            next_button = page.get_by_role("button", name="Next undecided")

            next_button.click()
            next_button.click()
            next_button.click()
            expect(page.get_by_role("heading", name="B6_other")).to_be_visible()
            page.get_by_role("button", name="Confirm group").click()
            page.get_by_text("Group confirmed.").wait_for()
            next_button.click()
            expect(page.get_by_label("Select answer d")).to_be_focused()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_filter_navigation_clears_selection_and_preserves_draft_recovery(
    tmp_path: Path,
) -> None:
    _, review_path = _review(tmp_path)
    _append_provider_warning_question(review_path)
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            page.get_by_label("Select answer d").check()
            page.get_by_label("Edit coding decision").select_option("existing_choice:1")
            filters = page.get_by_role("region", name="Question filters")
            filters.get_by_label("Provider warning").check()

            draft = page.get_by_role("region", name="Unsaved decision draft")
            expect(draft.get_by_role("button", name="Return to draft")).to_be_visible()
            expect(
                draft.get_by_role("button", name="Apply decision changes")
            ).to_be_visible()
            expect(draft.get_by_role("button", name="Discard draft")).to_be_visible()
            draft.get_by_role("button", name="Return to draft").click()
            expect(
                page.get_by_role("heading", name="Country of origin")
            ).to_be_visible()
            expect(filters.get_by_label("Provider warning")).not_to_be_checked()
            page.get_by_role("button", name="Discard draft").click()
            expect(page.get_by_label("Select answer d")).not_to_be_checked()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_answer_search_preserves_ime_composition_and_unicode_highlight(
    tmp_path: Path,
) -> None:
    _, review_path = _review(tmp_path)
    document = json.loads(review_path.read_text(encoding="utf-8"))
    document["questions"][0]["answers"][0]["text"] = "İx"
    document["questions"][0]["answers"][1]["text"] = "ΟΣ"
    document["questions"][0]["answers"][2]["text"] = "Straße ος"
    review_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            search = page.get_by_label("Search answers in this question")

            search.evaluate(
                """element => {
                  element.dataset.compositionProbe = "alive";
                  element.dispatchEvent(new CompositionEvent("compositionstart", {data: "x", bubbles: true}));
                  element.value = "x";
                  element.dispatchEvent(new InputEvent("input", {data: "x", inputType: "insertCompositionText", isComposing: true, bubbles: true}));
                }"""
            )
            expect(search).to_have_attribute("data-composition-probe", "alive")
            search.evaluate(
                'element => element.dispatchEvent(new CompositionEvent("compositionend", {data: "x", bubbles: true}))'
            )
            expect(page.locator("mark")).to_have_text("x")
            page.get_by_label("Search answers in this question").fill("οσ")
            expect(page.get_by_text("ΟΣ", exact=True)).to_be_visible()
            page.get_by_label("Search answers in this question").fill("STRASSE ΟΣ")
            expect(page.locator("mark")).to_have_text("Straße ος")
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_keyboard_exclude_restore_history_and_immediate_undo(tmp_path: Path) -> None:
    _, review_path = _review(tmp_path)
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            for text in ("a", "b", "c", "d"):
                page.get_by_label(f"Select answer {text}").click()
            actions = page.get_by_role("region", name="Selection actions")
            actions.get_by_text(
                "4 unique answers · 5 respondent responses", exact=True
            ).wait_for()
            actions.get_by_role("button", name="Exclude selected answers").click()
            page.get_by_text("Selected answers excluded.").wait_for()
            page.get_by_role("banner", name="Question progress").get_by_text(
                "Complete", exact=True
            ).wait_for()
            expect(page.locator("#sidebar-completion-count")).to_have_text("1/1")
            expect(page.locator("#progress-bar")).to_have_attribute(
                "style", "width: 100%;"
            )
            excluded = page.get_by_role("group", name="Excluded from coding")
            expect(excluded).to_contain_text(
                "4 unique answers · 5 respondent responses"
            )
            expect(excluded).to_contain_text("Latest exclusion")
            assert page.get_by_label("Select answer a").count() == 0

            page.get_by_role("button", name="Undo exclusion").click()
            page.get_by_text("Latest structural change undone.").wait_for()
            page.get_by_label("Select answer a").wait_for()
            page.get_by_text("History (2)").click()
            page.get_by_text("Excluded 4 answers from coding", exact=False).wait_for()
            page.get_by_text("Undid exclusion", exact=False).wait_for()

            for text in ("a", "b", "c", "d"):
                page.get_by_label(f"Select answer {text}").click()
            page.get_by_role("region", name="Selection actions").get_by_role(
                "button", name="Exclude selected answers"
            ).click()
            page.get_by_text("Selected answers excluded.").wait_for()
            page.reload()
            assert page.get_by_role("button", name="Undo exclusion").count() == 0

            page.get_by_role("group", name="Excluded from coding").click()
            page.get_by_label("Restore answer d").click()
            restore = page.get_by_role("region", name="Restore actions")
            restore.get_by_text(
                "1 unique answer · 1 respondent response", exact=True
            ).wait_for()
            restore.get_by_role("button", name="Restore selected answers").click()
            page.get_by_text("Selected answers restored to Needs attention.").wait_for()
            page.get_by_role("heading", name="Needs attention").wait_for()
            page.get_by_label("Select answer d").wait_for()
            assert page.get_by_label("Restore answer d").count() == 0
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    workspace = load_review_file(review_path)["questions"][0]["workspace"]
    assert [entry["operation"] for entry in workspace["history"]] == [
        "exclude_answers",
        "undo",
        "exclude_answers",
        "restore_answers",
    ]
    assert len(workspace["excluded_answers"]) == 3
    assert len(workspace["needs_attention"]) == 1


def test_keyboard_draft_discard_apply_and_confirm_journey(tmp_path: Path) -> None:
    _, review_path = _review(tmp_path)
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            assert page.get_by_text("Your name").count() == 0
            assert page.get_by_text("ground-truth", exact=False).count() == 0
            decision = page.get_by_label("Edit coding decision")

            decision.focus()
            page.keyboard.press("Home")
            page.keyboard.press("ArrowDown")
            page.get_by_role("region", name="Unsaved decision draft").wait_for()
            page.get_by_role("button", name="Discard draft").focus()
            page.keyboard.press("Enter")
            page.get_by_text("Draft discarded").wait_for()
            assert load_review_file(review_path)["revision"] == 0

            decision = page.get_by_label("Edit coding decision")
            decision.focus()
            page.keyboard.press("Home")
            page.keyboard.press("ArrowDown")
            page.get_by_role("button", name="Apply decision changes").focus()
            page.keyboard.press("Enter")
            page.get_by_text("Decision changes applied.").wait_for()
            assert load_review_file(review_path)["revision"] == 1

            decision = page.get_by_label("Edit coding decision")
            decision.focus()
            page.keyboard.press("End")
            english = page.get_by_label("English label")
            english.focus()
            page.keyboard.type("Reviewed category")
            arabic = page.get_by_label("Arabic label")
            arabic.focus()
            page.keyboard.type("فئة مراجعة")
            page.get_by_role("button", name="Apply decision changes").focus()
            page.keyboard.press("Enter")
            page.get_by_text("Decision changes applied.").wait_for()

            confirm = page.get_by_role("button", name="Confirm group")
            expect(confirm).to_be_enabled()
            confirm.focus()
            page.keyboard.press("Enter")
            page.get_by_text("Group confirmed.").wait_for()
            page.get_by_text("Confirmed", exact=True).wait_for()

            page.get_by_label("Select answer a").focus()
            page.keyboard.press("Space")
            same_group_actions = page.get_by_role("region", name="Selection actions")
            destination = same_group_actions.get_by_label("Move selected answers to")
            assert (
                destination.locator("option").filter(has_text="Review group 1").count()
                == 0
            )
            assert same_group_actions.get_by_role(
                "button", name="Move selected answers"
            ).is_disabled()
            same_group_actions.get_by_role("button", name="Clear selection").click()

            page.get_by_label("Select answer a").focus()
            page.keyboard.press("Space")
            expect(page.get_by_label("Select answer a")).to_be_focused()
            page.get_by_label("Select answer d").focus()
            page.keyboard.press("Space")
            expect(page.get_by_label("Select answer d")).to_be_focused()
            actions = page.get_by_role("region", name="Selection actions")
            actions.get_by_text(
                "2 unique answers · 3 respondent responses", exact=True
            ).wait_for()
            actions.get_by_label("Move selected answers to").select_option(
                label="Review group 1"
            )
            actions.get_by_role("button", name="Move selected answers").focus()
            page.keyboard.press("Enter")
            page.get_by_text("Selected answers moved.").wait_for()
            assert page.get_by_role("region", name="Selection actions").count() == 0
            page.get_by_text("Needs review", exact=True).wait_for()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    document = load_review_file(review_path)
    group = document["questions"][0]["workspace"]["active_groups"][0]
    history = document["questions"][0]["workspace"]["history"]
    assert document["revision"] == 4
    assert group["member_processing_ids"] == sorted(
        answer["processing_id"] for answer in document["questions"][0]["answers"]
    )
    assert group["decision"] == {
        "decision": "new_category",
        "selected_choice_value": None,
        "english_label": "Reviewed category",
        "arabic_label": "فئة مراجعة",
    }
    assert group["review_state"] == "needs_review"
    assert [entry["operation"] for entry in history] == [
        "apply_decision",
        "apply_decision",
        "confirm_group",
        "move_answers",
    ]
    assert history[-1]["affected_answer_count"] == 2
    assert history[-1]["affected_response_count"] == 3


def test_keyboard_create_split_and_merge_group_journey(tmp_path: Path) -> None:
    _, review_path = _review(tmp_path)
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            page.get_by_label("Select answer d").focus()
            page.keyboard.press("Space")
            actions = page.get_by_role("region", name="Selection actions")
            actions.get_by_text(
                "1 unique answers · 1 respondent responses", exact=True
            ).wait_for()
            actions.get_by_role("button", name="Create group from selection").click()
            page.get_by_text("Group created from selected answers.").wait_for()
            page.get_by_role("article", name="Review group 2").wait_for()

            page.get_by_label("Select answer a").focus()
            page.keyboard.press("Space")
            actions = page.get_by_role("region", name="Selection actions")
            actions.get_by_text(
                "1 unique answers · 2 respondent responses", exact=True
            ).wait_for()
            actions.get_by_role("button", name="Create group from selection").click()
            page.get_by_text("Group created from selected answers.").wait_for()

            source = page.get_by_role("article", name="Review group 3")
            source.wait_for()
            merge_destination = source.get_by_role("combobox", name="Merge this group")
            expect(merge_destination).to_have_accessible_name(
                "Merge this group (1 unique answers · 2 respondent responses) into"
            )
            merge_destination.select_option(label="Review group 2")
            source.get_by_role("button", name="Merge group").focus()
            page.keyboard.press("Enter")
            page.get_by_text("Groups merged.").wait_for()
            assert page.get_by_role("article", name="Review group 3").count() == 0
            page.get_by_text("History (3)").click()
            page.get_by_text(
                "Merged Review group 3 into Review group 2; retired Review group 3 · revision 3 · 1 unique / 2 responses",
                exact=True,
            ).wait_for()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    document = load_review_file(review_path)
    question = document["questions"][0]
    workspace = question["workspace"]
    answers = {answer["text"]: answer for answer in question["answers"]}
    destination = next(
        group for group in workspace["active_groups"] if group["origin"] == "reviewer"
    )
    assert destination["member_processing_ids"] == [
        answers["a"]["processing_id"],
        answers["d"]["processing_id"],
    ]
    assert destination["decision"] is None
    assert destination["review_state"] == "needs_review"
    assert [entry["operation"] for entry in workspace["history"]] == [
        "create_group",
        "split_group",
        "merge_groups",
    ]
    assert workspace["retired_groups"][-1]["origin"] == "reviewer"


def test_unapplied_draft_only_blocks_structural_changes_to_its_group(
    tmp_path: Path,
) -> None:
    _, review_path = _review(tmp_path)
    app = create_review_app(review_path, working_directory=tmp_path)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")

            page.get_by_label("Select answer d").click()
            page.get_by_role("region", name="Selection actions").get_by_role(
                "button", name="Create group from selection"
            ).click()
            reviewer_group = page.get_by_role("article", name="Review group 2")
            reviewer_group.wait_for()

            automatic_group = page.get_by_role("article", name="Review group 1")
            automatic_group.get_by_label("Edit coding decision").select_option(
                "existing_choice:1"
            )
            page.get_by_role("region", name="Unsaved decision draft").wait_for()

            reviewer_group = page.get_by_role("article", name="Review group 2")
            reviewer_group.get_by_label("Select answer d").click()
            create = page.get_by_role("region", name="Selection actions").get_by_role(
                "button", name="Create group from selection"
            )
            expect(create).to_be_enabled()
            create.click()

            created_group = page.get_by_role("article", name="Review group 3")
            created_group.wait_for()
            page.get_by_role("region", name="Unsaved decision draft").wait_for()
            assert (
                created_group.get_by_role("combobox", name="Merge this group").count()
                == 0
            )

            page.get_by_role("button", name="Discard draft").click()
            created_group = page.get_by_role("article", name="Review group 3")
            created_group.get_by_role("combobox", name="Merge this group").wait_for()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
