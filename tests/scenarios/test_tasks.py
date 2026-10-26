"""Plan scenario 1: a draining note sends the next task to the partner with more room."""

from __future__ import annotations

from tests.scenarios.harness import Scenario
from themi.ai.types import ToolResult


async def test_erins_draining_note_routes_the_next_task_to_her_husband(
    scenario: Scenario,
) -> None:
    scenario.primary.queue_tool_calls(
        [
            ("log_energy_note", {"effect": -3, "note": "the call with the bank drained her"}, None),
            (
                "create_task",
                {
                    "title": "text the plumber back",
                    "kind": "text",
                    "effort": 2,
                    "due_date": "",
                    "assign_to": "anyone",
                    "steps": [],
                    "check_in": False,
                    "due_time": "",
                },
                None,
            ),
        ]
    )
    scenario.primary.queue_text(
        "That sounds like a lot. Husband has a bit more room today, so the plumber is his."
    )
    replies = await scenario.say(
        "Erin", "That call with the bank wiped me out. Can someone text the plumber back?"
    )

    assert replies == [
        "That sounds like a lot. Husband has a bit more room today, so the plumber is his."
    ]
    assert not any(ch.isdigit() for reply in replies for ch in reply)  # no score, ever

    # The model was told who and why, in words.
    tool_results = [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult)
    ]
    assert any("assigned to Husband" in r and "more room" in r for r in tool_results)

    task = scenario.app.db.one("SELECT * FROM tasks")
    assert task is not None
    assert task["assignee"] == scenario.member("Husband").id
    assert task["default_owner"] == scenario.member("Erin").id
    assert "Husband seems to have more room" in task["assign_reason"]

    # He gets a two-option nudge at a good moment; Erin gets nothing about it.
    await scenario.advance(hours=10)
    nudge = [t for t in scenario.inbox("Husband") if "text the plumber back" in t]
    assert len(nudge) == 1
    assert scenario.last_buttons("Husband") == ["Done", "Later"]
    assert not any("Done already" in t for t in scenario.inbox("Erin"))

    await scenario.tap("Husband", "Done")
    task = scenario.app.db.one("SELECT status FROM tasks")
    assert task == {"status": "done"}
    assert "Marked done" in scenario.edits("Husband")[-1]["text"]


async def test_later_brings_a_task_back(scenario: Scenario) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    task = await board.create(erin, "Book the dentist", "errand", 1)
    await scenario.advance(hours=10)
    assert any("Book the dentist" in t for t in scenario.inbox("Erin"))

    await scenario.tap("Erin", "Later")
    assert board.get(task.id).status == "snoozed"
    sent_before = len(scenario.inbox("Erin"))

    await scenario.advance(hours=4, minutes=1)
    assert await scenario.run_periodic("tasks.resurface") == 1
    await scenario.advance(hours=10)
    assert board.get(task.id).status == "open"
    assert any("Book the dentist" in t for t in scenario.inbox("Erin")[sent_before:])


def drained_erin_then(title: str, kind: str, assign_to: str) -> list:
    """Erin is worn out, so matching alone would hand her usual tasks to her husband."""
    return [
        ("log_energy_note", {"effect": -3, "note": "the call with the bank drained her"}, None),
        (
            "create_task",
            {
                "title": title,
                "kind": kind,
                "effort": 2,
                "due_date": "",
                "assign_to": assign_to,
                "steps": [],
                "check_in": False,
                "due_time": "",
            },
            None,
        ),
    ]


def task_results(scenario: Scenario) -> list[str]:
    return [
        block.content
        for message in scenario.primary.last_request.messages
        for block in message.content
        if isinstance(block, ToolResult) and block.content.startswith(("Task", "Not created"))
    ]


