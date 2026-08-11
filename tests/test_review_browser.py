from __future__ import annotations

from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from other_cluster.review_file import load_review_file
from other_cluster.review_webapp import create_review_app

from .test_review_file import _review


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
            page.get_by_text("Complete", exact=True).wait_for()
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
