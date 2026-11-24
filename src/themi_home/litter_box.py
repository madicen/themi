"""The litter box's chores (CG1b): when the CatGenie needs a person, someone hears about it.

From the litter box's events (CatGenie, `themi_home.connectors.catgenie`), as the feeders' (32):

- An error (on the box, or in an alert the app was sent), or sani-solution running low or
  out, makes one effort-1 hands-on task, for whoever has the most room right now
  (`Matcher.roomiest`). It goes on the wall's lists like any chore: it lasts until someone
  sees to it. Starting while that person's in quiet hours, it's for either of you instead.
- Its nudge waits 10 minutes, so a reading that bounces never sends one. An error, or no
  sani-solution, stops the box cleaning, so it's due at once (the daily limit doesn't hold
  it to morning; quiet hours, busy times and "/pause litter" still do). Running low and the
  granules can wait for the usual limits. Done / Later; Later asks again in an hour.
- Running low, then out: the same task, asked again with the new words.
- The box showing it's sorted (a new cartridge, the error gone, a clean after an alert)
  closes the task: done if the nudge had gone out, quietly taken off the list if not.
- Granules: the box can't say how many are left, so once the household sets a number on the
  Accounts page, a "top up the granules" chore comes every that many cleaning cycles. Marking
  it done (or taking it off the list) starts the count again.
- Energy: someone saying they've done one is a small chore's effort for them (a "device
  activity" signal, kept only when that input is on for them). The box sorting itself says
  nothing about who did it, so it doesn't count.

People see words, never codes. A problem marked done isn't raised again until the box stops
showing it.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.accounts import Device, Member
from themi.channels.outbox import Button, Priority
from themi.core import keys
from themi.core.services import Services
from themi.localtime import in_quiet_hours, to_local, to_utc_iso
from themi.core.prompts import OpenItem
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.standard.tasks import Task, TaskBoard, TaskChange, clock_words
from themi_home.connectors.catgenie import (
    ALERT,
    ERROR,
    GRANULES,
    OUT,
    SOLUTION,
    CatGenieWatcher,
    LitterBoxEvent,
    LitterBoxReading,
)
from themi_home.connectors.catgenie.events import CODES, error_words, named_words

log = logging.getLogger(__name__)

KIND = "litter_box"  # the outbox kind: "/pause litter" holds these
TITLES = {
    ERROR: "Check {the}",
    ALERT: "Check {the}",
    SOLUTION: "Change {the_s} sani-solution cartridge",
    GRANULES: "Top up {the_s} granules",
}
TEXTS = {
    ERROR: "{The} needs a look: {detail}. Check it when you can?",
    ALERT: "{The} sent an alert: {detail}. Check it when you can?",
}
LOW_TEXT = "{The} is running low on sani-solution{left}. Swap in a new cartridge when you can?"
OUT_TEXT = "{The} is out of sani-solution, so it can't wash. Swap in a new cartridge?"
GRANULES_TEXT = (
    "{The} has cleaned {used} times since its granules were last topped up. Top them up when "
    "you can?"
)
BROKEN_TEXT = (
    "CatGenie stopped answering for the litter box, so Themi can't see it for now: {why} It "
    "can be linked again on the website's Accounts page."
)
DONE, LATER = "Done", "Later"
WAIT = timedelta(minutes=10)  # a problem's first nudge waits this long
LATER_FOR = 60  # minutes: Later asks again in an hour
URGENT = (ERROR, ALERT)  # with OUT: it can't clean
EFFORT = -0.5  # a small chore, for the energy model
UNKNOWN_ASK = " What does the CatGenie app call it?"  # F60b: so a reply is expected
LEARNED_TEXT = "Got it: code {code} is {words}. I'll say that from now on."
ENDS_IN_A_KIND = re.compile(
    r"\b(?:issue|error|problem|fault|jam(?:med)?|block(?:ed|age)|fail(?:ure|ed)|warning)$"
)


class LitterBox:
    def __init__(self, services: Services, board: TaskBoard, watcher: CatGenieWatcher) -> None:
        self.services = services
        self.board = board
        self.watcher = watcher
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.provide(keys.litter_box, self)
        self.watcher.listeners.append(self.on_event)
        self.watcher.reading_listeners.append(self._counted)
        self.watcher.broken_listeners.append(self._broken)
        self.board.own_nudges.append(self._nudge)
        self.board.change_listeners.append(self._task_changed)
        self.board.done_hooks.append(self._done)
        self.board.display_notes.append(self._task_note)
        self.services.group_sources.append(self._unnamed_groups)  # F60b
        self.services.open_item_sources.append(self._unnamed_items)
        self.services.tools.register(name_litter_code)

    # ----- the box --------------------------------------------------------------------

    async def on_event(self, event: LitterBoxEvent) -> None:
        if event.gone:
            await self._gone(event)
            return
        live = self._live(event.device_id, event.kind)
        if live:
            await self._changed(live[-1], event)
            return
        device = self._device(event.device_id)
        if device is None:
            return
        assignment = self.board.matcher.roomiest("physical", 1, event.at)
        row_id = self.db.execute(
            "INSERT INTO litter_problems (device_id, problem, detail, status, opened_at) "
            "VALUES (?, ?, ?, 'open', ?)",
            (event.device_id, event.kind, event.detail, to_utc_iso(event.at)),
        )
        the = _the(device.name)
        task = await self.board.create(
            assignment.assignee,
            TITLES[event.kind].format(the=the, the_s=_possessive(the)),
            "physical",
            1,
            nudge=False,
            assignment=assignment,
        )
        self.db.execute("UPDATE litter_problems SET task_id = ? WHERE id = ?", (task.id, row_id))
        if in_quiet_hours(assignment.assignee, event.at, self._timezone()):
            await self.board.make_either(task.id)  # each asked as they wake; first one wins
        else:
            await self.board.prompt(task)  # now it's known as the box's: its own nudge

    async def _changed(self, row: dict[str, Any], event: LitterBoxEvent) -> None:
        """The same problem in new words. Running low, then out: asked again, if it's open."""
        if row["detail"] == event.detail:
            return
        self.db.execute(
            "UPDATE litter_problems SET detail = ? WHERE id = ?", (event.detail, row["id"])
        )
        task = self._task(row)
        if row["status"] == "open" and task is not None and event.detail == OUT:
            await self.board.prompt(task)

    async def _gone(self, event: LitterBoxEvent) -> None:
        now = to_utc_iso(event.at)
        for row in self._live(event.device_id, event.kind):
            self.db.execute("UPDATE litter_problems SET gone_at = ? WHERE id = ?", (now, row["id"]))
            if row["status"] != "open":
                continue
            # Closed before the task, so `_task_changed` doesn't take it for a person's word.
            self.db.execute(
                "UPDATE litter_problems SET status = 'cleared', closed_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            task = self._task(row)
            if task is None or task.assignee is None:
                continue
            member = self.store.get_member(task.assignee)
            if self._sent(task):
                await self.board.complete(task.id, member)
            else:
                await self.board.cancel(task.id, member)

    # ----- the granules -----------------------------------------------------------------

    def granules(self, device_id: int) -> tuple[int | None, int | None]:
        """(every how many cleans, cleans since the last top-up), when the box has said."""
        row = self.db.one("SELECT * FROM litter_granules WHERE device_id = ?", (device_id,))
        cycles = self.db.scalar(
            "SELECT cycles FROM litter_states WHERE device_id = ?", (device_id,)
        )
        if row is None or row["every"] is None:
            return None, None
        if cycles is None or row["since_cycles"] is None:
            return int(row["every"]), None
        return int(row["every"]), max(int(cycles) - int(row["since_cycles"]), 0)

    def set_granules(self, device_id: int, every: int | None) -> None:
        """Every how many cleans the granules want topping up; None turns it off. Turned on
        (or changed), the count starts now."""
        if every is not None and every <= 0:
            raise ValueError("the number of cleans must be more than none")
        cycles = self.db.scalar(
            "SELECT cycles FROM litter_states WHERE device_id = ?", (device_id,)
        )
        self.db.execute(
            "INSERT INTO litter_granules (device_id, every, since_cycles) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET every = excluded.every, "
            "since_cycles = excluded.since_cycles",
            (device_id, every, cycles),
        )

    async def _counted(self, device: Device, reading: LitterBoxReading) -> None:
        """Each read: the granules' chore once enough cleans have gone by."""
        row = self.db.one("SELECT * FROM litter_granules WHERE device_id = ?", (device.id,))
        if row is None or row["every"] is None or reading.cycles is None:
            return
        if row["since_cycles"] is None or reading.cycles < row["since_cycles"]:  # a reset box
            self.db.execute(
                "UPDATE litter_granules SET since_cycles = ? WHERE device_id = ?",
                (reading.cycles, device.id),
            )
            return
        used = reading.cycles - int(row["since_cycles"])
        if used < int(row["every"]) or self._live(device.id, GRANULES):
            return
        await self.on_event(LitterBoxEvent(device.id, GRANULES, str(used), clock.now()))

    # ----- the nudge ------------------------------------------------------------------

    async def _nudge(
        self, task: Task, member: Member, not_before: datetime | None, deadline: datetime | None
    ) -> bool:
        row = self.db.one("SELECT * FROM litter_problems WHERE task_id = ?", (task.id,))
        if row is None:
            return False
        if row["status"] != "open":
            return True  # already handled; nothing to ask
        device = self._device(int(row["device_id"])) if row["device_id"] else None
        the = _the(device.name if device else "litter box")
        now = clock.now()
        kind, detail = str(row["problem"]), str(row["detail"])
        not_before = max(now, datetime.fromisoformat(row["opened_at"]) + WAIT, not_before or now)
        if kind == SOLUTION and detail == OUT:
            text = OUT_TEXT.format(The=_cap(the))
        elif kind == SOLUTION:
            text = LOW_TEXT.format(The=_cap(the), left=self._left(row))
        elif kind == GRANULES:
            text = GRANULES_TEXT.format(The=_cap(the), used=detail)
        else:
            text = TEXTS[kind].format(The=_cap(the), detail=detail)
            if self.unnamed_codes(int(row["device_id"] or 0)):
                text += UNKNOWN_ASK
        if kind in URGENT or detail == OUT:
            deadline = not_before  # due when it may go: the daily limit doesn't hold it
        self._withdraw(task, member)  # one nudge per problem waiting for them
        result = await self.services.outbox.send(
            member,
            text,
            priority=Priority.NORMAL,
            kind=KIND,
            buttons=[
                Button(DONE, "task", {"task": task.id, "action": "done"}),
                Button(LATER, "task", {"task": task.id, "action": "later", "minutes": LATER_FOR}),
            ],
            not_before=not_before,
            deadline=deadline,
            dedupe_key=f"task-{task.id}-{secrets.token_hex(4)}",  # one of the task's nudges
        )
        if result.outbox_id is not None:
            self.db.execute(
                "UPDATE tasks SET prompt_outbox_id = ? WHERE id = ?", (result.outbox_id, task.id)
            )
        return True

    async def _task_changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        """Done or taken off the list by a person (a tap, a word in chat, a tick on the wall):
        handled as far as Themi's concerned. For the granules, the count starts again."""
        if change not in ("done", "cancelled"):
            return
        now = to_utc_iso(clock.now())
        for row in self.db.query(
            "SELECT * FROM litter_problems WHERE task_id = ? AND status = 'open'", (task.id,)
        ):
            self.db.execute(
                "UPDATE litter_problems SET status = 'done', closed_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            if row["problem"] == GRANULES:  # nothing will show it gone: it is now
                self.db.execute(
                    "UPDATE litter_problems SET gone_at = ? WHERE id = ?", (now, row["id"])
                )
                self.db.execute(
                    "UPDATE litter_granules SET since_cycles = (SELECT cycles FROM litter_states "
                    "WHERE device_id = ?) WHERE device_id = ?",
                    (row["device_id"], row["device_id"]),
                )

    async def _done(self, task: Task, by: Member, interactive: bool) -> None:
        """Someone did it: a small chore's effort for them. Not when the box showed it
        sorted (that's 'cleared'), which says nothing about who did it."""
        row = self.db.one(
            "SELECT * FROM litter_problems WHERE task_id = ? AND status = 'done'", (task.id,)
        )
        if row is not None:
            note = f"saw to the litter box ({row['problem']})"
            self.services.energy.record(by, "device_activity", EFFORT, note)

    async def _broken(self, why: str) -> None:
        for member in self.store.list_members():
            if member.is_admin:
                await self.services.outbox.send(
                    member,
                    BROKEN_TEXT.format(why=why),
                    priority=Priority.NORMAL,
                    kind=KIND,
                    dedupe_key=f"catgenie-broken-{clock.now().date().isoformat()}",
                )

    # ----- asked about ------------------------------------------------------------------

    def chores(self, device_id: int) -> list[str]:
        """The granules' count, and each open chore for the box: whose it is, and whether
        they've been asked."""
        lines = []
        every, used = self.granules(device_id)
        if every is not None and used is not None:
            lines.append(
                f"Granules: {used} clean{'s' if used != 1 else ''} since they were last topped "
                f"up (a top-up every {every})."
            )
        for row in self.db.query(
            "SELECT * FROM litter_problems WHERE device_id = ? AND status = 'open' "
            "AND task_id IS NOT NULL ORDER BY id",
            (device_id,),
        ):
            task = self._task(row)
            if task is None:
                continue
            if task.either:
                whose = "either of you"
            elif task.assignee is not None:
                whose = f"{self.store.get_member(task.assignee).name}'s"
            else:
                whose = "nobody's yet"
            asked = self.db.scalar(
                "SELECT MIN(sent_at) FROM outbox WHERE status = 'sent' AND dedupe_key LIKE ?",
                (f"task-{task.id}-%",),
            )
            when = (
                f"asked at {clock_words(to_local(datetime.fromisoformat(asked), self._timezone()))}"
                if asked
                else "not asked yet"
            )
            lines.append(f"Open chore: {task.title}, {whose}, {when}.")
        return lines

    # ----- codes the family names (F60b) ------------------------------------------------

    def unnamed_codes(self, device_id: int | None = None) -> list[str]:
        """Bare-number codes a box shows now with no words yet, while its problem is open."""
        found: list[str] = []
        for row in self.db.query(
            "SELECT DISTINCT device_id FROM litter_problems WHERE status = 'open' "
            "AND problem IN (?, ?)",
            (ERROR, ALERT),
        ):
            if device_id is not None and row["device_id"] != device_id:
                continue
            device = self._device(int(row["device_id"])) if row["device_id"] else None
            reading = self.watcher.reading(device) if device else None
            codes = reading.unknown if reading else ()
            # A code in words ("HEATER_FAULT") says itself; a bare number needs naming.
            found += [c for c in codes if c.strip().isdigit() and c not in found]
        return found

    def _unnamed_groups(self, member: Member) -> set[str]:
        return {"devices"} if self.unnamed_codes() else set()

    def _unnamed_items(self, member: Member) -> list[OpenItem]:
        codes = self.unnamed_codes()
        if not codes:
            return []
        listed = ", ".join(codes)
        return [
            OpenItem(
                f"The litter box shows a code Themi has no words for ({listed}). If they say "
                "what the CatGenie app calls it ('it says Error: Drainage issue'), that's "
                "name_litter_code, not complete_task: they haven't said it's sorted."
            )
        ]

    def seen_code(self, code: str) -> bool:
        """A code a box has reported: showing now, or in a problem's words."""
        if code in self.unnamed_codes():
            return True
        return bool(
            self.db.one(
                "SELECT 1 FROM litter_problems WHERE detail LIKE ?", (f"%yet ({code})%",)
            )
        )

    def learn(self, member: Member, code: str, said: str) -> str:
        code = code.strip()
        named = self.watcher.named()
        if code in CODES or code in named:
            return f"Code {code} already has its words: {error_words(code, named)}."
        if not self.seen_code(code):
            raise ToolFailed(f"No litter box has shown code {code}, so there's nothing to name.")
        words = code_words(said)
        if not words:
            raise ToolFailed("Say what the CatGenie app calls it, in a few words.")
        before = error_words(code, named)
        self.db.execute(
            "INSERT INTO litter_codes (code, words, member_id, said_at) VALUES (?, ?, ?, ?)",
            (code, words, member.id, to_utc_iso(clock.now())),
        )
        after = named_words(words)
        for table, column in (("litter_problems", "detail"), ("litter_states", "alert")):
            self.db.execute(
                f"UPDATE {table} SET {column} = replace({column}, ?, ?) "  # noqa: S608
                f"WHERE {column} LIKE ?",
                (before, after, f"%{before}%"),
            )
        return LEARNED_TEXT.format(code=code, words=words)

    def _task_note(self, task: Task) -> str | None:
        row = self.db.one(
            "SELECT detail FROM litter_problems WHERE task_id = ? AND status = 'open' "
            "AND problem IN (?, ?)",
            (task.id, ERROR, ALERT),
        )
        return f"(The box: {row['detail']}.)" if row else None

    # ----- small things -------------------------------------------------------------------

    def _withdraw(self, task: Task, member: Member) -> None:
        """Before a new nudge: this person's waiting ones go. A chore for either of you keeps
        the other's."""
        if not task.shared:
            self.board.withdraw_prompt(task)
            return
        for queued in self.db.query(
            "SELECT id FROM outbox WHERE status = 'queued' AND member_id = ? AND dedupe_key LIKE ?",
            (member.id, f"task-{task.id}-%"),
        ):
            self.services.outbox.cancel(queued["id"])

    def _left(self, row: dict[str, Any]) -> str:
        state = self.db.one(
            "SELECT sani_left, sani_unit FROM litter_states WHERE device_id = ?",
            (row["device_id"],),
        )
        if state is None or state["sani_left"] is None:
            return ""
        left = int(state["sani_left"])  # cleans, on every box (F58b)
        return f" (about {left} clean{'' if left == 1 else 's'} left)"

    def _timezone(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    def _live(self, device_id: int, problem: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM litter_problems WHERE device_id = ? AND problem = ? "
            "AND gone_at IS NULL ORDER BY id",
            (device_id, problem),
        )

    def _task(self, row: dict[str, Any]) -> Task | None:
        if row["task_id"] is None:
            return None
        task = self.board.get(row["task_id"])
        return task if task.status in ("open", "snoozed") else None

    def _sent(self, task: Task) -> bool:
        return (
            self.db.one(
                "SELECT 1 FROM outbox WHERE status = 'sent' AND dedupe_key LIKE ?",
                (f"task-{task.id}-%",),
            )
            is not None
        )

    def _device(self, device_id: int) -> Device | None:
        return next((d for d in self.watcher.devices() if d.id == device_id), None)


def _the(name: str) -> str:
    """ "the CatGenie" from the app's "CatGenie"; "Mochi's litter box" as it is."""
    name = name.strip() or "litter box"
    if "'" in name or "\u2019" in name or name.lower().startswith("the "):
        return name
    return f"the {name}"


def _possessive(the: str) -> str:
    return the + ("'" if the.endswith("s") else "'s")


def _cap(words: str) -> str:
    return words[0].upper() + words[1:]


def code_words(said: str) -> str:
    """F60b: "Error: Drainage issue" -> "a drainage issue"; "Clogged waste" -> "a clogged
    waste error". Short, their words, no quotes or "Error:"."""
    text = re.sub(r"^\s*(?:it says|says)\s+", "", said.strip(), flags=re.IGNORECASE)
    text = re.sub(r"^\s*error\s*[:\-]?\s*", "", text, flags=re.IGNORECASE)
    text = text.strip(" \"'“”‘’.!").strip()
    text = re.sub(r"\s+", " ", text)[:60].strip()
    if not text:
        return ""
    acronym = len(text) > 1 and text[:2].isupper()  # "UV lamp fault" stays, and is "a UV"
    if not acronym:
        text = text[0].lower() + text[1:]
    if not ENDS_IN_A_KIND.search(text.lower()):
        text += " error"
    if re.match(r"(?:an?|the)\b", text):
        return text
    return ("an " if not acronym and text[0] in "aeiou" else "a ") + text


@tool(
    "name_litter_code",
    "What the CatGenie app calls a litter box code Themi didn't know, when they say it ('It "
    "says Error: Drainage issue' for code 3). code: the number Themi said; words: their words "
    "for it. Themi uses them from then on. It doesn't mark the chore done.",
    {"code": {"type": "string"}, "words": {"type": "string"}},
)
async def name_litter_code(ctx: ToolContext, args: dict[str, Any]) -> str:
    box = ctx.services.maybe(keys.litter_box)
    if box is None:
        raise ToolFailed("The litter box isn't linked.")
    return box.learn(ctx.member, str(args.get("code") or ""), str(args.get("words") or ""))