async def test_a_task_someone_takes_on_stays_theirs(scenario: Scenario) -> None:
    """Feedback bug #2: "I want to process the cardboard" went to the partner."""
    scenario.primary.queue_tool_calls(drained_erin_then("text the plumber back", "text", "me"))
    scenario.primary.queue_text("On your list.")
    await scenario.say("Erin", "I'm wiped, but I'll text the plumber back later")

    task = scenario.app.db.one("SELECT * FROM tasks")
    assert task is not None
    assert task["assignee"] == scenario.member("Erin").id
    assert task["assign_reason"] == "Erin said they'd do it."
    (result,) = task_results(scenario)
    assert "assigned to Erin (the person asking)" in result
    # She's worn out, so the nudge may wait for a better moment; it's hers, in her words.
    (nudge,) = scenario.app.db.query(
        "SELECT member_id, text FROM outbox WHERE kind = 'task' AND text LIKE '%plumber%'"
    )
    assert nudge["member_id"] == scenario.member("Erin").id
    assert nudge["text"].startswith("To do: text the plumber back, whenever it suits.")


async def test_a_task_for_a_named_person_says_who_added_it(scenario: Scenario) -> None:
    scenario.primary.queue_tool_calls(
        drained_erin_then("pick up the dry cleaning", "errand", "husband")
    )
    scenario.primary.queue_text("Passed to him.")
    await scenario.say("Erin", "can you ask Husband to pick up the dry cleaning?")

    task = scenario.app.db.one("SELECT * FROM tasks")
    assert task is not None and task["assignee"] == scenario.member("Husband").id
    assert task["assign_reason"] == "Erin asked for Husband to do it."
    (result,) = task_results(scenario)
    assert "assigned to Husband" in result and "Let Erin know it went to Husband." in result
    await scenario.advance(hours=10)
    assert any(
        t.startswith("To do: pick up the dry cleaning (Erin added this for you), whenever")
        for t in scenario.inbox("Husband")
    )


async def test_an_unknown_name_is_refused(scenario: Scenario) -> None:
    scenario.primary.queue_tool_calls(drained_erin_then("water the plants", "physical", "Bob"))
    scenario.primary.queue_text("Who's Bob?")
    await scenario.say("Erin", "Bob should water the plants")
    (result,) = task_results(scenario)
    assert result.startswith("Not created:") and "Bob" in result
    assert scenario.app.db.scalar("SELECT COUNT(*) FROM tasks") == 0


async def test_matching_still_hands_off_tasks_for_anyone(scenario: Scenario) -> None:
    scenario.primary.queue_tool_calls(drained_erin_then("text the plumber back", "text", "anyone"))
    scenario.primary.queue_text("Husband has it.")
    await scenario.say("Erin", "can someone text the plumber back?")
    task = scenario.app.db.one("SELECT * FROM tasks")
    assert task is not None and task["assignee"] == scenario.member("Husband").id
    await scenario.advance(hours=10)
    assert any("(Erin added this for you)" in t for t in scenario.inbox("Husband"))


async def test_your_own_new_task_isnt_nudged_straight_away(scenario: Scenario) -> None:
    """Erin's rule 2 was a workaround for this: adding a task in chat got an instant
    "Done already, or later?" about the thing she'd just said."""
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "clean the upstairs bathroom",
            "kind": "physical",
            "effort": 3,
            "due_date": "",
            "assign_to": "me",
            "steps": [],
            "check_in": False,
            "due_time": "",
        },
    )
    scenario.primary.queue_text("Added to your list.")
    assert await scenario.say("Erin", "add cleaning the upstairs bathroom") == [
        "Added to your list."
    ]
    await scenario.advance(hours=3, minutes=59)  # 12:59, added at 09:00
    assert not any("upstairs bathroom" in t for t in scenario.inbox("Erin"))
    await scenario.advance(minutes=2)  # 13:01
    nudges = [t for t in scenario.inbox("Erin") if "upstairs bathroom" in t]
    assert len(nudges) == 1 and nudges[0].startswith("To do: clean the upstairs")


async def test_a_task_for_someone_else_still_reaches_them_promptly(scenario: Scenario) -> None:
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "pick up the dry cleaning",
            "kind": "errand",
            "effort": 1,
            "due_date": "",
            "assign_to": "Husband",
            "steps": [],
            "check_in": False,
            "due_time": "",
        },
    )
    scenario.primary.queue_text("Passed to him.")
    await scenario.say("Erin", "can Husband pick up the dry cleaning?")
    await scenario.advance(minutes=30)
    assert any("dry cleaning" in t for t in scenario.inbox("Husband"))


