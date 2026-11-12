"""P4: a 👎 on one of Themi's replies marks it as the wrong thing, silently; review labels it
(router miss, model choice, no tool needed) and turns it into an eval case."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from tests.evals.scoring import load_cases
from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi import clock
from themi.channels.outbox import Priority
from themi.core import keys
from themi.standard.wrong_replies import ReplyReview, decide, report

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


async def test_a_card_made_by_a_reply_is_marked_and_nudges_arent(scenario: Scenario) -> None:
    # F38c changed this: a 👎 on a card a model reply made marks that reply (it was P4's
    # "cards aren't marked"). Nudges and other cards Themi made on its own still aren't.
    scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["saffron"]})
    scenario.primary.queue_text("Want saffron on the list?")
    await scenario.say("Erin", "saffron might be nice")  # not asked for: a card
    reply_id = scenario.app.db.scalar("SELECT MAX(id) FROM replies")
    card = scenario.app.db.one("SELECT sent_text FROM outbox WHERE kind = 'approval'")
    assert card is not None
    await scenario.react("Erin", "👎", card["sent_text"])
    assert marked(scenario) == [reply_id]
    await scenario.app.outbox.send(
        scenario.member("Erin"), "Time to water the plants?", priority=Priority.URGENT, kind="task"
    )
    await scenario.app.outbox.flush()
    await scenario.react("Erin", "👎", "Time to water the plants?")
    assert marked(scenario) == [reply_id]


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
        "calls": [
            {
                "name": "add_to_grocery_list",
                "arguments": '{"items": ["olive oil"]}',
                "result": "Done automatically (action 1): Added olive oil to the grocery list.",
            }
        ],
        "groups": [g for g in groups.split(",") if g],
        "groups_added": [],
        "shaped": [],  # F30b: nothing the gentle phrasing changed
    }
    feedback = scenario.app.services.maybe(keys.feedback)
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
    page = (await site.get("/dev")).text
    assert "2 replies marked this week: model choice (1), 1 not labelled yet." in page


async def test_a_bug_report_shows_each_tool_call_and_what_it_said(scenario: Scenario) -> None:
    """Bug #110: "figure out why this failed" couldn't be answered, since only the tools'
    names were kept. Each call's arguments and result are kept too, redacted and cut short."""
    scenario.primary.queue_tool_call("complete_task", {"task_id": 99})
    scenario.primary.queue_text("Hmm.")
    await scenario.say("Erin", "the dentist is done")
    reply_id = scenario.app.db.scalar("SELECT MAX(id) FROM replies")
    (row,) = scenario.app.db.query(
        "SELECT arguments, result FROM reply_tools WHERE reply_id = ?", (reply_id,)
    )
    assert json.loads(row["arguments"]) == {"task_id": 99}
    assert "no task with that number" in row["result"]

    await scenario.say("Erin", "/bug it didn't mark it")
    feedback = scenario.app.services.maybe(keys.feedback)
    assert feedback is not None
    text = feedback.book.report(feedback.book.items())
    assert '1. complete_task {"task_id": 99} → ' in text
    assert "There's no task with that number." in text


# ----- F38c: a 👎 on a card marks the reply that made it; a 👎 taken back clears ---------


async def wrong_card(scenario: Scenario) -> tuple[int, dict[str, Any]]:
    """Michael's bug #171 shape: a reply stages the wrong card (approval, with its reply)."""
    scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["saffron"]})
    scenario.primary.queue_text("Want saffron on the list?")
    await scenario.say("Erin", "saffron might be nice")
    reply_id = scenario.app.db.scalar("SELECT MAX(id) FROM replies")
    card = scenario.app.db.one("SELECT * FROM outbox WHERE kind = 'approval'")
    assert card is not None and card["reply_id"] == reply_id
    return reply_id, card


async def test_a_thumbs_down_on_a_replys_card_marks_it_and_declines(scenario: Scenario) -> None:
    reply_id, card = await wrong_card(scenario)
    assert await scenario.react("Erin", "👎", card["sent_text"]) == []
    assert marked(scenario) == [reply_id]
    (action,) = scenario.app.db.query("SELECT status, summary FROM pending_actions")
    assert action["status"] == "declined"
    assert scenario.edits("Erin")[-1]["text"] == f"{action['summary']}\nLeft as is."
    assert scenario.app.db.query("SELECT * FROM message_reactions") == []  # S5 leaves cards

    (reply,) = ReplyReview(scenario.app.db).unlabelled()
    assert reply.cards == ((card["sent_text"], "declined by the 👎"),)
    text = report([reply], "America/Los_Angeles")
    assert f"Card: {card['sent_text']}" in text and "(declined by the 👎)" in text


async def test_a_thumbs_down_on_a_card_themi_made_on_its_own_marks_nothing(
    scenario: Scenario,
) -> None:
    from themi.autonomy import ExecutionContext

    async def archive(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        return "Archived."

    scenario.app.services.autonomy.executors.register("test.archive")(archive)
    outcome = await scenario.app.services.autonomy.stage(
        "email_archive_noise", scenario.member("Erin"), "Archive 3 promo emails", {"count": 3},
        "test.archive",
    )  # fmt: skip
    await scenario.react("Erin", "👎")
    assert marked(scenario) == []
    assert scenario.app.services.autonomy.action(outcome.action.id).status == "declined"


async def test_a_thumbs_down_replaced_by_a_thumbs_up_leaves_it_unmarked(
    scenario: Scenario,
) -> None:
    """Reply 316: 👎 then 👍 two seconds later (a slip in the reaction picker)."""
    reply_id = await wrong_grocery_add(scenario)
    message = "Added olive oil to the grocery list."
    await scenario.react("Erin", "👎", message)
    assert marked(scenario) == [reply_id]
    await scenario.change_reaction("Erin", message, ["👍"], ["👎"])
    assert marked(scenario) == []
    (row,) = scenario.app.db.query("SELECT value FROM message_reactions")
    assert row["value"] == 1


async def test_a_thumbs_down_taken_back_after_labelling_keeps_the_label(
    scenario: Scenario,
) -> None:
    reply_id = await wrong_grocery_add(scenario)
    message = "Added olive oil to the grocery list."
    await scenario.react("Erin", "👎", message)
    ReplyReview(scenario.app.db).label(reply_id, "create_task")
    await scenario.change_reaction("Erin", message, [], ["👎"])
    reply = ReplyReview(scenario.app.db).get(reply_id)
    assert reply is not None and reply.label == "model_choice"
    assert scenario.app.db.scalar("SELECT marked_at FROM replies WHERE id = ?", (reply_id,))
