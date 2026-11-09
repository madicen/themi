"""CK1: the chat's card and the cook screen are two views of one session: a step typed in
Telegram shows on the page at its next poll. The clock starts Wednesday 21 October 2026,
9 am."""

from __future__ import annotations

import httpx

from tests.fixtures.cookbook import load
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.unit.test_cook_screen import ALFREDO, lines


async def test_next_typed_in_telegram_shows_on_the_page(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    load(scenario.app.services)
    await sign_in(scenario, site, "Erin")
    scenario.primary.queue_tool_call("start_cooking", {"recipe": "alfredo sauce", "scale": ""})
    scenario.primary.queue_structured(lines(ALFREDO))
    await scenario.say("Erin", "Let's make the alfredo sauce")
    polled = (await site.get("/session/state")).json()
    assert (polled["phase"], polled["ahead"][0]["text"]) == ("ready", "soak the cashews (10 min)")
    await scenario.say("Erin", "done")  # the soak's done: on to gathering
    again = (await site.get("/session/state")).json()
    assert again["phase"] == "gather" and again["seq"] > polled["seq"]
    assert again["drawn"] != polled["drawn"]  # the page redraws
    page = (await site.get("/session/cook/view")).text
    assert "What it uses" in page and "1 Cup cashews" in page