async def test_a_task_due_today_says_so(scenario: Scenario) -> None:
    """Erin's rule 6 asked for this; rules can't change nudge wording, so it's built in."""
    from datetime import date

    board = scenario.app.services.taskboard
    assert board is not None
    erin, husband = scenario.member("Erin"), scenario.member("Husband")
    await board.create(erin, "Book the dentist", "errand", 1, date(2026, 10, 21))  # today
    await board.create(erin, "Return the library books", "errand", 1, date(2026, 10, 30))
    await board.create(erin, "Call the plumber", "call", 2, date(2026, 10, 21))  # his, from her
    await scenario.advance(hours=1)
    inbox = scenario.inbox("Erin")
    assert "Due today: Book the dentist. Done already, or later?" in inbox
    assert not any("library books" in t for t in inbox)  # not until it's due (bug #14)
    assert any(
        t.startswith("Due today: Call the plumber (Erin added this for you).")
        for t in scenario.inbox("Husband")
    )
    assert husband.id != erin.id


async def test_due_today_is_judged_when_the_nudge_goes_out(scenario: Scenario) -> None:
    from datetime import date

    board = scenario.app.services.taskboard
    assert board is not None
    await scenario.advance(hours=13)  # 22:00 Wednesday: Erin's quiet hours
    await board.create(scenario.member("Erin"), "Book the dentist", "errand", 1, date(2026, 10, 22))
    await scenario.advance(hours=10, minutes=1)  # 08:01 Thursday, the due date
    assert "Due today: Book the dentist. Done already, or later?" in scenario.inbox("Erin")


async def test_a_task_for_later_today_waits_for_its_time(scenario: Scenario) -> None:
    """Bug #14: "Today at around 2, remind me to answer the tutoring email" was asked
    about straight away. The clock starts on Wednesday 21 October at 09:00."""
    scenario.primary.queue_tool_call(
        "create_task",
        {
            "title": "Answer the tutoring email",
            "kind": "text",
            "effort": 1,
            "due_date": "2026-10-21",
            "due_time": "14:00",
            "assign_to": "me",
            "steps": [],
            "check_in": False,
        },
    )
    scenario.primary.queue_text("I'll remind you at 2.")
    await scenario.say("Erin", "Today around 2, remind me to answer the tutoring email")
    await scenario.advance(hours=4, minutes=59)  # 13:59
    assert not any("tutoring" in t for t in scenario.inbox("Erin")[1:])
    await scenario.advance(minutes=2)  # 14:01
    assert any(t.startswith("Due today: Answer the tutoring email") for t in scenario.inbox("Erin"))


async def test_a_task_isnt_prompted_before_its_day(scenario: Scenario) -> None:
    """Bug #14: "do not prompt tasks until they're due"."""
    from datetime import date

    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    await board.create(erin, "Return the library books", "errand", 1, date(2026, 10, 23))
    for _ in range(46):  # hour by hour to Thursday 23:00
        await scenario.advance(hours=1)
    assert not any("library" in t for t in scenario.inbox("Erin"))
    for _ in range(10):  # Friday 09:00
        await scenario.advance(hours=1)
    assert any(t.startswith("Due today: Return the library books") for t in scenario.inbox("Erin"))


async def test_task_nudges_come_one_at_a_time(scenario: Scenario) -> None:
    """Idea #11: "only prompt one task at a time". Four nudges had landed together at 08:00."""
    from datetime import date

    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    today = date(2026, 10, 21)
    for title in ("Book the dentist", "Return the books", "Call the vet"):
        await board.create(erin, title, "errand", 1, today, assignee=erin)

    def nudged() -> list[str]:
        return [t for t in scenario.inbox("Erin") if t.startswith("Due today:")]

    assert len(nudged()) == 1
    await scenario.tap("Erin", "Done")  # answered: the next one may come
    await scenario.advance(minutes=1)
    assert len(nudged()) == 2
    await scenario.advance(hours=1)  # not answered yet: the third waits
    assert len(nudged()) == 2
    await scenario.advance(hours=1, minutes=1)  # two hours unanswered: it comes anyway
    assert len(nudged()) == 3
