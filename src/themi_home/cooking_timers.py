"""Step timers while cooking (RC3c).

A step with a time ("cook for 10 minutes", "about 2 to 3 minutes") gets [Timer 10 min]; a
range offers its low end and says the range ("Timer 2 min (2-3)"). "Overnight" and times of
8 hours or more offer a reminder instead. Up to two per step.

Each timer is a row and a scheduler job on `themi.clock`, so a restart doesn't lose it, and
several can run at once. When one ends: "Time's up: 10 min for step 3 of Pad Thai." as an
urgent message, even in quiet hours, because they asked for it. "How long left?", "cancel
the timer" and "add 2 minutes" work typed; ending the session with timers running asks
whether to keep them.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.localtime import next_waking_start, to_utc_iso
from themi.modules import Module, ModuleContext
from themi_home.groups import COOKING

if TYPE_CHECKING:
    from themi.scheduler import Scheduler
    from themi_home.cooking import Cooking, Part, Session
    from themi_home.recipes import Recipe

log = logging.getLogger(__name__)

JOB = "cooking.timer"
KIND = "cooking_timer"
LONG = 8 * 60  # minutes: past this, a reminder instead of a timer
PER_STEP = 2
LABEL = 40  # characters of a timer's own label (CK3)
PRESETS = (1, 3, 5, 10, 15, 30)  # CK3: [+ Timer]'s minutes
DASHES = "-\u2013\u2014"  # hyphen, en and em dash
UNIT = r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)"
DURATION = re.compile(
    rf"\b(?P<low>\d+(?:\.\d+)?)(?:\s*(?:[{DASHES}]|to)\s*(?P<high>\d+(?:\.\d+)?))?\s*{UNIT}\b",
    re.IGNORECASE,
)
OVERNIGHT = re.compile(r"\bovernight\b", re.IGNORECASE)
LEFT = re.compile(r"^(?:how (?:long|much time) (?:is )?left|how long (?:to go|now)|time left)$")
CANCEL = re.compile(r"^(?:cancel|stop) (?:the |my |all )?(?:timers?)$")
ADD = re.compile(
    r"^(?:add|another|plus) (\d+) (?:more )?(?:minutes?|mins?)(?: to (?:the )?timer)?$"
)


@dataclass(frozen=True)
class Found:
    minutes: float  # what the timer is set for
    said: str  # how the button says it: "10 min", "2 min (2-3)"
    reminder: bool = False


def _minutes(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("s"):
        return value / 60
    if unit.startswith("h"):
        return value * 60
    return value


def _short(minutes: float) -> str:
    if minutes < 1:
        return f"{round(minutes * 60)} sec"
    if minutes >= 60 and minutes % 60 == 0:
        hours = int(minutes // 60)
        return f"{hours} hr" if hours == 1 else f"{hours} hrs"
    if minutes >= 60:
        return f"{int(minutes // 60)} hr {int(minutes % 60)} min"
    return f"{minutes:g} min"


def durations(text: str) -> list[Found]:
    """The times a step names, as timers or (for overnight and long ones) reminders."""
    found: list[Found] = []
    if OVERNIGHT.search(text):
        found.append(Found(0, "overnight", reminder=True))
    for match in DURATION.finditer(text):
        unit = match.group("unit")
        low = _minutes(float(match.group("low")), unit)
        high = _minutes(float(match.group("high")), unit) if match.group("high") else None
        if (high or low) >= LONG:
            found.append(Found(high or low, _short(high or low), reminder=True))
            continue
        said = _short(low)
        if high is not None:
            said += f" ({match.group('low')}-{match.group('high')})"
        found.append(Found(low, said))
    seen: set[str] = set()
    unique = []
    for item in found:
        if item.said not in seen:
            seen.add(item.said)
            unique.append(item)
    return unique[:PER_STEP]


def step_durations(db: Any, recipe: Recipe, part: Any) -> list[Found]:
    """A step's times with the recipe's timer fixes from cooking notes made (CF7)."""
    from themi_home.cooking_notes import timer_fixed

    return timer_fixed(db, recipe, part.label, durations(part.text))


def default_label(recipe: Recipe, step: str) -> str:
    """ "Sauce, step 3" where the recipe groups its steps, else "Step 3"."""
    from themi_home.cooking import step_parts

    group = next((p.group for p in step_parts(recipe) if p.label == step), "")
    return f"{group}, step {step}" if group else f"Step {step}"


class CookingTimers:
    def __init__(self, cooking: Cooking, jobs: Scheduler) -> None:
        self.cooking = cooking
        self.services = cooking.services
        self.db = cooking.db
        self.jobs = jobs

    def install(self) -> None:
        self.jobs.handler(JOB)(self.run_job)
        self.cooking.timers = self
        self.services.button_handlers["cooking_timer"] = self.on_button
        self.services.text_handlers.append(self.on_text)

    # ----- buttons on a step ----------------------------------------------------------------

    def buttons(self, session: Session, part: Part) -> list[Button]:
        out = []
        recipe = self.cooking.recipes.get(session.recipe_id)
        found_times = step_durations(self.db, recipe, part) if recipe else durations(part.text)
        for found in found_times:
            payload: dict[str, Any] = {
                "session": session.id, "step": part.label, "minutes": found.minutes,
            }  # fmt: skip
            if found.reminder:
                label = (
                    "Remind me tomorrow"
                    if found.said == "overnight"
                    else f"Remind me in {found.said}"
                )
                out.append(Button(label, "cooking_timer", {**payload, "action": "remind"}))
            else:
                out.append(
                    Button(f"Timer {found.said}", "cooking_timer", {**payload, "action": "start"})
                )
        return out

    # ----- running ------------------------------------------------------------------------

    def running(self, member: Member) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM cooking_timers WHERE member_id = ? AND fired_at IS NULL "
            "AND cancelled_at IS NULL ORDER BY ends_at",
            (member.id,),
        )

    def start(
        self,
        member: Member,
        session: Session,
        recipe: Recipe,
        step: str,
        minutes: float,
        label: str | None = None,
    ) -> datetime:
        """A timer for `step`; its label is theirs (CK3) or the step's ("Sauce, step 3").
        Returns when it ends."""
        return self.begin(member, session, recipe, step, minutes, label)[1]

    def begin(
        self,
        member: Member,
        session: Session,
        recipe: Recipe,
        step: str,
        minutes: float,
        label: str | None = None,
    ) -> tuple[int, datetime]:
        """`start`, returning the new timer's id too (F59h: the oven's timer is tied to it)."""
        now = clock.now()
        ends = now + timedelta(minutes=minutes)
        label = " ".join((label or "").split())[:LABEL] or default_label(recipe, step)
        timer_id = self.db.execute(
            "INSERT INTO cooking_timers (session_id, member_id, recipe, step, minutes, ends_at, "
            "in_group, created_at, label) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session.id, member.id, recipe.name, step, minutes, to_utc_iso(ends),
             int(session.in_group), to_utc_iso(now), label),
        )  # fmt: skip
        self.jobs.enqueue(JOB, {"timer": timer_id}, run_after=ends)
        return int(timer_id), ends

    # ----- one timer, from the cook screen (CK3) -------------------------------------------

    def _one(self, member_id: int, timer_id: int) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM cooking_timers WHERE id = ? AND member_id = ? AND cancelled_at IS NULL",
            (timer_id, member_id),
        )

    def add(self, member_id: int, timer_id: int, minutes: int) -> datetime | None:
        """More time on a running timer, as a typed "add 2 minutes": the job already queued
        sees the later end and queues itself again."""
        row = self._one(member_id, timer_id)
        if row is None or row["fired_at"] is not None or not 0 < minutes <= 60:
            return None
        ends = datetime.fromisoformat(row["ends_at"]) + timedelta(minutes=minutes)
        self.db.execute(
            "UPDATE cooking_timers SET ends_at = ?, minutes = minutes + ? WHERE id = ?",
            (to_utc_iso(ends), minutes, row["id"]),
        )
        return ends

    def cancel(self, member_id: int, timer_id: int) -> bool:
        """One running timer off, as a typed "cancel the timer" (whose job finds it gone)."""
        return bool(
            self.db.update(
                "UPDATE cooking_timers SET cancelled_at = ? WHERE id = ? AND member_id = ? "
                "AND fired_at IS NULL AND cancelled_at IS NULL",
                (to_utc_iso(clock.now()), timer_id, member_id),
            )
        )

    async def changed(self) -> bool:
        """F45f (bug #215): the oven's timer follows a cancel or more time now. True when
        the oven's timer changed with it."""
        oven = self.services.maybe(keys.oven)
        if oven is None:
            return False
        try:
            return bool(await oven.follow_timers())
        except Exception:
            log.exception("The oven's timer didn't follow the cook screen's")
            return False

    def clear(self, member_id: int, timer_id: int) -> bool:
        """A fired timer tapped on the screen: the chime and the pulse stop."""
        return bool(
            self.db.update(
                "UPDATE cooking_timers SET cleared_at = ? WHERE id = ? AND member_id = ? "
                "AND fired_at IS NOT NULL AND cleared_at IS NULL",
                (to_utc_iso(clock.now()), timer_id, member_id),
            )
        )

    def shown(self, now: datetime, fired_shown: timedelta) -> list[dict[str, Any]]:
        """WA3: everyone's timers as the wall shows them: running, or gone off within
        `fired_shown` and not tapped (as the cook screen keeps them), soonest first."""
        return self.db.query(
            "SELECT * FROM cooking_timers WHERE cancelled_at IS NULL AND cleared_at IS NULL "
            "AND (fired_at IS NULL OR fired_at > ?) ORDER BY ends_at, id",
            (to_utc_iso(now - fired_shown),),
        )

    async def run_job(self, payload: dict[str, Any]) -> None:
        row = self.db.one(
            "SELECT * FROM cooking_timers WHERE id = ? AND fired_at IS NULL "
            "AND cancelled_at IS NULL",
            (int(payload.get("timer", 0)),),
        )
        if row is None:
            return  # cancelled, or moved (a new job carries it)
        ends = datetime.fromisoformat(row["ends_at"])
        if ends > clock.now() + timedelta(seconds=1):  # "add 2 minutes" moved it later
            self.jobs.enqueue(JOB, {"timer": row["id"]}, run_after=ends)
            return
        self.db.execute(
            "UPDATE cooking_timers SET fired_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), row["id"]),
        )
        member = self.services.store.get_member(row["member_id"])
        session = self.cooking.get(row["session_id"]) if row["session_id"] else None
        front = self.cooking.current(member)
        go = (  # F64e: its recipe is set aside behind another: a tap brings it forward
            [Button(f"Go to {row['recipe']}"[:40], "cooking",
                    {"session": session.id, "action": "front"})]
            if session is not None and session.ended_at is None and front is not None
            and front.id != session.id else []
        )  # fmt: skip
        await self.services.outbox.send(
            member,
            f"Time's up: {_short(row['minutes'])} for step {row['step']} of {row['recipe']}.",
            priority=Priority.URGENT,  # they set it: it rings in quiet hours too
            kind=KIND,  # to their own chat: a group message waits for everyone to be free
            buttons=go,
        )
        await self.cooking.timer_line(row["session_id"], row["label"] or f"step {row['step']}")

    def cancel_all(self, member: Member) -> int:
        return self.db.update(
            "UPDATE cooking_timers SET cancelled_at = ? WHERE member_id = ? AND fired_at IS NULL "
            "AND cancelled_at IS NULL",
            (to_utc_iso(clock.now()), member.id),
        )

    def left_text(self, member: Member) -> str:
        timers = self.running(member)
        if not timers:
            return "No timers running."
        now = clock.now()
        parts = []
        several = len({row["session_id"] for row in timers}) > 1  # F64e: say whose
        for row in timers:
            seconds = max(0, (datetime.fromisoformat(row["ends_at"]) - now).total_seconds())
            left = f"{math.ceil(seconds / 60)} min" if seconds >= 60 else f"{int(seconds)} sec"
            whose = f" of {row['recipe']}" if several else ""
            parts.append(f"{left} left on step {row['step']}{whose}")
        return "; ".join(parts).capitalize() + "."

    # ----- taps and typing ------------------------------------------------------------------

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        member = self.services.store.get_member(event.member.id)
        action = payload.get("action")
        if action in ("keep", "cancel"):
            if action == "cancel" and payload.get("session"):  # F64e: that recipe's only
                self.db.execute(
                    "UPDATE cooking_timers SET cancelled_at = ? WHERE member_id = ? AND "
                    "session_id = ? AND fired_at IS NULL AND cancelled_at IS NULL",
                    (to_utc_iso(clock.now()), member.id, int(payload["session"])),
                )
                await self.changed()
            elif action == "cancel":
                self.cancel_all(member)
                await self.changed()
            self.cooking.answer_timers(member, kept=action == "keep")  # CK3: the screen too
            text = "Timers cancelled." if action == "cancel" else "The timers keep running."
            if event.button.message_id is not None:
                await self.services.outbox.edit(member, event.button.message_id, text)
            return
        session = self.cooking.get(int(payload.get("session", 0)))
        if session is None or (session.member_id != member.id and not session.in_group):
            return
        recipe = self.cooking.recipes.get(session.recipe_id)
        assert recipe is not None
        minutes = float(payload.get("minutes", 0))
        step = str(payload.get("step", ""))
        owner = self.services.store.get_member(session.member_id)
        if action == "remind":
            when = (
                next_waking_start(owner, clock.now(), self._tz())
                if minutes == 0
                else clock.now() + timedelta(minutes=minutes)
            )
            await self.services.outbox.send(
                owner, f"{recipe.name}: step {step} has had its time.", priority=Priority.NORMAL,
                kind=KIND, not_before=when, deadline=when + timedelta(minutes=30),
            )  # fmt: skip
            said = f"I'll say when step {step}'s time is up."
        else:
            ends = self.start(owner, session, recipe, step, minutes)
            said = f"Timer set: {_short(minutes)} for step {step}, done at {self._clock(ends)}."
        await self.services.outbox.send(owner, said, priority=Priority.REPLY, kind=KIND)
        if event.button.message_id is not None:  # a keyboard takes one tap: fresh buttons
            session.message_id = event.button.message_id
            await self.cooking.show(session)

    async def on_text(self, event: InboundEvent, member: Member, text: str) -> bool:
        said = " ".join(text.lower().strip().rstrip("!?. ").split())
        if not self.running(member):
            return False
        if LEFT.match(said):
            reply = self.left_text(member)
        elif CANCEL.match(said):
            count = self.cancel_all(member)
            reply = "Timer cancelled." if count == 1 else f"{count} timers cancelled."
            if await self.changed():
                reply = reply.removesuffix(".") + ", and the oven's too."
        elif found := ADD.match(said):
            row = self.running(member)[-1]
            ends = self.add(member.id, row["id"], int(found.group(1))) or clock.now()
            reply = (
                f"Added {found.group(1)} min: step {row['step']} is done at {self._clock(ends)}."
            )
        else:
            return False
        session = self.cooking.current(member) if event.from_page else None
        if session is not None:  # CK13: said on the cook screen, answered there
            await self.cooking.say(session, reply)
            return True
        await self.services.outbox.send(member, reply, priority=Priority.REPLY, kind=KIND)
        return True

    async def ask_on_end(self, member: Member, session_id: int | None = None) -> None:
        """A session ended with timers still running: keep them or not. F64e: with other
        recipes still on the go, only the ended one's timers are asked about."""
        mine = session_id is not None and bool(self.cooking.open_sessions(member))
        rows = [r for r in self.running(member) if not mine or r["session_id"] == session_id]
        if not rows:
            return
        only = {"session": session_id} if mine else {}
        await self.services.outbox.send(
            member,
            "There's a timer still running. Keep it going?",
            priority=Priority.REPLY,
            kind=KIND,
            buttons=[
                Button("Keep timers", "cooking_timer", {"action": "keep", **only}),
                Button("Cancel them", "cooking_timer", {"action": "cancel", **only}),
            ],
        )

    def _tz(self) -> str:
        family = self.services.store.get_family()
        return family.timezone if family else "UTC"

    def _clock(self, moment: datetime) -> str:
        from themi.localtime import to_local

        local = to_local(moment, self._tz())
        hour = local.hour % 12 or 12
        return f"{hour}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"


class CookingTimersModule(Module):
    """RC3c: a step's timers, as scheduler jobs."""

    name = "cooking_timers"
    title = "Cooking timers"
    group = COOKING
    summary = "Sets the timers a recipe's steps call for."
    requires = ("cooking",)

    def install(self, ctx: ModuleContext) -> None:
        from themi_home.cooking import Cooking  # at install: at the top it would be an import cycle

        ctx.provide(CookingTimers(ctx.get(Cooking), ctx.scheduler)).install()
