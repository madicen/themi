"""BD1a: Themi keeps someone company while they work: quietly (Silent Anchor) or in sprints
(Sprint Partner). The clock starts Wednesday 21 October 2026, 9 am."""

from __future__ import annotations

from datetime import date

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai.errors import PermanentError
from themi.core.tasks import Task, TaskBoard


def board(scenario: Scenario) -> TaskBoard:
    assert scenario.app.services.taskboard is not None
    return scenario.app.services.taskboard


def session_row(scenario: Scenario) -> dict:
    row = scenario.app.db.one("SELECT * FROM body_double_sessions ORDER BY id DESC LIMIT 1")
    assert row is not None
    return row


async def taxes(scenario: Scenario) -> Task:
    return await board(scenario).create(scenario.member("Erin"), "Do the taxes", "text", 4)


async def start(scenario: Scenario, text: str, **args: object) -> list[str]:
    call = {"mode": "", "minutes": 0, "task_id": 0, "what": "", **args}
    scenario.primary.queue_tool_call("start_body_double", call)  # its message ends the turn
    return await scenario.say("Erin", text)


async def test_a_quiet_hour_ends_with_done_and_the_task_closed(scenario: Scenario) -> None:
    task = await taxes(scenario)
    replies = await start(scenario, "Sit with me for an hour while I do the taxes",
                          mode="quiet", minutes=60, task_id=task.id)  # fmt: skip
    assert replies == ["I'm here. Going quiet until 10 am."]
    assert session_row(scenario)["energy_level"] in ("low", "medium", "high", None)
    await scenario.advance(minutes=30)
    assert await scenario.run_jobs() == []  # nothing until the hour is up
    await scenario.advance(minutes=30)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's the hour. How did it go?"
    assert scenario.last_buttons("Erin") == ["Done", "Not finished", "A bit longer"]
    await scenario.tap("Erin", "Done")
    assert scenario.edits("Erin")[-1]["text"].startswith("Marked done: Do the taxes.")
    assert board(scenario).get(task.id).status == "done"
    row = session_row(scenario)
    assert row["outcome"] == "finished" and row["mode"] == "silent"
    assert scenario.app.services.outbox.pauses.active(scenario.member("Erin")) == []


async def test_a_sprint_of_two_blocks_with_a_break(scenario: Scenario) -> None:
    replies = await scenario.say("Erin", "/bodydouble sprint")
    assert replies == ["Sprint on: 25 minutes, then a 5-minute break. I'll say when."]
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "That's 25 minutes. Break for 5?"
    assert scenario.last_buttons("Erin") == ["Break", "Keep going", "Stop here"]
    await scenario.tap("Erin", "Break")
    assert scenario.edits("Erin")[-1]["text"] == "Break on, back at 9:30 am."
    await scenario.advance(minutes=5)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "Break's done whenever you are."
    assert scenario.last_buttons("Erin") == ["Carry on", "A bit longer", "Stop here"]
    await scenario.tap("Erin", "Carry on")
    assert scenario.edits("Erin")[-1]["text"] == "Another 25 minutes, then. I'll say when."
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    await scenario.tap("Erin", "Stop here")
    assert scenario.edits("Erin")[-1]["text"] == "Stopping there."
    row = session_row(scenario)
    assert (row["outcome"], row["blocks_done"]) == ("stopped", 2)


async def test_a_sprint_left_unanswered_ends_quietly(scenario: Scenario) -> None:
    await scenario.say("Erin", "/bodydouble sprint")
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    before = len(scenario.inbox("Erin"))
    await scenario.advance(minutes=30)
    await scenario.run_jobs()
    assert session_row(scenario)["ended_at"] is None  # still waiting, still paused
    await scenario.advance(minutes=31)
    await scenario.run_jobs()
    assert session_row(scenario)["outcome"] == "left"
    assert len(scenario.inbox("Erin")) == before  # quietly: nothing said
    assert scenario.edits("Erin")[-1]["text"] == "That's 25 minutes. Break for 5?"
    assert "reply_markup" not in scenario.edits("Erin")[-1] or not (
        scenario.edits("Erin")[-1]["reply_markup"] or {}
    ).get("inline_keyboard")


