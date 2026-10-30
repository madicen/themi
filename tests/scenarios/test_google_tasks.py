"""GT1a: Google Tasks as an inbox. What someone adds by voice ("Hey Google, add a task...")
lands in their Google Tasks; Themi takes each new item as their message, answers in
Telegram, and removes it. The clock starts on Wednesday 21 October 2026, 09:00 (Los Angeles)."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlsplit

import httpx
import pytest

from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.gtasks_api import FakeGtasks
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN, link
from themi import clock
from themi.connectors.google import TASKS_SCOPE
from themi.connectors.google.oauth import LINK_SCOPES


@pytest.fixture
async def inbox(
    scenario: Scenario, fake_google: FakeGoogle, fake_gtasks: FakeGtasks, site: httpx.AsyncClient
) -> FakeGtasks:
    """Erin's Google account, linked with Google Tasks allowed."""
    await link(scenario, site, fake_google, "Erin", ERIN)
    return fake_gtasks


async def run(scenario: Scenario) -> object:
    handled = await scenario.run_periodic("google_tasks.inbox")
    await scenario.app.outbox.flush()
    return handled


def on_list(scenario: Scenario) -> list[str]:
    groceries = scenario.app.services.groceries
    assert groceries is not None
    return [i.name for i in groceries.needed()]


async def test_a_voice_item_is_handled_as_their_message_then_removed(
    scenario: Scenario, inbox: FakeGtasks
) -> None:
    inbox.add(ERIN, "Milk")
    scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["milk"]})
    scenario.primary.queue_text("Milk's on the grocery list.")
    assert await run(scenario) == 1
    turn = scenario.primary.requests[0].messages[0].text
    assert (
        'Erin asked their Google speaker to add "Milk" to Google Tasks. Take it as something '
        "they asked for." in turn
    )
    assert on_list(scenario) == ["milk"]  # asked for in their own words: no card
    assert scenario.inbox("Erin")[-1] == "Milk's on the grocery list."
    assert inbox.titles(ERIN) == []
    assert await run(scenario) == 0  # nothing left


async def test_my_accounts_says_google_tasks_is_on(
    scenario: Scenario, inbox: FakeGtasks, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    assert "Themi takes what you add by voice to My Tasks" in (await site.get("/accounts")).text


async def test_the_due_date_and_note_go_with_it(scenario: Scenario, inbox: FakeGtasks) -> None:
    inbox.add(ERIN, "Call the plumber", notes="about the leak", due="2026-10-23T00:00:00.000Z")
    scenario.primary.queue_text("I'll remind you on Friday.")
    await run(scenario)
    turn = scenario.primary.requests[0].messages[0].text
    assert (
        'Erin asked their Google speaker to add "Call the plumber" to Google Tasks, due Friday '
        '23 October, with the note "about the leak".' in turn
    )


async def test_items_are_handled_in_order_and_only_once(
    scenario: Scenario, inbox: FakeGtasks
) -> None:
    inbox.add(ERIN, "Milk")
    clock.advance(timedelta(seconds=5))
    inbox.add(ERIN, "Batteries")
    scenario.primary.queue_text("Noted milk.").queue_text("Noted batteries.")
    assert await run(scenario) == 2
    assert scenario.inbox("Erin")[-2:] == ["Noted milk.", "Noted batteries."]

    inbox.fail("delete", 503)  # the next item's delete fails once
    inbox.add(ERIN, "Bread")
    scenario.primary.queue_text("Noted bread.")
    assert await run(scenario) == 1
    assert inbox.titles(ERIN) == ["Bread"]
    assert await run(scenario) == 0  # removed now, and not handled again
    assert inbox.titles(ERIN) == []
    assert scenario.inbox("Erin").count("Noted bread.") == 1


async def test_an_ai_outage_keeps_the_item_for_later(scenario: Scenario, inbox: FakeGtasks) -> None:
    inbox.add(ERIN, "Milk")
    scenario.primary.fail(1, status=400)
    scenario.fallback.fail(1, status=400)
    assert await run(scenario) == 0
    assert inbox.titles(ERIN) == ["Milk"]
    busy = len(scenario.inbox("Erin"))
    assert await run(scenario) == 0  # waits an hour: no busy reply every minute
    assert len(scenario.inbox("Erin")) == busy
    clock.advance(timedelta(hours=1))
    scenario.primary.queue_text("Noted milk.")
    assert await run(scenario) == 1
    assert inbox.titles(ERIN) == []


async def test_done_and_empty_items_are_left_alone(scenario: Scenario, inbox: FakeGtasks) -> None:
    inbox.add(ERIN, "Already done", done=True)
    inbox.add(ERIN, "   ")
    assert await run(scenario) == 0
    assert scenario.primary.pending() == 0


async def test_an_account_linked_without_google_tasks_is_left_alone(
    scenario: Scenario, fake_google: FakeGoogle, fake_gtasks: FakeGtasks, site: httpx.AsyncClient
) -> None:
    (reply,) = await scenario.say("Erin", "/link gmail")
    unticked = tuple(s for s in LINK_SCOPES if s != TASKS_SCOPE)  # linked before GT1a, say
    callback = urlsplit(fake_google.consent(reply.splitlines()[-1], ERIN, scopes=unticked))
    assert (await site.get(f"{callback.path}?{callback.query}")).status_code == 200
    fake_gtasks.add(ERIN, "Milk")
    assert await run(scenario) == 0
    assert fake_gtasks.calls == []
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/accounts")).text
    assert "Google Tasks isn't allowed for this account yet" in page


async def test_a_long_inbox_is_read_page_by_page(scenario: Scenario, inbox: FakeGtasks) -> None:
    inbox.page_size = 2
    for title in ("Milk", "Bread", "Eggs"):
        inbox.add(ERIN, title)
        clock.advance(timedelta(seconds=1))
    for title in ("milk", "bread", "eggs"):
        scenario.primary.queue_text(f"Noted {title}.")
    assert await run(scenario) == 3
    assert inbox.titles(ERIN) == []
