"""Idea #12: plain language by default; each person can choose gentle phrasing and add their
own notes on how they like things said."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.types import CallKind
from themi.channels.pda import AIRewriter, PdaShield, find_demands


def gentle(scenario: Scenario, name: str, notes: str | None = None) -> None:
    member = scenario.member(name)
    scenario.app.store.update_settings(member, member.id, phrasing="gentle", phrasing_notes=notes)


async def nudge(scenario: Scenario, title: str) -> str:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    await board.create(erin, title, "errand", 1, assignee=erin)
    return scenario.inbox("Erin")[-1]


async def test_plain_by_default_and_gentle_when_chosen(scenario: Scenario) -> None:
    assert scenario.member("Erin").phrasing == "plain"
    assert await nudge(scenario, "Water the plants") == (
        "To do: Water the plants. Done already, or later?"
    )
    await scenario.tap("Erin", "Done")
    gentle(scenario, "Erin")
    assert await nudge(scenario, "Sort the post") == (
        "To do: Sort the post, whenever it suits. Done already, or later?"
    )


async def test_a_demand_is_softened_in_their_style(scenario: Scenario) -> None:
    shield = PdaShield(None)  # the AI is down: the deterministic softener
    erin = scenario.member("Erin")
    plain = await shield.apply("Move the laundry to the dryer.", erin)
    assert plain.text == "Up next: move the laundry to the dryer."
    assert find_demands(plain.text, erin.pda_strength) == []
    soft = await shield.apply("Move the laundry to the dryer.", replace(erin, phrasing="gentle"))
    assert soft.text == "If you're up for it, you could move the laundry to the dryer."


async def test_the_rewriter_is_told_their_style_and_notes(scenario: Scenario) -> None:
    seen: list[str] = []

    class Client:
        async def structured(self, system: str, prompt: str, *a: Any, **kw: Any) -> Any:
            seen.append(system)
            return type("R", (), {"data": {"text": "Laundry: dryer now, or later?", "options": []}})

    class Router:
        def client_for(self, member_id: int, task: Any) -> Client:
            return Client()

    erin = replace(scenario.member("Erin"), phrasing_notes="questions are fine; never 'should'")
    await AIRewriter(Router()).rewrite("Move the laundry.", erin, [], CallKind.INTERACTIVE)  # type: ignore[arg-type]
    assert "Their phrasing: plain" in seen[0]
    assert "<notes>\nquestions are fine; never 'should'\n</notes>" in seen[0]


async def test_the_model_hears_how_they_like_things_said(scenario: Scenario) -> None:
    gentle(scenario, "Erin", notes="two options are nice")
    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "morning")
    turn = scenario.primary.last_request.messages[0].text
    assert "How Erin likes things said: gentle" in turn and "two options are nice" in turn


async def test_saying_it_in_chat_sets_it(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "set_phrasing", {"style": "gentle", "notes": "questions are fine"}
    )
    scenario.primary.queue_text("Got it, softer from now on.")
    await scenario.say("Erin", "can you be a bit softer with me? questions are fine")
    erin = scenario.member("Erin")
    assert (erin.phrasing, erin.phrasing_notes) == ("gentle", "questions are fine")
    assert scenario.member("Husband").phrasing == "plain"  # only hers


async def test_the_settings_page_sets_it(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    form = {
        "csrf": csrf,
        "quiet_start": "21:30",
        "quiet_end": "08:00",
        "daily_limit": "6",
        "pda_enabled": "on",
        "pda_strength": "1",
        "phrasing": "gentle",
        "phrasing_notes": "never say 'should'",
    }
    assert (await site.post("/settings", data=form)).status_code == 303
    erin = scenario.member("Erin")
    assert (erin.phrasing, erin.phrasing_notes) == ("gentle", "never say 'should'")
    assert "never say &#39;should&#39;" in (await site.get("/settings")).text