async def test_a_nudge_waits_for_the_session_then_comes(scenario: Scenario) -> None:
    await scenario.say("Erin", "/bodydouble quiet 30")
    erin = scenario.member("Erin")
    await board(scenario).create(erin, "Book the dentist", "errand", 1, date(2026, 10, 21))
    await scenario.advance(minutes=20)
    assert not any("Book the dentist" in t for t in scenario.inbox("Erin"))
    await scenario.advance(minutes=10)
    await scenario.run_jobs()
    await scenario.tap("Erin", "Not finished")
    assert scenario.edits("Erin")[-1]["text"] == "That's fine. It'll keep for another time."
    await scenario.advance(minutes=1)
    assert any("Book the dentist" in t for t in scenario.inbox("Erin"))


async def test_a_bigger_tasks_nudge_offers_a_body_double(scenario: Scenario) -> None:
    task = await board(scenario).create(scenario.member("Erin"), "Write the essay", "text", 4)
    await board(scenario).prompt(task)
    await scenario.advance(minutes=1)
    assert scenario.last_buttons("Erin") == ["Done", "Later", "Body double"]
    await scenario.tap("Erin", "Body double")  # BD2: writing is deep work, quiet company
    assert scenario.edits("Erin")[-1]["text"] == (
        "Quiet company for this one.\nI'm here. Going quiet until you say you're done."
    )
    assert card_buttons(scenario) == ["Sprints instead", "Step by step instead"]
    assert session_row(scenario)["task_id"] == task.id


async def test_a_break_ends_the_session(scenario: Scenario) -> None:
    await scenario.say("Erin", "/bodydouble")
    await scenario.say("Erin", "/break 10")
    assert session_row(scenario)["outcome"] == "stopped"


async def test_im_done_ends_it_and_marks_the_task(scenario: Scenario) -> None:
    task = await taxes(scenario)
    await start(scenario, "pomodoro the taxes", mode="sprint", task_id=task.id)
    scenario.primary.queue_tool_call("end_body_double", {"finished": True})
    scenario.primary.queue_text("Well done.")  # the done line opens the reply
    replies = await scenario.say("Erin", "I'm done!")
    assert replies[0].startswith("Marked done: Do the taxes.")
    assert board(scenario).get(task.id).status == "done"
    assert session_row(scenario)["outcome"] == "finished"


async def test_stop_here_then_its_done_after_all(scenario: Scenario) -> None:
    task = await taxes(scenario)
    await start(scenario, "pomodoro the taxes", mode="sprint", task_id=task.id)
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    await scenario.tap("Erin", "Stop here")
    assert scenario.edits("Erin")[-1]["text"] == (
        "Stopping there. If Do the taxes is done, tap below."
    )
    await scenario.tap("Erin", "It's done")
    assert board(scenario).get(task.id).status == "done"
    assert session_row(scenario)["outcome"] == "finished"


async def test_the_sprint_lengths_are_theirs(scenario: Scenario) -> None:
    erin = scenario.member("Erin")
    scenario.app.store.update_settings(erin, erin.id, sprint_work_minutes=50,
                                       sprint_break_minutes=10)  # fmt: skip
    replies = await scenario.say("Erin", "/bodydouble pomodoro")
    assert replies == ["Sprint on: 50 minutes, then a 10-minute break. I'll say when."]


# ----- BD1b: Guided Step-Through --------------------------------------------------------------

KITCHEN = [
    "Clear the counter",
    "Load the dishwasher",
    "Wipe the stovetop",
    "Wipe the shelves (Optional/Bonus)",
    "Sweep the floor",
    "Take out the trash",
]


def card(scenario: Scenario) -> str:
    return scenario.edits("Erin")[-1]["text"]


def card_buttons(scenario: Scenario) -> list[str]:
    markup = scenario.edits("Erin")[-1].get("reply_markup") or {}
    return [b["text"] for row in markup.get("inline_keyboard", []) for b in row]


async def kitchen(scenario: Scenario, steps: list[str] | None = KITCHEN) -> Task:
    task = await board(scenario).create(scenario.member("Erin"), "Clean the kitchen",
                                        "physical", 3)  # fmt: skip
    if steps:
        await board(scenario).update(task.id, scenario.member("Erin"), steps=steps)
    return task


