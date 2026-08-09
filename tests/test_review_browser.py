from __future__ import annotations

from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from other_cluster.review_file import load_review_file
from other_cluster.review_webapp import create_review_app

from .test_review_file import _review


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

            page.get_by_role("button", name="Confirm group").focus()
            page.keyboard.press("Enter")
            page.get_by_text("Group confirmed.").wait_for()
            page.get_by_text("Confirmed", exact=True).wait_for()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    document = load_review_file(review_path)
    group = document["questions"][0]["workspace"]["active_groups"][0]
    history = document["questions"][0]["workspace"]["history"]
    assert document["revision"] == 3
    assert group["decision"] == {
        "decision": "new_category",
        "selected_choice_value": None,
        "english_label": "Reviewed category",
        "arabic_label": "فئة مراجعة",
    }
    assert group["review_state"] == "confirmed"
    assert [entry["operation"] for entry in history] == [
        "apply_decision",
        "apply_decision",
        "confirm_group",
    ]
