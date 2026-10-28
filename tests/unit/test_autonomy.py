import sqlite3
from datetime import datetime, timedelta
from typing import Any

import pytest

from tests.fixtures.family import SeededFamily
from themi import clock
from themi.accounts import NotFound, PermissionDenied
from themi.autonomy import (
    Autonomy,
    AutonomyError,
    CappedCategory,
    Decision,
    ExecutionContext,
    ExecutorRegistry,
    InvalidTransition,
    Tier,
)

CAPPED = {
    "email_reply",
    "safeway_cart",
    "doordash_order",
    "vendor_call",
    "habit_trial",
    "chore_step_up",  # F6b: Themi never changes a chore's schedule on its own
    "calendar_event_change",  # K3: another's event is never changed without a yes
}
CAN_BE_AUTOMATIC = {
    "email_mark_read",
    "email_archive_noise",
    "grocery_list_add",
    "calendar_write",
    "wall_list_add",
    "list_add",
    "list_delete",
    "calendar_event",
    "calendar_from_email",
    "wall_routine_add",
}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], ExecutionContext]] = []
        self.failures_left = 0

    async def __call__(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        self.calls.append((payload, ctx))
        if self.failures_left:
            self.failures_left -= 1
            raise ConnectionError("gmail unreachable")
        return f"Archived {payload.get('count', 0)} emails."


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def autonomy(family: SeededFamily, recorder: Recorder) -> Autonomy:
    executors = ExecutorRegistry()
    executors.register("gmail.archive")(recorder)
    executors.register("groceries.add")(recorder)
    return Autonomy(family.store, executors)


def events(autonomy: Autonomy, action_id: int) -> list[str]:
    return [row["event"] for row in autonomy.audit_trail(action_id)]


# ----- categories -------------------------------------------------------------


def test_every_category_starts_supervised_with_the_plans_caps(autonomy: Autonomy) -> None:
    categories = {c.name: c for c in autonomy.categories()}
    assert set(categories) == CAPPED | CAN_BE_AUTOMATIC
    assert all(c.tier is Tier.SUPERVISED for c in categories.values())
    assert {n for n, c in categories.items() if c.capped} == CAPPED
    assert categories["grocery_list_add"].scope == "family"
    assert categories["email_reply"].scope == "member"


@pytest.mark.parametrize("name", sorted(CAPPED))
def test_capped_categories_can_never_become_automatic(
    autonomy: Autonomy, family: SeededFamily, name: str
) -> None:
    with pytest.raises(CappedCategory):
        autonomy.grant_tier2(name, via_rule_id=1, by=family.erin)
    assert autonomy.category(name).tier is Tier.SUPERVISED
    with pytest.raises(sqlite3.IntegrityError):  # the database refuses it too
        family.db.execute("UPDATE action_categories SET tier = 2 WHERE name = ?", (name,))


def test_only_admins_change_tiers(autonomy: Autonomy, family: SeededFamily) -> None:
    with pytest.raises(PermissionDenied):
        autonomy.grant_tier2("email_archive_noise", via_rule_id=1, by=family.husband)
    autonomy.grant_tier2("email_archive_noise", via_rule_id=7, by=family.erin)
    category = autonomy.category("email_archive_noise")
    assert category.tier is Tier.AUTOMATIC and category.granted_by_rule == 7
    with pytest.raises(PermissionDenied):
        autonomy.revoke_tier2("email_archive_noise", by=family.husband)
    assert autonomy.revoke_tier2("email_archive_noise", by=family.erin).tier is Tier.SUPERVISED


# ----- Tier 1: staged, then resolved --------------------------------------------


async def test_tier_1_actions_wait_for_approval(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    outcome = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive 3 promo emails", {"count": 3}, "gmail.archive"
    )
    assert outcome.action.status == "pending" and not outcome.action.automatic
    assert recorder.calls == []
    assert [a.id for a in autonomy.awaiting(family.erin)] == [outcome.action.id]


async def test_approving_runs_the_executor_once(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    staged = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive 3 promo emails", {"count": 3}, "gmail.archive"
    )
    done = await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.erin)
    assert done.action.status == "done" and done.message == "Archived 3 emails."
    ((payload, ctx),) = recorder.calls
    assert payload == {"count": 3}
    assert (
        ctx.member.id == family.erin.id
        and ctx.idempotency_key == f"themi-action-{staged.action.id}"
    )
    with pytest.raises(InvalidTransition):
        await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.erin)
    assert len(recorder.calls) == 1
    assert events(autonomy, staged.action.id) == ["staged", "approved", "executed"]
    assert autonomy.audit_trail(staged.action.id)[1]["actor"] == f"member:{family.erin.id}"


