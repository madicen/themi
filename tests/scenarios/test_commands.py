"""/pause, /resume, /tracking, /site, /link and /help, end to end."""

from __future__ import annotations

import httpx

from tests.scenarios.harness import Scenario
from themi.channels.outbox import Priority
from themi.core.commands import LINK_ONLY_GMAIL


async def queue_meal_nudge(scenario: Scenario, text: str = "Lunch idea: soup?") -> None:
    await scenario.app.outbox.send(
        scenario.member("Erin"), text, priority=Priority.NORMAL, kind="meal"
    )


async def test_pause_holds_that_kind_then_lets_it_through(scenario: Scenario) -> None:
    replies = await scenario.say("Erin", "/pause meals today")
    assert replies == [
        "Okay, holding meal reminders until 12:00 AM on Thursday. /resume brings them back sooner."
    ]
    await queue_meal_nudge(scenario)
    await scenario.app.outbox.send(
        scenario.member("Erin"), "Washer's done.", priority=Priority.NORMAL, kind="laundry"
    )
    assert "Washer's done." in scenario.inbox("Erin")
    assert "Lunch idea: soup?" not in scenario.inbox("Erin")
    delivered = await scenario.advance(hours=23)  # past midnight and quiet hours
    assert "Lunch idea: soup?" in delivered


async def test_resume_brings_held_messages_back(scenario: Scenario) -> None:
    await scenario.say("Erin", "/pause everything 3 hours")
    await queue_meal_nudge(scenario)
    assert await scenario.say("Erin", "/resume") == [
        "Back to normal. Anything that was held will come through."
    ]
    assert "Lunch idea: soup?" in await scenario.advance(minutes=1)
    assert await scenario.say("Erin", "/resume") == ["Nothing was paused."]


async def test_pause_with_no_topic_explains_and_lists(scenario: Scenario) -> None:
    await scenario.say("Erin", "/pause laundry 2 hours")
    (reply,) = await scenario.say("Erin", "/pause")
    assert reply.startswith("To pause something, send for example /pause meals today")
    assert "Paused now:\n• laundry nudges until 11:00 AM" in reply


async def test_pause_explains_what_it_didnt_understand(scenario: Scenario) -> None:
    (reply,) = await scenario.say("Erin", "/pause weather today")
    assert "I don't have a topic called 'weather'" in reply
    (reply,) = await scenario.say("Erin", "/pause meals for a bit")
    assert "I didn't catch how long" in reply


async def test_pausing_in_plain_words_through_the_model(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("pause_messages", {"topic": "meals", "duration": "today"})
    scenario.primary.queue_text("No meal nudges for the rest of today.")
    await scenario.say("Erin", "no meal reminders today please")
    await queue_meal_nudge(scenario)
    assert "Lunch idea: soup?" not in scenario.inbox("Erin")


async def test_tracking_lists_your_inputs_with_toggles(scenario: Scenario) -> None:
    (reply,) = await scenario.say("Erin", "/tracking")
    assert reply.startswith("Here's what Themi notices about you. Only you see this.")
    assert "• When you tend to reply, and how quickly: on" in reply
    assert scenario.last_buttons("Erin") == [
        "Stop energy notes",
        "Stop reply timing",
        "Stop device activity",
        "Stop calendar",  # S2
        "Stop reactions",  # S5
    ]
    assert await scenario.tap("Erin", "Stop reply timing") == []  # the list is edited instead
    assert not scenario.app.store.get_member(scenario.member("Erin").id).tracks("message_timing")
    edited = scenario.edits("Erin")[-1]
    assert "• When you tend to reply, and how quickly: off" in edited["text"]
    labels = [
        b["text"] for b in (b for row in edited["reply_markup"]["inline_keyboard"] for b in row)
    ]
    assert labels == [
        "Stop energy notes",
        "Start reply timing",
        "Stop device activity",
        "Stop calendar",
        "Stop reactions",
    ]


async def test_tracking_changes_show_on_the_website(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    from tests.fixtures.web import sign_in

    await scenario.say("Erin", "/tracking")
    await scenario.tap("Erin", "Stop device activity")
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    assert 'name="track_device_activity" >' in page or 'name="track_device_activity">' in page
    assert 'name="track_text_notes" checked' in page


async def test_tracking_only_ever_shows_your_own(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, tracking={"text_notes": False})
    (his,) = await scenario.say("Husband", "/tracking")
    assert "• Notes about how you're doing, when you mention it: on" in his


async def test_site_sends_a_one_time_link_without_a_preview(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/site")
    assert reply.startswith("Here's a sign-in link for the Themi website.")
    url = reply.splitlines()[-1]
    assert url.startswith("http://themi.test/login/")
    sent = scenario.telegram.calls("sendMessage")[-1]
    assert sent["link_preview_options"] == {"is_disabled": True}
    path = url.removeprefix("http://themi.test")
    assert (await site.post(path)).status_code == 303
    assert (await site.post(path)).status_code == 410  # exactly once


async def test_link_only_knows_gmail_for_now(scenario: Scenario) -> None:
    assert await scenario.say("Erin", "/link dropbox") == [LINK_ONLY_GMAIL]


async def test_help_lists_the_commands(scenario: Scenario) -> None:
    (reply,) = await scenario.say("Erin", "/help")
    for command in ("/pending", "/rules", "/pause", "/resume", "/tracking", "/site", "/link"):
        assert command in reply


async def test_commands_are_published_to_telegram(scenario: Scenario) -> None:
    (published,) = scenario.telegram.calls("setMyCommands")
    names = [c["command"] for c in published["commands"]]
    assert {"pending", "rules", "pause", "resume", "tracking", "site", "link", "help"} <= set(names)


async def test_a_sign_in_link_never_reaches_the_model(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/site")
    token = reply.splitlines()[-1].rsplit("/", 1)[-1]
    scenario.primary.queue_text("Glad to help.")
    await scenario.say("Erin", "thanks")
    turn = scenario.primary.last_request.messages[0].text
    assert token not in turn
    assert "/login/[redacted]" in turn  # the model still sees that a link was sent
