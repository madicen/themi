"""M1: a private journal per person, written once the day is over: what was talked about and
decided, searchable from chat and on the Rules & memory page, and deletable. The clock starts
on Wednesday 21 October 2026, 09:00 (Los Angeles)."""

from __future__ import annotations

from datetime import date, timedelta

import httpx

from tests.fixtures.web import csrf_of, flash, sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.ai.types import ToolResult
from themi.channels.outbox import Priority

WED = date(2026, 10, 21)
PACIFIERS = {
    "topics": ["pacifiers going missing"],
    "decided": ["Keep a basket of pacifiers by the front door"],
}


async def talk_about_pacifiers(scenario: Scenario) -> None:
    scenario.primary.queue_text("A basket by the door could help. Want to try that?")
    await scenario.say("Erin", "how can we stop losing the pacifiers?")
    scenario.primary.queue_text("Good plan.")
    await scenario.say("Erin", "ok let's do the basket by the door")


async def next_day(scenario: Scenario, hour: int = 1) -> object:
    target = clock.now().replace(year=2026, month=10, day=22, hour=hour, minute=0)
    clock.advance(target - clock.now())
    return await scenario.run_periodic("memory.journal")


def tool_result(scenario: Scenario) -> str:
    """What the last tool call gave the model."""
    return next(
        block.content
        for message in reversed(scenario.primary.last_request.messages)
        for block in message.content
        if isinstance(block, ToolResult)
    )


def entries(scenario: Scenario, name: str) -> list[tuple[str, str, str]]:
    rows = scenario.app.db.query(
        "SELECT day, topics, decided FROM journal_entries WHERE member_id = ? ORDER BY day",
        (scenario.member(name).id,),
    )
    return [(r["day"], r["topics"], r["decided"]) for r in rows]


async def test_the_day_is_written_up_once_its_over(scenario: Scenario) -> None:
    await talk_about_pacifiers(scenario)
    assert await scenario.run_periodic("memory.journal") == 0  # the day isn't over
    scenario.primary.queue_structured(PACIFIERS)
    assert await next_day(scenario) == 1
    request = scenario.primary.last_request
    assert '<data source="conversation">' in request.prompt
    assert "Erin: how can we stop losing the pacifiers?" in request.prompt
    assert "Themi: A basket by the door could help." in request.prompt
    assert entries(scenario, "Erin") == [
        (
            WED.isoformat(),
            '["pacifiers going missing"]',
            '["Keep a basket of pacifiers by the front door"]',
        )
    ]
    assert entries(scenario, "Husband") == []  # he didn't talk to Themi
    assert await scenario.run_periodic("memory.journal") == 0  # once


async def test_only_themis_own_messages_arent_written_up(scenario: Scenario) -> None:
    await scenario.app.outbox.send(
        scenario.member("Husband"), "Bins go out tonight.", priority=Priority.URGENT, kind="task"
    )
    await scenario.app.outbox.flush()
    await next_day(scenario)
    assert entries(scenario, "Husband") == []
    assert scenario.primary.pending("structured") == 0


async def test_a_model_outage_waits_for_the_next_hour(scenario: Scenario) -> None:
    await talk_about_pacifiers(scenario)
    scenario.primary.fail(1, status=400, op="structured")  # neither backend answers
    scenario.fallback.fail(1, status=400, op="structured")
    assert await next_day(scenario) == 0
    assert entries(scenario, "Erin") == []
    scenario.primary.queue_structured(PACIFIERS)
    assert await next_day(scenario, hour=2) == 1


async def test_asking_about_an_earlier_day_searches_their_own_journal(
    scenario: Scenario,
) -> None:
    await talk_about_pacifiers(scenario)
    scenario.primary.queue_structured(PACIFIERS)
    await next_day(scenario, hour=9)

    scenario.primary.queue_tool_call("search_journal", {"query": "pacifiers"})
    scenario.primary.queue_text("You decided to keep a basket of them by the front door.")
    await scenario.say("Erin", "what did we decide about the pacifiers?")
    result = tool_result(scenario)
    assert "From their journal" in result
    assert (
        "Wed 21 Oct 2026: talked about pacifiers going missing. Decided: Keep a basket of "
        "pacifiers by the front door." in result
    )

    scenario.primary.queue_tool_call("search_journal", {"query": "pacifier"})
    scenario.primary.queue_text("Nothing about that.")
    await scenario.say("Husband", "what did we decide about the pacifier?")
    assert "Nothing in their journal about that" in tool_result(scenario)


async def test_the_journal_on_the_rules_and_memory_page(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await talk_about_pacifiers(scenario)
    scenario.primary.queue_structured(PACIFIERS)
    await next_day(scenario, hour=9)

    await sign_in(scenario, site, "Husband")
    assert "Keep a basket" not in (await site.get("/knowledge")).text  # Erin's only

    await site.post("/logout", data={"csrf": csrf_of((await site.get("/")).text)})
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/knowledge")).text
    assert "Wednesday 21 October" in page
    assert "Decided: Keep a basket of pacifiers by the front door" in page
    assert "Keep a basket" in (await site.get("/knowledge?q=pacifier")).text  # word endings
    assert "Nothing in your journal about that" in (await site.get("/knowledge?q=plumber")).text

    (row,) = scenario.app.db.query("SELECT id FROM journal_entries")
    deleted = await site.post(f"/journal/{row['id']}/delete", data={"csrf": csrf_of(page)})
    assert deleted.status_code == 303
    page = await flash(site, "/knowledge")
    assert "Deleted that day from your journal." in page
    assert "Keep a basket" not in page
    assert entries(scenario, "Erin") == [(WED.isoformat(), "[]", "[]")]  # not written again
    assert await scenario.run_periodic("memory.journal") == 0


async def test_someone_elses_entry_cant_be_deleted(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await talk_about_pacifiers(scenario)
    scenario.primary.queue_structured(PACIFIERS)
    await next_day(scenario, hour=9)
    csrf = await sign_in(scenario, site, "Husband")
    (row,) = scenario.app.db.query("SELECT id FROM journal_entries")
    await site.post(f"/journal/{row['id']}/delete", data={"csrf": csrf})
    assert "That entry isn&#39;t one of yours." in await flash(site, "/knowledge")
    assert entries(scenario, "Erin")[0][2] != "[]"


async def test_a_missed_day_is_caught_up(scenario: Scenario) -> None:
    await talk_about_pacifiers(scenario)
    clock.advance(timedelta(days=2))
    scenario.primary.queue_structured(PACIFIERS)
    assert await scenario.run_periodic("memory.journal") == 1
    assert entries(scenario, "Erin")[0][0] == WED.isoformat()
