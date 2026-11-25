"""F62b: "I like to be 30 minutes early for tutoring": events whose title has the words are
planned to be there that early, so the get-ready heads-up comes that much sooner. The
clock starts Wednesday 21 October 2026, 9 am; home → Smile Dental is about 35 min."""

from __future__ import annotations

import httpx

from tests.fakes.gcal_api import FakeGcal
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_travel import ERIN, at, local, ready, tool_result
from themi_google.travel import TravelPreferences

__all__ = ["ready"]


async def thirty_early_for_tutoring(scenario: Scenario) -> str:
    scenario.primary.queue_tool_call("set_event_early", {"words": "tutoring", "minutes": 30})
    scenario.primary.queue_text("I'll plan to have you there 30 minutes early.")
    await scenario.say("Erin", "I like to be 30 minutes early for tutoring")
    return tool_result(scenario)


def tutoring_at_4(ready: FakeGcal) -> None:
    ready.add_event(ERIN, local(16), local(17), summary="Tutoring with G",
                    location="Smile Dental")  # fmt: skip


async def test_the_heads_up_comes_thirty_minutes_sooner_for_tutoring(
    scenario: Scenario, ready: FakeGcal
) -> None:
    said = await thirty_early_for_tutoring(scenario)
    assert said == "Done: I'll plan to have them at tutoring 30 minutes early."
    prefs = scenario.app.store.preferences(scenario.member("Erin").id, TravelPreferences)
    assert prefs.be_early_for == ("tutoring: 30",)
    tutoring_at_4(ready)
    assert await at(scenario, 14, 25) == []  # leave 2:55, get ready from 2:40
    assert await at(scenario, 14, 40) == [
        "Tutoring with G at 4 pm, there by 3:30 pm (30 min early for tutoring), about 35 min "
        "with traffic: leave around 2:55 pm."
    ]


async def test_other_events_keep_their_time(scenario: Scenario, ready: FakeGcal) -> None:
    await thirty_early_for_tutoring(scenario)
    ready.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    assert await at(scenario, 14, 10) == [
        "Dentist at 3 pm, about 35 min with traffic: leave around 2:25 pm."
    ]


async def test_what_they_said_for_that_event_wins(scenario: Scenario, ready: FakeGcal) -> None:
    await thirty_early_for_tutoring(scenario)
    tutoring_at_4(ready)
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call(
        "drive_time", {"event": "tutoring", "address": "", "arrive_by": "15:50"}
    )
    scenario.primary.queue_text("OK.")
    await scenario.say("Erin", "I want to be there at 3:50 for this one")
    result = tool_result(scenario)
    assert "to be there by 3:50 pm, leave around 3:15 pm" in result
    assert "min early for tutoring" not in result


async def test_the_drive_answer_says_why(scenario: Scenario, ready: FakeGcal) -> None:
    await thirty_early_for_tutoring(scenario)
    tutoring_at_4(ready)
    await scenario.run_periodic("calendar.busy")
    scenario.primary.queue_tool_call("drive_time", {"event": "tutoring", "address": ""})
    scenario.primary.queue_text("About that long.")
    await scenario.say("Erin", "When should I leave for tutoring?")
    assert "to be there by 3:30 pm (30 min early for tutoring), leave around 2:55 pm" in (
        tool_result(scenario)
    )


async def test_zero_minutes_stops_it(scenario: Scenario, ready: FakeGcal) -> None:
    await thirty_early_for_tutoring(scenario)
    scenario.primary.queue_tool_call("set_event_early", {"words": "Tutoring", "minutes": 0})
    scenario.primary.queue_text("OK.")
    await scenario.say("Erin", "no need to be early for tutoring any more")
    assert tool_result(scenario) == "Done: no extra time for Tutoring any more."
    prefs = scenario.app.store.preferences(scenario.member("Erin").id, TravelPreferences)
    assert prefs.be_early_for == ()


async def test_a_buffer_rule_is_pointed_at_the_setting(scenario: Scenario) -> None:
    """Rule 20 on the Pi: "Add 30 minutes to the standard travel buffer for tutoring"."""
    scenario.primary.queue_tool_call(
        "propose_rule",
        {
            "summary": "Add 30 minutes to the standard travel buffer for tutoring sessions",
            "text": "Add 30 minutes to the standard travel buffer for tutoring sessions.",
            "kind": "policy", "category": "", "rule_id": 0, "applies_to": "personal",
        },
    )  # fmt: skip
    scenario.primary.queue_text("OK.")
    await scenario.say("Erin", "Add 30 minutes to the travel buffer for tutoring sessions")
    assert "set_event_early" in tool_result(scenario)
    rulebook = scenario.app.services.rulebook
    assert rulebook is not None and rulebook.drafts(scenario.member("Erin")) == []


async def test_the_settings_page_keeps_the_list(
    scenario: Scenario, ready: FakeGcal, site: httpx.AsyncClient
) -> None:
    await thirty_early_for_tutoring(scenario)
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    assert 'name="be_early_for"' in page and "tutoring: 30" in page
