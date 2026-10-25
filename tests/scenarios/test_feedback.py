"""Feedback from the chat: /bug, /idea and plain words, each with a context snapshot."""

import logging

from tests.scenarios.harness import Scenario
from themi.core.feedback import HOW_TO, THANKS, FeedbackBook
from themi.logs import recent_logs

SECRET_LINE = "odd reply with key AIza" + "y" * 35


def book(scenario: Scenario) -> FeedbackBook:
    return FeedbackBook(scenario.app.db)


async def test_a_bug_report_keeps_the_conversation_and_state(scenario: Scenario) -> None:
    scenario.primary.queue_text("King sheets are on the list.")
    await scenario.say("Erin", "what's on the grocery list?")
    await scenario.say("Erin", "/pause meals today")
    # `themi run` attaches recent_logs to the root logger; here, feed it a line directly.
    recent_logs.emit(
        logging.makeLogRecord(
            {"name": "themi.test", "levelname": "WARNING", "levelno": 30, "msg": SECRET_LINE}
        )
    )

    replies = await scenario.say("Erin", "/bug it said king sheets but I removed them")
    (item,) = book(scenario).items()
    assert replies == [THANKS["bug"].format(id=item.id)]
    assert scenario.primary.requests[1:] == []  # the command doesn't call the model

    ctx = item.context
    assert (item.kind, item.text, item.status) == (
        "bug",
        "it said king sheets but I removed them",
        "new",
    )
    assert ctx["member"] == {"id": scenario.member("Erin").id, "name": "Erin", "role": "admin"}
    assert ctx["via"] == "/bug" and ctx["replied_to"] is None
    said = [(m["direction"], m["text"]) for m in ctx["conversation"]]
    assert ("in", "what's on the grocery list?") in said
    assert ("out", "King sheets are on the list.") in said
    assert ctx["settings"]["quiet hours"] == "21:30-08:00"
    assert ctx["settings"]["timezone"] == "America/Los_Angeles"
    assert ctx["ai"] and "api_key" not in str(ctx["ai"])
    assert any("[redacted]" in line for line in ctx["log"])
    assert not any(SECRET_LINE in line for line in ctx["log"])
    assert ctx["settings"]["pauses"].startswith("meals until ")
    assert ctx["local_time"].startswith("Wed 21 Oct 2026 09:")


async def test_reply_marks_the_message_that_went_wrong(scenario: Scenario) -> None:
    scenario.primary.queue_text("Added king sheets to the grocery list.")
    await scenario.say("Erin", "we need king sheets")
    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "morning")

    await scenario.say(
        "Erin",
        "/bug this wasn't added, it was only waiting for my OK",
        reply_to_text="Added king sheets to the grocery list.",
    )
    (item,) = book(scenario).items()
    replied = item.context["replied_to"]
    assert replied["text"] == "Added king sheets to the grocery list."
    assert replied["kind"] == "from Themi chat"


async def test_an_idea(scenario: Scenario) -> None:
    replies = await scenario.say("Husband", "/idea a summary of the week on Sundays")
    (item,) = book(scenario).items()
    assert (item.kind, item.text) == ("idea", "a summary of the week on Sundays")
    assert replies == [THANKS["idea"].format(id=item.id)]
    assert item.context["member"]["name"] == "Husband"


async def test_the_bare_command_explains_itself_and_saves_nothing(scenario: Scenario) -> None:
    assert await scenario.say("Erin", "/bug") == [HOW_TO["bug"]]
    assert await scenario.say("Erin", "/idea") == [HOW_TO["idea"]]
    assert book(scenario).items() == []


async def test_plain_words_go_through_the_tool(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "log_feedback", {"kind": "idea", "summary": "remind me about bins on Sunday nights"}
    )
    scenario.primary.queue_text("Noted that idea, thanks!")
    replies = await scenario.say("Erin", "it would be nice if you reminded me about the bins")
    assert replies == ["Noted that idea, thanks!"]
    (item,) = book(scenario).items()
    assert (item.kind, item.text) == ("idea", "remind me about bins on Sunday nights")
    assert item.context["via"] == "plain words (log_feedback)"


async def test_open_items_are_in_the_snapshot(scenario: Scenario) -> None:
    async def archive(payload: dict, ctx: object) -> str:
        return "Archived."

    scenario.app.services.autonomy.executors.register("gmail.archive")(archive)
    await scenario.app.services.autonomy.stage(
        "email_archive_noise",
        scenario.member("Erin"),
        "Archive 3 promo emails",
        {},
        "gmail.archive",
    )
    await scenario.say("Erin", "/bug test")
    (item,) = book(scenario).items()
    assert "Waiting on you: Archive 3 promo emails" in item.context["open_items"]


async def test_the_commands_are_in_the_menu(scenario: Scenario) -> None:
    menu = dict(scenario.app.services.command_menu())
    assert "bug" in menu and "idea" in menu


async def test_a_reused_message_number_points_at_the_newest_message(scenario: Scenario) -> None:
    """The dev simulator restarts its numbering, so old rows can share a message id."""
    erin = scenario.member("Erin")
    scenario.primary.queue_text("The list is empty.")
    await scenario.say("Erin", "what's on the list?")
    latest = scenario.app.db.one(
        "SELECT telegram_message_id FROM message_log WHERE member_id = ? AND direction = 'out' "
        "ORDER BY id DESC LIMIT 1",
        (erin.id,),
    )
    assert latest is not None
    # Her earlier message (a lower row id) gets the same number, as after a restart.
    scenario.app.db.execute(
        "UPDATE message_log SET telegram_message_id = ? WHERE member_id = ? AND direction = 'in' "
        "AND text = 'what''s on the list?'",
        (latest["telegram_message_id"], erin.id),
    )
    await scenario.say("Erin", "/bug wrong", reply_to_text="The list is empty.")
    (item,) = book(scenario).items()
    assert item.context["replied_to"]["text"] == "The list is empty."
