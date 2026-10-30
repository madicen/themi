"""P4: a 👎 on one of Themi's replies marks it as the wrong thing, silently; review labels it
(router miss, model choice, no tool needed) and turns it into an eval case."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx

from tests.evals.scoring import load_cases
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.channels.outbox import Priority
from themi.core.wrong_replies import ReplyReview, decide, report

OLIVE_OIL = "remind me to buy olive oil tomorrow"


async def wrong_grocery_add(scenario: Scenario) -> int:
    """Erin asks for a reminder; the model puts olive oil on the grocery list instead of
    making her a task. Returns the reply's id."""
    scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["olive oil"]})
    scenario.primary.queue_text("Added olive oil to the grocery list.")
    await scenario.say("Erin", OLIVE_OIL)
    return scenario.app.db.scalar("SELECT MAX(id) FROM replies")


def marked(scenario: Scenario) -> list[int]:
    return [r.id for r in ReplyReview(scenario.app.db).unlabelled()]


def strength(scenario: Scenario) -> int:
    return scenario.app.store.get_member(scenario.member("Erin").id).pda_strength


async def test_a_thumbs_down_marks_the_reply_and_says_nothing(scenario: Scenario) -> None:
    reply_id = await wrong_grocery_add(scenario)
    before, sent = strength(scenario), len(scenario.inbox("Erin"))
    assert await scenario.react("Erin", "👎", "Added olive oil to the grocery list.") == []
    assert marked(scenario) == [reply_id]
    assert len(scenario.inbox("Erin")) == sent  # no "was that right?", no reply
    assert strength(scenario) == before  # phrasing doesn't move
    assert scenario.app.db.query("SELECT * FROM message_reactions") == []  # not S5's either

    review = ReplyReview(scenario.app.db)
    (reply,) = review.unlabelled()
    assert reply.message == OLIVE_OIL
    assert reply.said == ("Added olive oil to the grocery list.",)
    assert reply.tools == ("add_to_grocery_list",)
    text = report([reply], "America/Los_Angeles")
    assert f"## Reply {reply_id}, to Erin, Wed 21 Oct 09:00" in text
    assert f"> {OLIVE_OIL}" in text and "Tools run: add_to_grocery_list." in text

    labelled, stub = review.label(reply_id, "create_task")
    assert labelled.label == "model_choice"  # a core tool: it was there to use
    assert stub == {
        "id": f"review-{reply_id}",
        "category": "from_review",
        "message": OLIVE_OIL,
        "from": "Erin",
        "expect": ["create_task"],
        "forbid": ["add_to_grocery_list"],
    }
    assert marked(scenario) == []


async def test_cards_and_nudges_arent_marked(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["saffron"]})
    scenario.primary.queue_text("Want saffron on the list?")
    await scenario.say("Erin", "saffron might be nice")  # not asked for: a card
    card = scenario.app.db.one("SELECT sent_text FROM outbox WHERE kind = 'approval'")
    assert card is not None
    await scenario.react("Erin", "👎", card["sent_text"])
    await scenario.app.outbox.send(
        scenario.member("Erin"), "Time to water the plants?", priority=Priority.URGENT, kind="task"
    )
    await scenario.app.outbox.flush()
    await scenario.react("Erin", "👎", "Time to water the plants?")
    assert marked(scenario) == []


async def test_angry_faces_still_soften_phrasing(scenario: Scenario) -> None:
    await wrong_grocery_add(scenario)
    before = strength(scenario)
    await scenario.react("Erin", "😠")
    assert strength(scenario) == before + 1
    assert marked(scenario) == []


async def test_a_marked_reply_outlives_the_weeks_clean_up_until_labelled(
    scenario: Scenario,
) -> None:
    kept = await wrong_grocery_add(scenario)
    await scenario.react("Erin", "👎")
    scenario.primary.queue_text("Morning!")
    await scenario.say("Erin", "hi")
    unmarked = scenario.app.db.scalar("SELECT MAX(id) FROM replies")

    clock.advance(timedelta(days=8))
    scenario.primary.queue_text("Hello again.")
    await scenario.say("Erin", "hello")  # finishing a reply clears last week's
    ids = [r["id"] for r in scenario.app.db.query("SELECT id FROM replies")]
    assert kept in ids and unmarked not in ids
    assert scenario.app.db.query("SELECT 1 FROM reply_tools WHERE reply_id = ?", (kept,))
    assert scenario.app.db.query("SELECT 1 FROM ai_calls WHERE reply_id = ?", (kept,))

    ReplyReview(scenario.app.db).label(kept, None)  # not wrong after all
    scenario.primary.queue_text("Hi.")
    await scenario.say("Erin", "hey")
    assert kept not in [r["id"] for r in scenario.app.db.query("SELECT id FROM replies")]
    assert not scenario.app.db.query("SELECT 1 FROM ai_calls WHERE reply_id = ?", (kept,))


async def test_bug_reports_name_their_reply(scenario: Scenario) -> None:
    reply_id = await wrong_grocery_add(scenario)
    await scenario.say("Erin", "/bug it should have gone in the pantry")
    (row,) = scenario.app.db.query("SELECT context FROM feedback")
    context = json.loads(row["context"])
    groups = scenario.app.db.scalar("SELECT groups FROM replies WHERE id = ?", (reply_id,))
    assert context["reply"] == {
        "id": reply_id,
        "tools": ["add_to_grocery_list"],
        "groups": [g for g in groups.split(",") if g],
        "groups_added": [],
    }
    feedback = scenario.app.services.feedback
    assert feedback is not None
    text = feedback.book.report(feedback.book.items())
    offered = ", ".join(["core", *context["reply"]["groups"]])
    assert (
        f"**About reply {reply_id}:** tools run: add_to_grocery_list; groups offered: {offered}."
        in text
    )


def test_each_label_kind_from_the_offered_groups() -> None:
    assert decide("none", ("pantry",)) == "no_tool_needed"
    assert decide("add_calendar_event", ()) == "router_miss"  # calendar wasn't chosen
    assert decide("add_calendar_event", ("calendar",)) == "model_choice"
    assert decide("add_calendar_event", (), ("calendar",)) == "model_choice"  # more_tools
    assert decide("create_task", ()) == "model_choice"  # a core tool always goes


async def test_the_case_stub_loads_as_an_eval_case(scenario: Scenario, tmp_path: Path) -> None:
    reply_id = await wrong_grocery_add(scenario)
    await scenario.react("Erin", "👎")
    _, stub = ReplyReview(scenario.app.db).label(reply_id, "create_task")
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [stub]}))
    (case,) = load_cases(path)
    assert (case.message, case.speaker, case.expect, case.forbid) == (
        OLIVE_OIL,
        "Erin",
        ("create_task",),
        ("add_to_grocery_list",),
    )


async def test_reply_times_shows_the_weeks_marks(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    first = await wrong_grocery_add(scenario)
    await scenario.react("Erin", "👎")
    await wrong_grocery_add(scenario)
    await scenario.react("Erin", "👎")
    ReplyReview(scenario.app.db).label(first, "create_task")
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/ai/timing")).text
    assert "2 replies marked this week: model choice (1), 1 not labelled yet." in page