async def test_declining_never_runs_it(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    staged = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive", {}, "gmail.archive"
    )
    declined = await autonomy.resolve(staged.action.id, Decision.DECLINE, by=family.erin)
    assert declined.action.status == "declined"
    with pytest.raises(InvalidTransition):
        await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.erin)
    assert recorder.calls == []
    assert events(autonomy, staged.action.id) == ["staged", "declined"]


async def test_a_withdrawn_action_never_runs_and_says_why(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    """Bug #35: a newer card for the same event takes the waiting one's place."""
    told: list[tuple[int, str]] = []

    async def listener(action: Any, reason: str) -> None:
        told.append((action.id, reason))

    autonomy.withdrawn_listeners.append(listener)
    staged = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive", {}, "gmail.archive"
    )
    assert await autonomy.withdraw(staged.action.id, "Replaced by the newer card.")
    assert autonomy.action(staged.action.id).status == "declined"
    assert told == [(staged.action.id, "Replaced by the newer card.")]
    assert not await autonomy.withdraw(staged.action.id, "again")  # answered already
    with pytest.raises(InvalidTransition):
        await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.erin)
    assert recorder.calls == []
    assert events(autonomy, staged.action.id) == ["staged", "withdrawn"]


async def test_snoozed_actions_resurface_later(
    autonomy: Autonomy, family: SeededFamily, frozen_clock: datetime
) -> None:
    staged = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive", {}, "gmail.archive"
    )
    snoozed = await autonomy.resolve(
        staged.action.id, Decision.SNOOZE, by=family.erin, snooze_for=timedelta(hours=2)
    )
    assert snoozed.action.status == "snoozed"
    assert snoozed.action.snoozed_until == frozen_clock + timedelta(hours=2)
    assert autonomy.awaiting(family.erin) == []
    clock.advance(timedelta(hours=1, minutes=59))
    assert autonomy.resurface_snoozed() == []
    clock.advance(timedelta(minutes=1))
    (back,) = autonomy.resurface_snoozed()
    assert back.status == "pending" and back.snoozed_until is None
    assert events(autonomy, staged.action.id) == ["staged", "snoozed", "resurfaced"]


async def test_a_snoozed_action_can_still_be_approved(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    staged = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive", {}, "gmail.archive"
    )
    await autonomy.resolve(staged.action.id, Decision.SNOOZE, by=family.erin)
    done = await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.erin)
    assert done.action.status == "done"


# ----- Tier 2 and Tier 3 --------------------------------------------------------


async def test_tier_2_runs_at_once_and_says_so_in_the_audit(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    autonomy.grant_tier2("email_archive_noise", via_rule_id=3, by=family.erin)
    outcome = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive 2 promos", {"count": 2}, "gmail.archive"
    )
    assert outcome.action.status == "done" and outcome.action.automatic
    assert len(recorder.calls) == 1
    assert events(autonomy, outcome.action.id) == ["staged", "auto_approved", "executed"]


async def test_escalation_makes_a_tier_2_category_ask_again_until_resumed(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    autonomy.grant_tier2("email_mark_read", via_rule_id=3, by=family.erin)
    category = autonomy.escalate("email_mark_read", "the PG&E confirmation didn't arrive")
    assert category.escalated and category.effective_tier is Tier.SUPERVISED
    assert category.tier is Tier.AUTOMATIC  # the grant itself is kept
    staged = await autonomy.stage("email_mark_read", family.erin, "Mark read", {}, "gmail.archive")
    assert staged.action.status == "pending" and recorder.calls == []

    with pytest.raises(PermissionDenied):
        autonomy.resume("email_mark_read", by=family.husband)
    autonomy.resume("email_mark_read", by=family.erin)
    again = await autonomy.stage("email_mark_read", family.erin, "Mark read", {}, "gmail.archive")
    assert again.action.status == "done"
    category_events = [
        r["event"]
        for r in autonomy.audit_trail(category="email_mark_read")
        if r["action_id"] is None
    ]
    assert category_events == ["granted_tier2", "escalated", "resumed"]


# ----- failures ------------------------------------------------------------------


async def test_a_failed_execution_stays_retryable(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    recorder.failures_left = 1
    staged = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive", {}, "gmail.archive"
    )
    failed = await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.erin)
    assert failed.action.status == "failed" and failed.action.last_error == "ConnectionError"
    assert "try again" in failed.message
    assert [a.id for a in autonomy.open_for(family.erin)] == [staged.action.id]
    retried = await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.erin)
    assert retried.action.status == "done" and retried.action.attempts == 2
    assert events(autonomy, staged.action.id) == [
        "staged",
        "approved",
        "execution_failed",
        "approved",
        "executed",
    ]


