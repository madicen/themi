"""Erin's bugs #111 and #112 (2026-10-31): "I vacuumed upstairs. And washed the sheets. Though
Michael still needs to put the sheets back on the bed tonight." The tools did it all, but the
reply was rewritten into "Up next: put sheets back on bed for Michael tonight." with two
choices: no confirmations, no warm word, and a tap ran it all again."""

from datetime import date

from tests.scenarios.harness import Scenario
from themi.core.praise import PRAISE

SAID = (
    "I vacuumed upstairs. And washed the sheets. Though Husband still needs to put the "
    "sheets back on the bed tonight"
)


def sheets_for_husband() -> dict:
    return {
        "title": "Put sheets back on bed",
        "kind": "physical",
        "effort": 1,
        "due_date": "2026-10-21",
        "due_time": "23:00",
        "from_time": "",
        "assign_to": "Husband",
        "steps": [],
        "check_in": False,
        "importance": "normal",
    }


async def test_whats_done_is_confirmed_with_a_warm_word(scenario: Scenario) -> None:
    board = scenario.app.services.taskboard
    assert board is not None
    erin = scenario.member("Erin")
    vacuum = await board.create(erin, "Vacuum upstairs bedroom", "physical", 2, date(2026, 10, 21))
    sheets = await board.create(erin, "Change sheets", "physical", 2, date(2026, 10, 21))
    scenario.primary.queue_tool_calls(
        [
            ("complete_task", {"task_id": vacuum.id}, None),
            ("complete_task", {"task_id": sheets.id}, None),
            ("create_task", sheets_for_husband(), None),
        ]
    )
    scenario.primary.queue_text(  # the model's reply that day: no warm words
        'Marked done: "Vacuum upstairs bedroom".\nMarked done: "Change sheets".\n\n'
        'Put "Put sheets back on bed" on Husband\'s list for tonight.'
    )
    (reply,) = await scenario.say("Erin", SAID)
    first, second, rest = reply.split("\n", 2)
    assert first.startswith("Marked done: Vacuum upstairs bedroom. ")
    assert second.startswith("Marked done: Change sheets. ")
    assert first.removeprefix("Marked done: Vacuum upstairs bedroom. ") in PRAISE
    assert second.removeprefix("Marked done: Change sheets. ") in PRAISE
    assert rest.strip() == 'Put "Put sheets back on bed" on Husband\'s list for tonight.'
    (sent,) = [p for p in scenario.telegram.calls("sendMessage") if p["text"] == reply]
    assert not sent.get("reply_markup")  # no choice to tap, so nothing runs it again
    assert not [r for r in scenario.primary.requests if r.op == "structured"]  # no rewrite