async def test_a_six_step_chore_with_back_and_skip(scenario: Scenario) -> None:
    task = await kitchen(scenario)
    replies = await start(scenario, "walk me through the kitchen", mode="steps", task_id=task.id)
    assert replies == ["Step 1 of 6:\n> Clear the counter"]
    assert scenario.last_buttons("Erin") == ["Next", "Done"]
    await scenario.tap("Erin", "Next")
    assert card(scenario) == "Step 2 of 6:\n> Load the dishwasher"
    assert card_buttons(scenario) == ["Back", "Next", "Done"]
    await scenario.tap("Erin", "Back")
    assert card(scenario) == "Step 1 of 6:\n> Clear the counter"
    await scenario.tap("Erin", "Next")
    await scenario.tap("Erin", "Next")
    await scenario.tap("Erin", "Next")
    assert card(scenario) == "Step 4 of 6 (optional):\n> Wipe the shelves (Optional/Bonus)"
    assert card_buttons(scenario) == ["Back", "Skip", "Next", "Done"]
    await scenario.tap("Erin", "Skip")
    assert card(scenario) == "Step 5 of 6:\n> Sweep the floor"
    replies = await scenario.say("Erin", "next")  # typed: a fresh card at the bottom
    assert replies == ["Step 6 of 6:\n> Take out the trash"]
    assert scenario.edits("Erin")[-1]["text"] == "(Carried on below.)"
    await scenario.tap("Erin", "All done")
    assert card(scenario).startswith("Marked done: Clean the kitchen.")
    assert board(scenario).get(task.id).status == "done"
    assert session_row(scenario)["outcome"] == "finished"


async def test_a_task_without_steps_gets_proposed_ones_then_keeps_them(
    scenario: Scenario,
) -> None:
    task = await kitchen(scenario, steps=None)
    scenario.primary.queue_tool_call(
        "start_body_double", {"mode": "steps", "minutes": 0, "task_id": task.id, "what": ""}
    )
    scenario.primary.queue_structured(
        {"steps": [{"text": "Clear the counter.", "optional": False},
                   {"text": "Wipe the shelves", "optional": True},
                   {"text": "Sweep the floor", "optional": False}]}
    )  # fmt: skip
    replies = await scenario.say("Erin", "walk me through cleaning the kitchen")
    assert replies == [
        "Here's how I'd break it up:\n> 1. Clear the counter\n"
        "> 2. Wipe the shelves (Optional/Bonus)\n> 3. Sweep the floor"
    ]
    assert scenario.last_buttons("Erin") == ["Go", "Change them", "Keep these steps", "No steps"]
    assert scenario.primary.requests[-1].prompt.count("<data source=") == 1
    await scenario.tap("Erin", "Keep these steps")
    assert card(scenario) == "Step 1 of 3:\n> Clear the counter"
    assert board(scenario).get(task.id).steps == (
        "Clear the counter", "Wipe the shelves (Optional/Bonus)", "Sweep the floor",
    )  # fmt: skip


async def test_proposed_steps_changed_in_their_words_arent_kept_unless_asked(
    scenario: Scenario,
) -> None:
    scenario.primary.queue_error(PermanentError("no key"), op="structured")
    scenario.fallback.queue_error(PermanentError("no key"), op="structured")
    replies = await scenario.say("Erin", "/bodydouble steps")
    assert replies[0].startswith("I couldn't break it up just now")  # no model: quiet instead
    task = await kitchen(scenario, steps=None)
    scenario.primary.queue_tool_call(
        "start_body_double", {"mode": "steps", "minutes": 0, "task_id": task.id, "what": ""}
    )
    scenario.primary.queue_structured({"steps": [{"text": "Clear the counter", "optional": False}]})
    await scenario.say("Erin", "step by step for the kitchen please")
    await scenario.tap("Erin", "Change them")
    assert card(scenario) == "How would you change them? Tell me in your own words."
    scenario.primary.queue_structured(
        {"steps": [{"text": "Put on music", "optional": False},
                   {"text": "Clear the counter", "optional": False}]}
    )  # fmt: skip
    replies = await scenario.say("Erin", "start with putting music on")
    assert replies == ["Here's how I'd break it up:\n> 1. Put on music\n> 2. Clear the counter"]
    prompt = scenario.primary.requests[-1].prompt
    assert '<data source="their words">\nstart with putting music on\n</data>' in prompt
    await scenario.tap("Erin", "Go")
    assert card(scenario) == "Step 1 of 2:\n> Put on music"
    assert board(scenario).get(task.id).steps == ()  # Go doesn't keep them


