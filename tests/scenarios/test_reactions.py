"""S5: reactions on Themi's messages teach it what lands with each person, in words, for the
model and the My week page. Approval cards are left out, and a switch turns it off."""

from __future__ import annotations

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.accounts import SYSTEM
from themi.channels.outbox import Priority

LONG = "Here's the whole story of the week so far. " * 15


async def send(scenario: Scenario, name: str, text: str, kind: str, **extra: object) -> None:
    priority = Priority.REPLY if kind == "chat" else Priority.URGENT
    await scenario.app.outbox.send(
        scenario.member(name),
        text,
        priority=priority,
        kind=kind,
        **extra,  # type: ignore[arg-type]
    )
    await scenario.app.outbox.flush()


def recorded(scenario: Scenario, name: str) -> list[tuple[str, str, int]]:
    rows = scenario.app.db.query(
        "SELECT kind, length, value FROM message_reactions WHERE member_id = ? ORDER BY id",
        (scenario.member(name).id,),
    )
    return [(r["kind"], r["length"], r["value"]) for r in rows]


def lands(scenario: Scenario, name: str) -> str:
    return scenario.app.services.what_lands(scenario.member(name))


async def test_reactions_are_recorded_with_the_kind_and_length(scenario: Scenario) -> None:
    await send(scenario, "Erin", "Water the plants?", "task")
    await scenario.react("Erin", "👍")
    await send(scenario, "Erin", LONG, "summary")
    await scenario.react("Erin", "😕")
    await send(scenario, "Erin", "Sure, done.", "chat")
    await scenario.react("Erin", "🙏")
    await send(scenario, "Erin", "The plumber emailed back.", "email")
    await scenario.react("Erin", "❤")
    assert recorded(scenario, "Erin") == [
        ("nudges", "short", 1),
        ("summaries", "long", -1),
        ("chat replies", "short", 1),
        ("heads-ups", "short", 1),
    ]


async def test_a_check_in_is_told_apart_from_a_nudge(scenario: Scenario) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    run = await board.create(erin, "Go for a run", "physical", 2, check_in=True, nudge=False)
    await send(scenario, "Erin", "Check-in: Go for a run?", "task", dedupe_key=f"task-{run.id}-1")
    await scenario.react("Erin", "👍")
    assert recorded(scenario, "Erin") == [("check-ins", "short", 1)]


async def test_a_later_reaction_replaces_the_first_and_others_dont_count(
    scenario: Scenario,
) -> None:
    await send(scenario, "Erin", "Water the plants?", "task")
    await scenario.react("Erin", "👍")
    await scenario.react("Erin", "👎")
    await scenario.react("Erin", "🔥")  # not one that says how it landed
    assert recorded(scenario, "Erin") == [("nudges", "short", -1)]


async def test_reactions_on_approval_cards_answer_them_and_arent_counted(
    scenario: Scenario,
) -> None:
    await send(scenario, "Erin", "Add milk to the list?\nGo ahead, or not now?", "approval")
    await scenario.react("Erin", "👍")
    assert recorded(scenario, "Erin") == []


async def test_what_lands_in_words_for_the_model(scenario: Scenario) -> None:
    for _ in range(3):
        await send(scenario, "Erin", "Water the plants?", "task")
        await scenario.react("Erin", "👍")
        await send(scenario, "Erin", LONG, "summary")
        await scenario.react("Erin", "👎")
    await send(scenario, "Erin", "Sure.", "chat")
    await scenario.react("Erin", "👍")  # one isn't enough to say anything
    assert lands(scenario, "Erin") == "short nudges do well; long summaries don't"
    assert lands(scenario, "Husband") == ""  # his own, and he hasn't reacted

    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "hi")
    turn = scenario.primary.last_request.messages[0].text
    assert (
        "What lands with Erin, from their reactions: short nudges do well; long summaries don't"
        in turn
    )
    for word in ("score", "%", "3 of"):
        assert word not in lands(scenario, "Erin")


async def test_the_switch_stops_recording_and_hides_the_line(scenario: Scenario) -> None:
    for _ in range(3):
        await send(scenario, "Erin", "Water the plants?", "task")
        await scenario.react("Erin", "👍")
    assert lands(scenario, "Erin") == "short nudges do well"
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(SYSTEM, erin.id, tracking={"reactions": False})
    assert lands(scenario, "Erin") == ""
    await send(scenario, "Erin", "Water the plants?", "task")
    await scenario.react("Erin", "👎")
    assert len(recorded(scenario, "Erin")) == 3


async def test_the_tracking_command_has_the_switch(scenario: Scenario) -> None:
    (reply,) = await scenario.say("Erin", "/tracking")
    assert "How you react to my messages (👍 or 👎), to learn what lands: on" in reply
    await scenario.tap("Erin", "Stop reactions")
    assert not scenario.member("Erin").tracks("reactions")


async def test_my_week_shows_what_lands(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/week")).text
    assert "What lands with you" in page and "Nothing to say yet" in page
    for _ in range(3):
        await send(scenario, "Erin", LONG, "summary")
        await scenario.react("Erin", "👎")
    page = (await site.get("/week")).text
    assert "From your reactions to its messages: long summaries don&#39;t." in page