async def test_an_automatic_action_that_fails_is_left_open(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    recorder.failures_left = 1
    autonomy.grant_tier2("email_archive_noise", via_rule_id=1, by=family.erin)
    outcome = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive", {}, "gmail.archive"
    )
    assert outcome.action.status == "failed"
    assert autonomy.open_for(family.erin)[0].id == outcome.action.id


async def test_unknown_executors_and_categories_are_refused(
    autonomy: Autonomy, family: SeededFamily
) -> None:
    with pytest.raises(AutonomyError):
        await autonomy.stage("email_archive_noise", family.erin, "x", {}, "no.such.executor")
    with pytest.raises(NotFound):
        await autonomy.stage("teleport", family.erin, "x", {}, "gmail.archive")


# ----- who may answer ------------------------------------------------------------


async def test_personal_actions_belong_to_their_owner(
    autonomy: Autonomy, family: SeededFamily
) -> None:
    staged = await autonomy.stage(
        "email_archive_noise", family.erin, "Archive", {}, "gmail.archive"
    )
    with pytest.raises(PermissionDenied):
        await autonomy.resolve(staged.action.id, Decision.APPROVE, by=family.husband)
    his = await autonomy.stage(
        "email_archive_noise", family.husband, "Archive", {}, "gmail.archive"
    )
    with pytest.raises(PermissionDenied):  # even an admin can't answer for his inbox
        await autonomy.resolve(his.action.id, Decision.APPROVE, by=family.erin)
    assert autonomy.open_for(family.erin)[0].id == staged.action.id
    assert [a.id for a in autonomy.open_for(family.husband)] == [his.action.id]


async def test_household_actions_can_be_answered_by_an_admin(
    autonomy: Autonomy, family: SeededFamily
) -> None:
    his = await autonomy.stage("grocery_list_add", family.husband, "Add eggs", {}, "groceries.add")
    assert his.action.id in [a.id for a in autonomy.open_for(family.erin)]  # admin sees it
    done = await autonomy.resolve(his.action.id, Decision.APPROVE, by=family.erin)
    assert done.action.status == "done"
    hers = await autonomy.stage("grocery_list_add", family.erin, "Add rice", {}, "groceries.add")
    assert hers.action.id not in [a.id for a in autonomy.open_for(family.husband)]
    with pytest.raises(PermissionDenied):
        await autonomy.resolve(hers.action.id, Decision.APPROVE, by=family.husband)


# ----- the audit log ---------------------------------------------------------------


async def test_the_audit_log_is_append_only(autonomy: Autonomy, family: SeededFamily) -> None:
    await autonomy.stage("email_archive_noise", family.erin, "Archive", {}, "gmail.archive")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        family.db.execute("UPDATE action_audit SET event = 'forged'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        family.db.execute("DELETE FROM action_audit")


# ----- asked for in the person's own words --------------------------------------


async def test_an_asked_for_action_counts_as_the_yes(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    outcome = await autonomy.stage(
        "grocery_list_add", family.erin, "White miso", {}, "groceries.add", requested=True
    )
    assert outcome.action.status == "done" and len(recorder.calls) == 1
    assert "requested" in events(autonomy, outcome.action.id)
    assert autonomy.category("grocery_list_add").tier is Tier.SUPERVISED  # nothing granted


async def test_capped_or_escalated_categories_ask_even_when_asked_for(
    autonomy: Autonomy, family: SeededFamily, recorder: Recorder
) -> None:
    capped = await autonomy.stage(
        "vendor_call", family.erin, "Call the plumber", {}, "gmail.archive", requested=True
    )
    assert capped.action.status == "pending"
    autonomy.escalate("grocery_list_add", "odd pattern of adds")
    escalated = await autonomy.stage(
        "grocery_list_add", family.erin, "White miso", {}, "groceries.add", requested=True
    )
    assert escalated.action.status == "pending" and recorder.calls == []
