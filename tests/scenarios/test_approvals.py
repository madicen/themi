"""Approvals in the chat: buttons, reactions, yes/no, /pending, snooze and expiry."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tests.scenarios.harness import Scenario
from themi import clock
from themi.autonomy import Action, Decision, ExecutionContext
from themi.channels.telegram import NOT_YOURS_TEXT
from themi.core.approvals import ALREADY_TEXT, NOTHING_PENDING_TEXT

PACIFIC = ZoneInfo("America/Los_Angeles")


class Gmail:
    def __init__(self) -> None:
        self.archived: list[dict] = []
        self.failures_left = 0

    async def archive(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        if self.failures_left:
            self.failures_left -= 1
            raise ConnectionError("gmail unreachable")
        self.archived.append(payload)
        return f"Archived {payload['count']} promos."


@pytest.fixture
def gmail(scenario: Scenario) -> Gmail:
    gmail = Gmail()
    executors = scenario.app.services.autonomy.executors
    executors.register("gmail.archive")(gmail.archive)
    executors.register("test.family_archive")(gmail.archive)  # any family-wide category
    return gmail


async def stage(
    scenario: Scenario, name: str, count: int = 3, category: str = "email_archive_noise"
) -> Action:
    """Stage an action the way background work would (not mid-conversation)."""
    executor = "test.family_archive" if category == "grocery_list_add" else "gmail.archive"
    outcome = await scenario.app.services.autonomy.stage(
        category, scenario.member(name), f"Archive {count} promo emails", {"count": count}, executor
    )
    return outcome.action


def ask(count: int = 3) -> str:
    return f"Archive {count} promo emails\nGo ahead, or not now?"


async def test_tapping_go_ahead_runs_it_and_edits_the_message(
    scenario: Scenario, gmail: Gmail
) -> None:
    await stage(scenario, "Erin")
    assert scenario.inbox("Erin")[-1] == ask()
    assert scenario.last_buttons("Erin") == ["Go ahead", "Not now"]

    assert await scenario.tap("Erin", "Go ahead") == []  # the edit is the answer
    assert gmail.archived == [{"count": 3}]
    (edit,) = scenario.edits("Erin")
    assert edit["text"] == "Archive 3 promo emails\nDone. Archived 3 promos."
    assert not edit.get("reply_markup")  # buttons gone


async def test_a_check_reaction_approves(scenario: Scenario, gmail: Gmail) -> None:
    await stage(scenario, "Erin")
    await scenario.react("Erin", "✅")
    assert gmail.archived == [{"count": 3}]
    assert scenario.edits("Erin")[0]["text"].endswith("Done. Archived 3 promos.")


async def test_a_sleep_reaction_snoozes_and_it_comes_back(scenario: Scenario, gmail: Gmail) -> None:
    action = await stage(scenario, "Erin")
    await scenario.react("Erin", "💤")
    assert scenario.app.services.autonomy.action(action.id).status == "snoozed"
    assert scenario.edits("Erin")[0]["text"].endswith("No rush, this will come back later.")

    await scenario.advance(hours=2)
    assert await scenario.run_periodic("approvals.resurface") == 0
    await scenario.advance(hours=1)
    assert await scenario.run_periodic("approvals.resurface") == 1
    assert scenario.inbox("Erin")[-1] == ask()
    await scenario.tap("Erin", "Go ahead")
    assert gmail.archived == [{"count": 3}]


async def test_not_now_snoozes_rather_than_declines(scenario: Scenario, gmail: Gmail) -> None:
    action = await stage(scenario, "Erin")
    await scenario.tap("Erin", "Not now")
    assert scenario.app.services.autonomy.action(action.id).status == "snoozed"
    assert gmail.archived == []


async def test_a_second_tap_is_already_handled(scenario: Scenario, gmail: Gmail) -> None:
    action = await stage(scenario, "Erin")
    await scenario.tap("Erin", "Go ahead")
    again = await scenario.app.approvals.resolve(
        action.id, Decision.APPROVE, scenario.member("Erin")
    )
    assert again == ALREADY_TEXT
    assert gmail.archived == [{"count": 3}]


async def test_the_partner_cant_answer_someone_elses_approval(
    scenario: Scenario, gmail: Gmail
) -> None:
    await stage(scenario, "Erin")
    erin_chat = scenario.member("Erin").telegram_user_id
    husband_chat = scenario.member("Husband").telegram_user_id
    assert erin_chat is not None and husband_chat is not None
    go_ahead = scenario.telegram.last_keyboard(erin_chat)[0]["callback_data"]
    scenario.telegram.tap(husband_chat, go_ahead, 999)
    await scenario.app.channel.poll_once()
    assert gmail.archived == []
    assert scenario.telegram.calls("answerCallbackQuery")[-1]["text"] == NOT_YOURS_TEXT


async def test_pending_lists_everything_open_with_buttons(scenario: Scenario, gmail: Gmail) -> None:
    for count in (1, 2, 3):
        await stage(scenario, "Erin", count)
    replies = await scenario.say("Erin", "/pending")
    assert replies == ["3 things are waiting:", ask(1), ask(2), ask(3)]
    await scenario.tap("Erin", "Go ahead")  # the newest list entry: 3 promos
    assert gmail.archived == [{"count": 3}]
    edited = [e["text"] for e in scenario.edits("Erin")]
    assert edited.count("Archive 3 promo emails\nDone. Archived 3 promos.") == 2  # both copies


async def test_pending_with_nothing_waiting(scenario: Scenario) -> None:
    assert await scenario.say("Erin", "/pending") == [NOTHING_PENDING_TEXT]
    assert scenario.primary.requests == []  # commands don't go to the model


async def test_household_approvals_can_be_answered_by_an_admin(
    scenario: Scenario, gmail: Gmail
) -> None:
    await stage(scenario, "Husband", 2, category="grocery_list_add")
    assert scenario.inbox("Husband")[-1] == ask(2)
    replies = await scenario.say("Erin", "/pending")
    assert replies == ["One thing is waiting:", ask(2)]
    await scenario.tap("Erin", "Go ahead")
    assert gmail.archived == [{"count": 2}]
    assert scenario.edits("Husband")[0]["text"].endswith("Done. Archived 2 promos.")


async def test_personal_approvals_stay_personal(scenario: Scenario, gmail: Gmail) -> None:
    await stage(scenario, "Erin")
    assert await scenario.say("Husband", "/pending") == [NOTHING_PENDING_TEXT]


async def test_yes_answers_the_only_waiting_approval(scenario: Scenario, gmail: Gmail) -> None:
    await stage(scenario, "Erin")
    assert await scenario.say("Erin", "yes") == ["Archived 3 promos."]
    assert gmail.archived == [{"count": 3}]
    assert scenario.edits("Erin")[0]["text"].endswith("Done. Archived 3 promos.")
    assert scenario.primary.requests == []


async def test_not_now_in_words_snoozes(scenario: Scenario, gmail: Gmail) -> None:
    action = await stage(scenario, "Erin")
    await scenario.say("Erin", "not now")
    assert scenario.app.services.autonomy.action(action.id).status == "snoozed"


async def test_no_declines(scenario: Scenario, gmail: Gmail) -> None:
    action = await stage(scenario, "Erin")
    await scenario.say("Erin", "no")
    assert scenario.app.services.autonomy.action(action.id).status == "declined"
    assert scenario.edits("Erin")[0]["text"].endswith("Left as is.")


async def test_yes_with_two_waiting_asks_the_model(scenario: Scenario, gmail: Gmail) -> None:
    await stage(scenario, "Erin", 1)
    await stage(scenario, "Erin", 2)
    scenario.primary.queue_text("Which one: the 1 or the 2 promo cleanup?")
    await scenario.say("Erin", "yes")
    assert gmail.archived == []
    assert (
        "Waiting on you: Archive 1 promo emails" in scenario.primary.last_request.messages[0].text
    )


async def test_unanswered_approvals_lapse_quietly(scenario: Scenario, gmail: Gmail) -> None:
    action = await stage(scenario, "Erin")
    sent_before = len(scenario.inbox("Erin"))
    await scenario.advance(hours=73)
    assert await scenario.run_periodic("approvals.expire") == 1
    assert scenario.app.services.autonomy.action(action.id).status == "expired"
    assert scenario.edits("Erin")[0]["text"].endswith(
        "This one lapsed. Happy to line it up again any time."
    )
    assert len(scenario.inbox("Erin")) == sent_before  # nothing new was sent


async def test_a_failed_action_can_be_retried_from_pending(
    scenario: Scenario, gmail: Gmail
) -> None:
    gmail.failures_left = 1
    await stage(scenario, "Erin")
    await scenario.tap("Erin", "Go ahead")
    assert scenario.edits("Erin")[0]["text"].endswith("It's in /pending to try again.")
    replies = await scenario.say("Erin", "/pending")
    assert (
        replies[-1]
        == "Archive 3 promo emails\nThis one didn't go through earlier. Try again, or leave it?"
    )
    assert scenario.last_buttons("Erin") == ["Try again", "Leave it"]
    await scenario.tap("Erin", "Try again")
    assert gmail.archived == [{"count": 3}]


async def test_an_approval_answered_before_its_message_went_out_is_withdrawn(
    scenario: Scenario, gmail: Gmail
) -> None:
    clock.freeze(datetime(2026, 10, 21, 23, 0, tzinfo=PACIFIC))  # Erin's quiet hours
    await stage(scenario, "Erin")
    assert scenario.inbox("Erin") == []  # held until morning
    replies = await scenario.say("Erin", "/pending")  # she asks anyway
    assert replies == ["One thing is waiting:", ask()]
    await scenario.tap("Erin", "Go ahead")
    sent = await scenario.advance(hours=10)  # morning: the held request must not appear
    assert ask() not in sent
    assert gmail.archived == [{"count": 3}]


async def test_approvals_raised_in_conversation_go_out_straight_away(
    scenario: Scenario, gmail: Gmail
) -> None:
    from themi.core.tools import Proposal, ToolContext, staged_tool

    @staged_tool("archive_promos", "Archive promos", {"count": {"type": "integer"}})
    async def archive_promos(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
        return Proposal(
            "email_archive_noise",
            f"Archive {args['count']} promo emails",
            "gmail.archive",
            {"count": args["count"]},
        )

    scenario.app.services.tools.register(archive_promos)
    clock.freeze(datetime(2026, 10, 21, 23, 0, tzinfo=PACIFIC))  # quiet hours, but she's here
    scenario.primary.queue_tool_call("archive_promos", {"count": 4})
    scenario.primary.queue_text("Lined up for your okay.")
    assert await scenario.say("Erin", "archive the promos") == [ask(4), "Lined up for your okay."]


async def test_yes_after_themi_asked_something_else_goes_to_the_model(
    scenario: Scenario, gmail: Gmail
) -> None:
    """From a dev session: a card, then Themi asked a different question, and the
    person's "yes" (to that question) approved the card instead."""
    from themi.channels.outbox import Priority

    action = await stage(scenario, "Erin")
    erin = scenario.member("Erin")
    await scenario.app.outbox.send(
        erin, "Shall we add them to your tasks instead?", priority=Priority.REPLY
    )
    scenario.primary.queue_text("Great, I'll put it on your tasks.")

    assert await scenario.say("Erin", "yes") == ["Great, I'll put it on your tasks."]
    assert scenario.app.services.autonomy.action(action.id).status == "pending"
    assert gmail.archived == []
    turn = scenario.primary.last_request.messages[0].text
    assert "Waiting on you: Archive 3 promo emails" in turn  # the model still knows about it