async def test_one_gentle_line_when_a_step_takes_a_while(scenario: Scenario) -> None:
    task = await kitchen(scenario)
    await start(scenario, "walk me through the kitchen", mode="steps", task_id=task.id)
    await scenario.advance(minutes=20)
    await scenario.run_jobs()
    assert scenario.inbox("Erin")[-1] == "Still with you. Next step whenever you're ready."
    await scenario.tap("Erin", "Next")
    await scenario.advance(minutes=20)
    await scenario.run_jobs()
    lines = [t for t in scenario.inbox("Erin") if t.startswith("Still with you")]
    assert len(lines) == 1  # never more than one


async def test_no_gentle_line_on_an_optional_step(scenario: Scenario) -> None:
    task = await kitchen(scenario, steps=["Wipe the shelves (Optional/Bonus)", "Sweep"])
    await start(scenario, "walk me through the kitchen", mode="steps", task_id=task.id)
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    assert not any(t.startswith("Still with you") for t in scenario.inbox("Erin"))


async def test_switching_into_steps_keeps_the_time(scenario: Scenario) -> None:
    task = await kitchen(scenario)
    await start(scenario, "keep me company", mode="quiet", task_id=task.id)
    first = session_row(scenario)
    await scenario.advance(minutes=10)
    scenario.primary.queue_tool_call("switch_body_double_mode", {"mode": "steps"})
    replies = await scenario.say("Erin", "let's do it step by step instead")
    assert replies == ["Step 1 of 6:\n> Clear the counter"]
    row = session_row(scenario)
    assert row["started_at"] == first["started_at"] and row["mode"] == "guided"


# ----- BD2: choosing the mode -----------------------------------------------------------------


async def test_three_good_evening_sprints_change_the_pick_for_chores(scenario: Scenario) -> None:
    await scenario.advance(hours=10)  # 7 pm: the evening
    for _ in range(3):
        await start(scenario, "pomodoro the dishes", mode="sprint", minutes=25,
                    what="the dishes")  # fmt: skip
        await scenario.advance(minutes=25)
        await scenario.run_jobs()
        assert scenario.inbox("Erin")[-1] == "That's 25 minutes. How did it go?"
        await scenario.tap("Erin", "Done")
    rows = scenario.app.db.query("SELECT category, outcome FROM body_double_sessions")
    assert [(r["category"], r["outcome"]) for r in rows] == [("chores", "finished")] * 3
    replies = await start(scenario, "keep me company for the dishes", what="the dishes")
    assert replies == [
        "Starting a sprint for this one.\nSprint on: 25 minutes, then a 5-minute break. "
        "I'll say when."
    ]
    assert scenario.last_buttons("Erin") == ["Quiet instead", "Step by step instead"]
    await scenario.tap("Erin", "Quiet instead")
    assert card(scenario) == "Quiet company instead: going quiet until you say you're done."
    assert session_row(scenario)["mode"] == "silent"


# ----- BD3a: the session page -----------------------------------------------------------------


