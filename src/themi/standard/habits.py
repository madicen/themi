"""The habit reserve: small daily check-ins, offered rarely and dropped quietly.

Each member has a few ideas held in reserve. One is offered (through the
`habit_trial` category, so it waits for their yes) only when:

- nothing was offered to them in the last 14 days and no offer is open, and
- their recent prompts are mostly acted on (enough of them to tell), so a new
  one is likely welcome rather than one more thing to ignore.

An accepted habit sends one low-priority message a day, at a strong window.
If it's ignored several days in a row it's retired without comment; a
declined or lapsed offer is never made again.

In burnout mode (F22d) a check-in is held with everything else, unless they keep it
(`burnout` 'keep', in its burnout words if they gave some) or it's one of theirs that comes
only then ('only': extra water, grounding, rest). Those still come, and ignoring them then
never retires them.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.services import Services
from themi.energy.outcomes import OutcomeTracker
from themi.localtime import member_day, to_utc_iso
from themi.modules import Module, ModuleContext

log = logging.getLogger(__name__)

OFFER_EVERY = timedelta(days=14)
MIN_RECENT_OUTCOMES = 5
MIN_ACTED_RATE = 0.7
RETIRE_AFTER_IGNORED = 3
CATEGORY = "habit_trial"
# The daily message itself (not the offer) is labelled, as Erin asked in rules 7 and 8.
CHECK_IN_TEXT = "Check-in: {prompt}"
SELF_CARE_KIND = "selfcare"  # a check-in burnout mode keeps (F22d): not held by its pause
EXECUTOR = "habits.activate"
# Michael read the old "A small daily check-in to try: ..." as Erin's check-in sent to him:
# each member has their own reserve, so the offer says it's theirs.
OFFER_TEXT = "Something you could try for yourself: {idea}"

# (idea, the daily message). Worded as offers, never as instructions.
IDEAS: tuple[tuple[str, str], ...] = (
    (
        "a glass of water mid-morning",
        "A glass of water might feel good about now, if you fancy one.",
    ),
    (
        "a two-minute stretch in the afternoon",
        "Stretch break, if it'd feel nice? Two minutes is plenty.",
    ),
    ("a few minutes outside", "A few minutes of fresh air could be nice today, whenever it fits."),
    (
        "a five-minute reset of one small space",
        "Five-minute reset of one little spot, or skip it today? Either is fine.",
    ),
)


class HabitReserve:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db

    @property
    def outcomes(self) -> OutcomeTracker:
        assert self.services.outcomes is not None
        return self.services.outcomes

    def install(self) -> None:
        self.services.provide(keys.habits, self)
        self.services.autonomy.executors.register(EXECUTOR)(self._activate)

    def _today(self, member: Member | None = None) -> date:
        family = self.store.get_family()
        tz = ZoneInfo(family.timezone if family else "UTC")
        return member_day(member, clock.now(), tz) if member else clock.now().astimezone(tz).date()

    # ----- the reserve --------------------------------------------------------

    def seed(self, member: Member) -> None:
        self.db.executemany(
            "INSERT OR IGNORE INTO habits (member_id, idea, prompt) VALUES (?, ?, ?)",
            [(member.id, idea, prompt) for idea, prompt in IDEAS],
        )

    def habits(self, member: Member) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM habits WHERE member_id = ? ORDER BY id", (member.id,))

    def _sync_offers(self) -> None:
        """Offers that were declined or lapsed are settled as declined."""
        for row in self.db.query(
            "SELECT h.id FROM habits h JOIN pending_actions a ON a.id = h.action_id "
            "WHERE h.status = 'offered' AND a.status IN ('declined', 'expired')"
        ):
            self.db.execute("UPDATE habits SET status = 'declined' WHERE id = ?", (row["id"],))

    def ready_for_offer(self, member: Member) -> bool:
        if self.db.one(
            "SELECT 1 FROM habits WHERE member_id = ? AND status = 'offered'", (member.id,)
        ):
            return False
        last = self.db.scalar(
            "SELECT MAX(offered_at) FROM habits WHERE member_id = ?", (member.id,)
        )
        if last is not None and datetime.fromisoformat(last) > clock.now() - OFFER_EVERY:
            return False
        recent = self.outcomes.recent(member.id)
        if len(recent) < MIN_RECENT_OUTCOMES:
            return False
        return recent.count("acted") / len(recent) >= MIN_ACTED_RATE

    async def offer_due(self) -> int:
        """Scheduler job: offer one habit to each member it would suit. Returns offers made."""
        self._sync_offers()
        offered = 0
        for member in self.store.list_members():
            self.seed(member)
            if not self.ready_for_offer(member):
                continue
            habit = self.db.one(  # an idea someone else has taken up comes after the rest
                "SELECT * FROM habits h WHERE member_id = ? AND status = 'reserve' "
                "ORDER BY EXISTS (SELECT 1 FROM habits o WHERE o.idea = h.idea "
                "AND o.member_id != h.member_id AND o.status = 'active'), id LIMIT 1",
                (member.id,),
            )
            if habit is None:
                continue
            outcome = await self.services.autonomy.stage(
                CATEGORY,
                member,
                OFFER_TEXT.format(idea=habit["idea"]),
                {"habit": habit["id"]},
                EXECUTOR,
            )
            self.db.execute(
                "UPDATE habits SET status = 'offered', action_id = ?, offered_at = ? WHERE id = ?",
                (outcome.action.id, to_utc_iso(clock.now()), habit["id"]),
            )
            log.info("Offered habit %s to member %s", habit["id"], member.id)
            offered += 1
        return offered

    async def _activate(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        habit_id = int(payload["habit"])
        self.db.update(
            "UPDATE habits SET status = 'active', ignored_streak = 0 WHERE id = ? "
            "AND status IN ('offered', 'reserve')",
            (habit_id,),
        )
        idea = self.db.scalar("SELECT idea FROM habits WHERE id = ?", (habit_id,))
        return f"Trying it: {idea}. It'll drop away on its own if it isn't helping."

    # ----- active habits ------------------------------------------------------

    async def send_due(self) -> int:
        """Scheduler job: today's check-in for each active habit. Returns how many were queued."""
        sent = 0
        burnout = self.services.maybe(keys.burnout)
        for habit in self.db.query("SELECT * FROM habits WHERE status = 'active'"):
            member = self.store.get_member(habit["member_id"])
            today = self._today(member).isoformat()  # F34j: their own day
            if habit["last_sent_on"] == today:
                continue
            resting = burnout is not None and burnout.current(member) is not None
            if habit["burnout"] == ("held" if resting else "only"):
                continue  # held in burnout mode, or one that comes only then
            if habit["last_outbox_id"] is not None and not self._settle_last(habit, resting):
                continue
            if habit["status"] == "retired":
                continue
            words = (resting and habit["burnout_prompt"]) or _check_in_words(habit, member)
            result = await self.services.outbox.send(
                member,
                CHECK_IN_TEXT.format(prompt=words),
                priority=Priority.LOW,
                kind=SELF_CARE_KIND if resting else "habit",
            )
            self.db.execute(
                "UPDATE habits SET last_sent_on = ?, last_outbox_id = ?, check_ins = check_ins + 1 "
                "WHERE id = ?",
                (today, result.outbox_id, habit["id"]),
            )
            sent += 1
        return sent

    def _settle_last(self, habit: dict[str, Any], resting: bool = False) -> bool:
        """Count how yesterday's check-in went. False if there's nothing new to send. In
        burnout mode (`resting`) an ignored one isn't held against it."""
        outcome = self.outcomes.outcome_of(habit["last_outbox_id"])
        if outcome is None:
            return False  # still waiting to go out, or still open: one at a time
        if resting:
            return True
        streak = habit["ignored_streak"] + 1 if outcome == "ignored" else 0
        if streak >= RETIRE_AFTER_IGNORED:
            self.db.execute(
                "UPDATE habits SET status = 'retired', ignored_streak = ? WHERE id = ?",
                (streak, habit["id"]),
            )
            log.info("Retired habit %s after %d ignored check-ins", habit["id"], streak)
            habit["status"] = "retired"
            return True
        self.db.execute("UPDATE habits SET ignored_streak = ? WHERE id = ?", (streak, habit["id"]))
        return True


def _check_in_words(habit: dict[str, Any], member: Member) -> str:
    """Plain phrasing says what it is ("A glass of water mid-morning."); gentle phrasing
    keeps the habit's own offer ("...might feel good about now, if you fancy one")."""
    if member.phrasing == "gentle":
        return str(habit["prompt"])
    idea = str(habit["idea"])
    return f"{idea[:1].upper()}{idea[1:]}."


class HabitsModule(Module):
    """The habit reserve: small habits offered when there is room."""

    name = "habits"

    def install(self, ctx: ModuleContext) -> None:
        habits = ctx.provide(HabitReserve(ctx.services))
        habits.install()
        ctx.periodic("habits.offer", timedelta(hours=6), habits.offer_due)
        ctx.periodic("habits.send", timedelta(hours=1), habits.send_due)