async def test_yes_still_answers_the_card_after_a_remark_that_isnt_a_question(
    scenario: Scenario, gmail: Gmail
) -> None:
    from themi.channels.outbox import Priority

    await stage(scenario, "Erin")
    await scenario.app.outbox.send(
        scenario.member("Erin"), "That one's up for your OK.", priority=Priority.REPLY
    )
    assert await scenario.say("Erin", "yes") == ["Archived 3 promos."]
    assert gmail.archived == [{"count": 3}] and scenario.primary.requests == []


async def test_a_reply_claiming_an_add_that_was_declined_is_replaced(
    scenario: Scenario,
) -> None:
    """Evals (approve-ambiguous-yes): two grocery items waiting, a bare "yes", the model tried
    to add them again (declined: already waiting) and replied "Added eggs and rice"."""
    from themi.core.agent import DECLINED_TEXT, NOTHING_CHANGED_TEXT

    services = scenario.app.services
    erin = scenario.member("Erin")
    for item in ("eggs", "rice"):
        await services.autonomy.stage(
            "grocery_list_add", erin, f"{item.title()} for the grocery list",
            {"items": [item]}, "groceries.add",
        )  # fmt: skip
    scenario.primary.queue_tool_call("add_to_grocery_list", {"items": ["eggs", "rice"]})
    scenario.primary.queue_text("Added eggs and rice to the grocery list.")
    assert await scenario.say("Erin", "yes") == [NOTHING_CHANGED_TEXT]
    assert NOTHING_CHANGED_TEXT != DECLINED_TEXT  # the refusal message stays its own