async def test_next_on_the_page_moves_the_chat_card_and_back(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    scenario.app.services.site_url = "https://themi.example.ts.net"
    task = await kitchen(scenario)
    replies = await start(scenario, "walk me through the kitchen", mode="steps", task_id=task.id)
    assert replies == ["Step 1 of 6:\n> Clear the counter"]
    assert scenario.last_buttons("Erin") == ["Next", "Done", "Open"]
    markup = scenario.telegram.last_keyboard(scenario.member("Erin").telegram_user_id or 0)
    assert markup[-1]["web_app"] == {"url": "https://themi.example.ts.net/session"}

    csrf = await sign_in(scenario, site, "Erin")
    state = (await site.get("/session/state")).json()
    moved = await site.post(f"/session/{state['id']}/act", headers={"X-Requested-With": "fetch"},
                            data={"csrf": csrf, "action": "next", "seq": state["seq"]})  # fmt: skip
    assert moved.json()["line"] == "Load the dishwasher"
    assert card(scenario) == "Step 2 of 6:\n> Load the dishwasher"  # the chat card moved too
    assert card_buttons(scenario) == ["Back", "Next", "Done"]

    await scenario.tap("Erin", "Next")  # and a tap in chat shows on the page
    assert (await site.get("/session/state")).json()["step"] == 3


async def test_no_open_button_without_https(scenario: Scenario) -> None:
    scenario.app.services.site_url = "http://127.0.0.1:8080"
    assert await scenario.say("Erin", "/bodydouble quiet 30") == [
        "I'm here. Going quiet until 9:30 am."
    ]
    assert not scenario.telegram.calls("sendMessage")[-1].get("reply_markup")


# ----- BD3b: break chat on the page -----------------------------------------------------------


async def test_break_chat_on_the_page_reaches_telegram_too(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await scenario.say("Erin", "/bodydouble sprint")
    await scenario.advance(minutes=25)
    await scenario.run_jobs()
    await scenario.tap("Erin", "Break")
    csrf = await sign_in(scenario, site, "Erin")
    state = (await site.get("/session/state")).json()
    assert (state["phase"], state["scene"]) == ("break", "cheering")  # a block done
    await scenario.advance(minutes=1)
    assert (await site.get("/session/state")).json()["scene"] == "dozing"
    assert 'class="session-chat-open"' in (await site.get("/session")).text

    scenario.primary.queue_text("Leftover soup, then the pasta tomorrow.")
    after = await site.post("/session/chat", headers={"X-Requested-With": "fetch"},
                            data={"csrf": csrf, "text": "what's for dinner?"})  # fmt: skip
    assert scenario.inbox("Erin")[-1] == "Leftover soup, then the pasta tomorrow."  # Telegram
    chat = after.json()["chat"]
    assert chat[-2:] == [
        {"who": "you", "text": "what's for dinner?"},
        {"who": "themi", "text": "Leftover soup, then the pasta tomorrow."},
    ]
    assert after.json()["scene"] == "idle"  # listening while they chat


async def test_page_chat_outside_a_break_does_nothing(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await scenario.say("Erin", "/bodydouble sprint")
    csrf = await sign_in(scenario, site, "Erin")
    before = len(scenario.primary.requests)
    await site.post("/session/chat", data={"csrf": csrf, "text": "hello"})
    assert len(scenario.primary.requests) == before


# ----- BD4b: a picture for each step ----------------------------------------------------------


async def test_step_twos_picture_is_redone_and_sent_when_asked(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    task = await kitchen(scenario)
    await start(scenario, "walk me through the kitchen", mode="steps", task_id=task.id)
    csrf = await sign_in(scenario, site, "Erin")
    assert (await site.get("/session/state")).json()["picture"] == {"status": "making"}
    await scenario.run_jobs()
    await scenario.tap("Erin", "Next")
    state = (await site.get("/session/state")).json()
    assert state["picture"]["status"] == "ready"
    first_url = state["picture"]["url"]

    scenario.primary.queue_tool_call(
        "redo_step_picture", {"step": 2, "words": "show it from above"}
    )
    scenario.primary.queue_text("Making it again.")
    await scenario.say("Erin", "can you show step 2 from above?")
    await scenario.run_jobs()
    prompt = [r.prompt for r in scenario.primary.requests if r.op == "image"][-1]
    assert '<data source="the step">\nLoad the dishwasher\n</data>' in prompt
    assert '<data source="their words">\nshow it from above\n</data>' in prompt
    assert '<data source="the earlier pictures prompt">' in prompt
    assert (await site.get("/session/state")).json()["picture"]["url"] != first_url

    await site.post("/session/pictures/redo",
                    data={"csrf": csrf, "step": "0", "words": "cleaner, fewer things"})  # fmt: skip
    await scenario.run_jobs()
    prompt = [r.prompt for r in scenario.primary.requests if r.op == "image"][-1]
    assert "cleaner, fewer things" in prompt

    scenario.primary.queue_tool_call("send_step_picture", {"step": 0})
    await scenario.say("Erin", "send me the picture")
    photo = scenario.telegram.calls("sendPhoto")[-1]
    assert photo["caption"] == "Step 2 of 6" and photo["photo_bytes"] > 0
    assert card(scenario).startswith("Step 2 of 6:")  # the chat card stays text
