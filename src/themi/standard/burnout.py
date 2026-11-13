"""Burnout mode (F22d, Erin's ideas #33, #122 and #123): everything held, no demands.

"Put me in burnout mode" (or /burnout): every task nudge, check-in, list, approval card
and household nudge waits (a "burnout" pause with no end; nothing is dropped). What they
ask for still comes, and so do replies, urgent alerts, their own reminders, meal nudges
and travel heads-ups. The first reply is a few words with nothing in it to do.

Time-sensitive things don't wait: a task of theirs due today or overdue that has a time,
or is marked important, goes to their partner for now. Its nudges say why (Michael,
2026-11-02: knowing she has nothing in the tank helps him get it done), in words, never
energy scores. An hourly check hands on the ones that become due later. When it ends, what
was handed on and is still open comes back to them.

Check-ins (F22d's second half): each one is held in burnout mode unless they keep it, in
burnout words of their own if they like, and they can add ones that come only then (extra
water, grounding, rest). `set_burnout_check_in` sets that; a new one still waits for their
yes, as any new check-in does (`habit_trial` is capped).

It lasts until they turn it off ("I'm out of burnout mode", /burnout off). Only they can
turn it on: a partner asking is told so (F22a's case).

While it's on, each turn's context says so: no suggestions or questions; asked for
something to do, `burnout_task` gives the single lightest thing; worry about what's held
gets validation first, that it's all handled, and only later that rest is what helps.

Defaults chosen 2026-11-02 while Erin's answers were pending: see BUILD_PROMPTS F22d.
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.channels.outbox import Priority
from themi.core import keys, partner
from themi.core.tools import SETTINGS, ToolContext, ToolDeclined, ToolFailed, tool
from themi.core.wording import words_in_common
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.standard.habits import CATEGORY as HABIT_CATEGORY
from themi.standard.habits import EXECUTOR as HABIT_EXECUTOR
from themi.standard.tasks import Task, TaskBoard

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

TOPIC = "burnout"
FOREVER = timedelta(days=3650)  # no end date: it lasts until they turn it off
# Erin (#123): "a brief 'burnout mode enabled, all your tasks are handled, go rest.' With no
# demands", "mix up the phrasing".
STARTED_TEXTS = (  # never a command: the PDA shield would reword "Go rest."
    "Burnout mode is on. Everything's handled; resting is all that's left.",
    "Burnout mode's on. Everything is held and looked after. Time to rest.",
    "It's on. Nothing needs you; it's all handled.",
    "Burnout mode is on. I've got everything. Rest is the only thing on today.",
)
ALREADY_TEXT = "Burnout mode is still on. Everything's handled."
ENDED_TEXT = "Burnout mode is off. Things will come back gently, a few at a time."
NOT_ON_TEXT = "Burnout mode isn't on."
LIGHTEST_TEXT = "If you'd like one thing: {title}. Nothing at all is fine too."
NOTHING_TEXT = "There's nothing that needs you. Resting is the thing."
HANDED_TEXT = "{name}'s running on empty, so this one's come to you for now."
KEEP_TEXT = {
    "keep": "In burnout mode, {idea} still comes{words}.",
    "only": "{idea} now comes only in burnout mode{words}.",
    "held": "In burnout mode, {idea} waits with everything else.",
}
ONLY_OFFER = "A check-in just for burnout mode: {idea}"
SIGNAL = (
    "they're in burnout mode: everything is held and handled. Keep replies short and free "
    "of demands: no suggestions, tasks, plans or questions. Asked for something to do: "
    "burnout_task (one thing, the lightest). Worried about what's held: in that message "
    "only validate the feeling and say it's all tracked and being handled; only in a later "
    "message, that resting is the most useful thing now; a grounding idea only if they ask "
    "for one, a single one, from what they've said worked before. One step per message. "
    "To end it, they say so (end_burnout)"
)


class Burnout:
    def __init__(self, services: Services, board: TaskBoard) -> None:
        self.services = services
        self.board = board
        self.db = services.store.db
        self.pauses = services.outbox.pauses

    def install(self) -> None:
        s = self.services
        s.provide(keys.burnout, self)
        self.board.details.append(self._why_yours)
        self.board.handed_on.append(lambda task: self._why_yours(task) is not None)
        s.add_command("/burnout", self.on_command, "Burnout mode: /burnout, /burnout off")
        for t in (start_burnout, end_burnout, burnout_task, set_burnout_check_in):
            s.tools.register(t)

    def current(self, member: Member) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM burnout WHERE member_id = ? AND ended_at IS NULL ORDER BY id DESC",
            (member.id,),
        )

    def signals(self, member: Member) -> list[str]:
        """The line for each turn's context while it's on."""
        return [SIGNAL] if self.current(member) is not None else []

    async def start(self, member: Member) -> str:
        if self.current(member) is not None:
            return ALREADY_TEXT
        if (
            self.services.maybe(keys.body_double) is not None
        ):  # BD1a: burnout mode wins over a session
            await self.services.get(keys.body_double).stop_for_other(member)
        now = clock.now()
        pause = self.pauses.pause(member, TOPIC, now + FOREVER)
        self.db.execute(
            "INSERT INTO burnout (member_id, pause_id, started_at) VALUES (?, ?, ?)",
            (member.id, pause.id, to_utc_iso(now)),
        )
        log.info("Burnout mode on for member %s", member.id)
        await self.hand_over()
        return random.choice(STARTED_TEXTS)

    async def end(self, member: Member) -> str:
        row = self.current(member)
        if row is None:
            return NOT_ON_TEXT
        self.db.execute(
            "UPDATE burnout SET ended_at = ? WHERE id = ?", (to_utc_iso(clock.now()), row["id"])
        )
        for handed in self.db.query(
            "SELECT * FROM burnout_handoffs WHERE burnout_id = ?", (row["id"],)
        ):
            task = self.board.get(handed["task_id"])
            if task.status in ("open", "snoozed") and task.assignee == handed["to_member"]:
                await self.board.reassign(task.id, member)
        if self.pauses.resume(member, TOPIC):
            self.services.outbox.release_held(member)  # flush re-checks quiet hours, limits
        log.info("Burnout mode off for member %s", member.id)
        return ENDED_TEXT

    async def hand_over(self) -> int:
        """Time-sensitive tasks of anyone in burnout mode go to their partner for now."""
        handed = 0
        members = self.services.store.list_members()
        for row in self.db.query("SELECT * FROM burnout WHERE ended_at IS NULL"):
            member = self.services.store.get_member(row["member_id"])
            other = next(
                (m for m in members if m.id != member.id and m.reachable),
                None,
            )
            if other is None or self.current(other) is not None:
                continue  # nobody to hand to: it waits with the rest
            for task in self.board.open_for(member):
                if task.assignee != member.id or not self._time_sensitive(task):
                    continue
                self.db.execute(
                    "INSERT INTO burnout_handoffs (burnout_id, task_id, from_member, "
                    "to_member, created_at) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], task.id, member.id, other.id, to_utc_iso(clock.now())),
                )
                await self.board.reassign(task.id, other)
                handed += 1
        return handed

    def _why_yours(self, task: Task) -> str | None:
        """On a handed-on task's nudge: whose it was, and why it's with them now."""
        row = self.db.one(
            "SELECT h.from_member FROM burnout_handoffs h JOIN burnout b ON b.id = h.burnout_id "
            "WHERE h.task_id = ? AND h.to_member = ? AND b.ended_at IS NULL",
            (task.id, task.assignee),
        )
        if row is None:
            return None
        return HANDED_TEXT.format(name=self.services.store.get_member(row["from_member"]).name)

    def _time_sensitive(self, task: Task) -> bool:
        """Due today or overdue, with a time or marked important. Never shared (the
        partner has those already)."""
        today = self.board._today()
        due = task.due_on is not None and task.due_on <= today
        return (
            due
            and not task.shared
            and (
                task.due_time is not None or task.from_time is not None or task.importance == "high"
            )
        )

    def lightest(self, member: Member) -> Task | None:
        """The single lowest-demand thing they have: least effort, then the soonest due."""
        tasks = [
            t
            for t in self.board.open_for(member)
            if t.status == "open" and not t.medicine and t.due_on is not None
        ]
        far = self.board._today() + timedelta(days=10_000)
        return min(tasks, key=lambda t: (t.effort, t.due_on or far, t.id), default=None)

    async def keep_check_in(self, member: Member, check_in: str, mode: str, words: str) -> str:
        """Set a check-in's place in burnout mode; a new burnout-only one is offered for a
        yes. Returns what to tell them."""
        rows = self.db.query(
            "SELECT * FROM habits WHERE member_id = ? AND status IN ('active', 'offered')",
            (member.id,),
        )
        scored = [(words_in_common(check_in, r["idea"]), r) for r in rows]
        best = max(scored, key=lambda s: s[0], default=(0, None))
        habit = best[1] if best[0] else None
        if habit is not None:
            self.db.execute(
                "UPDATE habits SET burnout = ?, burnout_prompt = ? WHERE id = ?",
                (mode, words or None, habit["id"]),
            )
            idea = str(habit["idea"])
            said = f' as "{words}"' if words and mode != "held" else ""
            text = KEEP_TEXT[mode].format(idea=f'"{idea}"', words=said)
            return text[:1].upper() + text[1:]
        if mode != "only":
            raise ToolFailed(
                f"They have no check-in like {check_in!r}. A new everyday check-in comes "
                "from the reserve, offered for a yes; here only a burnout-only one can be "
                "added (mode only)."
            )
        now = to_utc_iso(clock.now())
        same = self.db.one(  # an idea they had before (declined, retired) starts again
            "SELECT id FROM habits WHERE member_id = ? AND idea = ?", (member.id, check_in)
        )
        if same is not None:
            habit_id = int(same["id"])
            self.db.execute(
                "UPDATE habits SET prompt = ?, status = 'offered', burnout = 'only', "
                "burnout_prompt = ?, offered_at = ?, ignored_streak = 0 WHERE id = ?",
                (words or check_in, words or None, now, habit_id),
            )
        else:
            habit_id = self.db.execute(
                "INSERT INTO habits (member_id, idea, prompt, status, burnout, "
                "burnout_prompt, offered_at) VALUES (?, ?, ?, 'offered', 'only', ?, ?)",
                (member.id, check_in, words or check_in, words or None, now),
            )
        outcome = await self.services.autonomy.stage(
            HABIT_CATEGORY,
            member,
            ONLY_OFFER.format(idea=check_in),
            {"habit": habit_id},
            HABIT_EXECUTOR,
        )
        self.db.execute(
            "UPDATE habits SET action_id = ? WHERE id = ?", (outcome.action.id, habit_id)
        )
        return ""  # the card is the answer

    async def on_command(self, member: Member, argument: str) -> None:
        if argument.strip().lower() in ("off", "end", "stop"):
            text = await self.end(member)
        else:
            text = await self.start(member)
        await self.services.outbox.send(member, text, priority=Priority.REPLY)


def _burnout(ctx: ToolContext) -> Burnout:
    burnout = ctx.services.maybe(keys.burnout)
    if burnout is None:
        raise ToolFailed("Burnout mode isn't set up.")
    return burnout


@tool(
    "start_burnout",
    "Turn on burnout mode when they ask for it, or say they're burnt out and want "
    "everything held ('put me in burnout mode'): every task nudge and check-in is held "
    "with no end date, time-sensitive tasks go to their partner, and they get a short "
    "message with nothing to do. Only for the person speaking: someone can't turn it on "
    "for their partner. It's sent as it is: add nothing.",
    {},
)
async def start_burnout(ctx: ToolContext, args: dict[str, Any]) -> str:
    members = ctx.services.store.list_members()
    if partner.about_partner(ctx.request_text, ctx.member, members):
        other = partner.named(ctx.request_text, ctx.member, members)
        name = other.name if other is not None else "they"
        raise ToolFailed(
            f"Not turned on: only {name} can put themselves in burnout mode. Say so kindly, "
            f"and that {name} can say 'burnout mode' to Themi any time; offer to take some "
            "of their things on meanwhile (update_task assign_to: me, for a one-off)."
        )
    text = await _burnout(ctx).start(ctx.member)
    ctx.replies.append(text)  # the reply, word for word: no demands added after it
    return f"Done; they're told, word for word: {text!r}. Add nothing."


@tool(
    "end_burnout",
    "Turn burnout mode off when they say they're ready ('I'm out of burnout mode', "
    "'turn burnout mode off'). Held things come back gently.",
    {},
)
async def end_burnout(ctx: ToolContext, args: dict[str, Any]) -> str:
    text = await _burnout(ctx).end(ctx.member)
    if text == NOT_ON_TEXT:
        raise ToolDeclined(text)
    ctx.replies.append(text)
    return text


@tool(
    "burnout_task",
    "In burnout mode, when they ask for something to do ('give me one thing', 'what "
    "could I do?'): the single lightest thing they have, with no push. Never offered "
    "unasked.",
    {},
)
async def burnout_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    burnout = _burnout(ctx)
    if burnout.current(ctx.member) is None:
        raise ToolFailed("Burnout mode isn't on: use day_summary or focus_now instead.")
    if any(name != "burnout_task" for name, _, _ in ctx.calls):
        raise ToolDeclined(  # F42b (bug #204): they told Themi something; that's the answer
            "They told you something this turn, so answer that, and don't offer a task. "
            "This is only for when they ask for something to do."
        )
    task = burnout.lightest(ctx.member)
    text = LIGHTEST_TEXT.format(title=task.title) if task is not None else NOTHING_TEXT
    ctx.replies.append(text)
    return f"They're told, word for word: {text!r}. Add nothing."


@tool(
    "set_burnout_check_in",
    "Which check-ins still come in burnout mode ('keep the water check-in when I'm burnt "
    "out', 'in burnout mode say 'water?' instead'), or a new one that comes only then "
    "('a grounding check-in just for burnout mode'). check_in: the check-in in their words. "
    "mode: keep (it still comes), only (only in burnout mode), held (waits with the rest, "
    "as by default). words: how it's said in burnout mode, in their words, or empty.",
    {
        "check_in": {"type": "string"},
        "mode": {"type": "string", "enum": ["keep", "only", "held"]},
        "words": {"type": "string"},
    },
)
async def set_burnout_check_in(ctx: ToolContext, args: dict[str, Any]) -> str:
    check_in = str(args["check_in"]).strip()
    if not check_in:
        raise ToolFailed("Which check-in? Ask them.")
    text = await _burnout(ctx).keep_check_in(
        ctx.member, check_in, str(args["mode"]), str(args["words"]).strip()
    )
    if not text:
        ctx.answered.append("set_burnout_check_in")
        return "A card asks them for a yes; it starts once they say it. Add nothing."
    ctx.replies.append(text)
    return text


class BurnoutModule(Module):
    """Burnout: handing tasks over when someone's running low."""

    name = "burnout"
    title = "Burnout watch"
    summary = "Notices when someone is running low and offers to hand their tasks over."
    tool_groups = (SETTINGS,)
    requires = ("tasks",)

    def install(self, ctx: ModuleContext) -> None:
        burnout = ctx.provide(Burnout(ctx.services, ctx.get(TaskBoard)))
        burnout.install()
        ctx.periodic("burnout.hand_over", timedelta(hours=1), burnout.hand_over)
