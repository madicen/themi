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

Working the box (F63b, Erin's idea #268): starting or stopping a clean and changing its
settings go through the trust tiers (`litter_box_control`, asked each time to start with).
An error's nudge has "Try a clean": the tap is the yes. Once the box has finished that
clean, the one who tapped hears how it went: the error cleared (the chore closes), or it
came back (the chore stays and says so). The API can't clear an error or say what caused it;
a clean that finishes is the only test there is.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from themi import clock
from themi.accounts import Device, Member
from themi.autonomy import ExecutionContext
from themi.channels.outbox import Button, Priority
from themi.core import keys
from themi.core.prompts import OpenItem
from themi.core.services import Services
from themi.core.tools import Proposal, ToolContext, ToolFailed, staged_tool, tool
from themi.localtime import in_quiet_hours, to_local, to_utc_iso
from themi.standard.tasks import Task, TaskBoard, TaskChange, clock_words
from themi_home.connectors.catgenie import (
    ALERT,
    ERROR,
    GRANULES,
    OUT,
    SOLUTION,
    CatGenieError,
    CatGenieWatcher,
    LitterBoxEvent,
    LitterBoxReading,
)
from themi_home.connectors.catgenie.events import (
    CODES,
    error_words,
    named_words,
    settings_words,
)
from themi_home.connectors.catgenie.events import clock_words as hours_words

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
QUOTES = " \"'\u201c\u201d\u2018\u2019.!"  # trimmed from what they said the app shows
UNKNOWN_ASK = " What does the CatGenie app call it?"  # F60b: so a reply is expected
LEARNED_TEXT = "Got it: code {code} is {words}. I'll say that from now on."
# F63b: working the box
CONTROL = "litter_box_control"  # the trust category
CLEAN, CONFIGURE = "litter_box.clean", "litter_box.settings"  # the executors
BUTTON = "litter"  # the button kind: an error's "Try a clean"
TRY = "Try a clean"
RETRY_FOR = timedelta(hours=2)  # a "Try a clean" that hasn't cleaned by then is let go
CLEARED, BACK, NONE = "cleared", "back", "none"  # how a "Try a clean" went
RETRY_STARTED = "Starting a clean on {the}. I'll tell you how it goes once it's done."
RETRY_CLEARED = "{The} finished a clean and the error's gone, so that chore's off the list."
RETRY_BACK = (
    "{The} finished a clean, but it's still showing the error ({detail}), so it needs a look "
    "by hand."
)
RETRY_NOTE = " A clean was tried and the error came back."
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
        self.services.autonomy.executors.register(CLEAN)(self._clean)  # F63b
        self.services.autonomy.executors.register(CONFIGURE)(self._configure)
        self.services.button_handlers[BUTTON] = self.on_button
        self.watcher.reading_listeners.append(self._retry_check)
        self.services.tools.register(litter_box_clean)
        self.services.tools.register(litter_box_settings)

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
        for row in self._live(event.device_id, event.kind):
            if self._retrying(row):  # F63b: told once the clean's done (`_retry_check`)
                continue
            await self._close_cleared(row)

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
            buttons=chore_buttons(task.id, retry=kind in URGENT),
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
            self.db.one("SELECT 1 FROM litter_problems WHERE detail LIKE ?", (f"%yet ({code})%",))
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
                f"UPDATE {table} SET {column} = replace({column}, ?, ?) WHERE {column} LIKE ?",
                (before, after, f"%{before}%"),
            )
        return LEARNED_TEXT.format(code=code, words=words)

    def _task_note(self, task: Task) -> str | None:
        row = self.db.one(
            "SELECT detail, retry_outcome FROM litter_problems WHERE task_id = ? "
            "AND status = 'open' AND problem IN (?, ?)",
            (task.id, ERROR, ALERT),
        )
        if row is None:
            return None
        tried = RETRY_NOTE if row["retry_outcome"] == BACK else ""  # F63b
        return f"(The box: {row['detail']}.{tried})"

    # ----- working the box (F63b) ---------------------------------------------------------

    def which(self, named: str) -> Device:
        """The litter box `named` means (its name, or with one box, "the litter box")."""
        boxes = self.watcher.devices()
        if not boxes:
            raise ToolFailed("No litter box is linked.", reply="No litter box is linked.")
        key = re.sub(r"[^a-z0-9 ]", "", named.lower()).strip()
        key = re.sub(r"^(?:the|my|our)\s+", "", key)
        if not key or key in ("litter box", "litter", "catgenie", "cat genie", "box"):
            if len(boxes) == 1:
                return boxes[0]
            raise ToolFailed(f"Which litter box? {_names(boxes)}.")
        found = [b for b in boxes if key in b.name.lower() or b.name.lower() in key]
        if len(found) == 1:
            return found[0]
        raise ToolFailed(f"Which litter box? {_names(boxes)}.")

    def cant_clean(self, device: Device) -> str | None:
        """Why a clean can't start now, in words; None when it can."""
        the = _the(device.name)
        reading = self.watcher.reading(device)
        if reading is None:
            return f"Themi hasn't been able to read {the} yet."
        if not reading.online:
            return f"{_cap(the)} is offline, so it can't start a clean."
        if reading.cleaning:
            return f"{_cap(the)} is cleaning already."
        if reading.problems.get(SOLUTION) == OUT:
            return (
                f"{_cap(the)} is out of sani-solution, so it can't wash. Swap the cartridge first."
            )
        return None

    async def retry(self, member: Member, task_id: int) -> tuple[bool, str]:
        """An error's "Try a clean": the tap is the yes. (started, what to say)"""
        row = self.db.one(
            "SELECT * FROM litter_problems WHERE task_id = ? AND status = 'open' "
            "AND problem IN (?, ?) ORDER BY id DESC",
            (task_id, ERROR, ALERT),
        )
        device = self._device(int(row["device_id"])) if row and row["device_id"] else None
        if row is None or device is None:
            return False, "That's sorted already."
        why = self.cant_clean(device)
        if why:
            return False, why
        # The tap asks for exactly this, so it's their yes: no card on top of it.
        outcome = await self.services.autonomy.stage(
            CONTROL, member, f"Start a clean on {_the(device.name)}",
            {"device": device.id, "clean": True}, CLEAN, interactive=True, requested=True,
        )  # fmt: skip
        if outcome.action.status != "done":
            return False, outcome.message
        self.db.execute(
            "UPDATE litter_problems SET retried_at = ?, retried_by = ?, retry_outcome = NULL "
            "WHERE id = ?",
            (to_utc_iso(clock.now()), member.id, row["id"]),
        )
        return True, RETRY_STARTED.format(the=_the(device.name))

    async def on_button(self, event: Any) -> None:
        payload = event.button.payload
        member = self.store.get_member(event.member.id)
        task_id = int(payload.get("task") or 0)
        started, said = await self.retry(member, task_id)
        # The tap used up the nudge's buttons: when nothing started, the chore's come back.
        live = not started and self._open_problem(task_id)
        await self.services.outbox.send(
            member, said, priority=Priority.REPLY, kind=KIND,
            buttons=chore_buttons(task_id, retry=True) if live else [],
        )  # fmt: skip

    def _open_problem(self, task_id: int) -> bool:
        return (
            self.db.one(
                "SELECT 1 FROM litter_problems WHERE task_id = ? AND status = 'open'", (task_id,)
            )
            is not None
        )

    async def _clean(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        device = self._device(int(payload["device"]))
        if device is None:
            raise CatGenieError("That litter box isn't linked any more.")
        the = _the(device.name)
        if payload.get("clean"):
            await self.watcher.account.start_clean(device.external_id)
            self._expect(device, cleaning=True)
            return f"Started a clean on {the}."
        await self.watcher.account.stop_clean(device.external_id)
        self._expect(device, cleaning=False)
        return f"Stopped {_possessive(the)} clean."

    async def _configure(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        device = self._device(int(payload["device"]))
        if device is None:
            raise CatGenieError("That litter box isn't linked any more.")
        await self.watcher.account.configure(device.external_id, dict(payload["fields"]))
        return f"Done: {_the(device.name)} now {payload['words']}."

    def _expect(self, device: Device, *, cleaning: bool) -> None:
        """The kept report says what was just asked of it until the next read."""
        raw = self.watcher.raw(device)
        if raw is None:
            return
        status = raw.setdefault("operationStatus", {})
        status.update({"state": 1, "progress": 0} if cleaning else {"state": 0, "progress": 255})
        self.db.execute(
            "UPDATE catgenie_devices SET raw = ? WHERE device_id = ?",
            (json.dumps(raw), device.id),
        )

    def _retrying(self, row: dict[str, Any]) -> bool:
        if not row.get("retried_at") or row.get("retry_outcome"):
            return False
        return clock.now() - datetime.fromisoformat(row["retried_at"]) < RETRY_FOR

    async def _retry_check(self, device: Device, reading: LitterBoxReading) -> None:
        """Each read: a "Try a clean" whose clean is done says how it went."""
        for row in self.db.query(
            "SELECT * FROM litter_problems WHERE device_id = ? AND retried_at IS NOT NULL "
            "AND retry_outcome IS NULL AND gone_at IS NULL",
            (device.id,),
        ):
            since = datetime.fromisoformat(row["retried_at"])
            done = (
                not reading.cleaning
                and reading.last_clean is not None
                and reading.last_clean > since
            )
            if not done and clock.now() - since < RETRY_FOR:
                continue
            still = ERROR in reading.problems
            outcome = (BACK if still else CLEARED) if done else NONE
            self.db.execute(
                "UPDATE litter_problems SET retry_outcome = ? WHERE id = ?", (outcome, row["id"])
            )
            if not still:
                await self._close_cleared(row)
            if outcome == NONE or not row["retried_by"]:
                continue
            member = self.store.get_member(int(row["retried_by"]))
            the = _the(device.name)
            text = (
                RETRY_CLEARED.format(The=_cap(the))
                if outcome == CLEARED
                else RETRY_BACK.format(The=_cap(the), detail=reading.problems[ERROR])
            )
            task_id = row["task_id"]
            back = outcome == BACK and task_id is not None
            await self.services.outbox.send(
                member, text, priority=Priority.NORMAL, kind=KIND,
                buttons=chore_buttons(int(task_id), retry=True) if back and task_id else [],
                dedupe_key=f"litter-retry-{row['id']}-{row['retried_at']}",
            )  # fmt: skip

    async def _close_cleared(self, row: dict[str, Any]) -> None:
        """The box isn't showing it any more: done if they'd been asked, else taken off."""
        now = to_utc_iso(clock.now())
        self.db.execute("UPDATE litter_problems SET gone_at = ? WHERE id = ?", (now, row["id"]))
        if row["status"] != "open":
            return
        # Closed before the task, so `_task_changed` doesn't take it for a person's word.
        self.db.execute(
            "UPDATE litter_problems SET status = 'cleared', closed_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        task = self._task(row)
        if task is None or task.assignee is None:
            return
        member = self.store.get_member(task.assignee)
        if self._sent(task):
            await self.board.complete(task.id, member)
        else:
            await self.board.cancel(task.id, member)

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


def chore_buttons(task_id: int, *, retry: bool) -> list[Button]:
    """A litter box chore's buttons: Done, (an error's) Try a clean, Later."""
    return [
        Button(DONE, "task", {"task": task_id, "action": "done"}),
        *([Button(TRY, BUTTON, {"task": task_id, "do": "retry"})] if retry else []),
        Button(LATER, "task", {"task": task_id, "action": "later", "minutes": LATER_FOR}),
    ]


def _names(boxes: list[Device]) -> str:
    return "The linked ones: " + ", ".join(b.name for b in boxes)


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
    text = text.strip(QUOTES).strip()
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


# ----- F63b: working the box from chat ---------------------------------------------------------


def _box(ctx: ToolContext) -> LitterBox:
    box = ctx.services.maybe(keys.litter_box)
    if box is None:
        raise ToolFailed("The litter box isn't linked.", reply="The litter box isn't linked.")
    return box


@staged_tool(
    "litter_box_clean",
    "Start or stop a clean on the CatGenie litter box now, when they ask ('run the Whoosh', "
    "'clean the litter box', 'stop the CatGenie'). box: its name as they said it, blank when "
    "there's one. stop: true to stop a clean that's running. Asks for their yes first.",
    {"box": {"type": "string", "default": ""}, "stop": {"type": "boolean", "default": False}},
)
async def litter_box_clean(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    box = _box(ctx)
    device = box.which(str(args.get("box") or ""))
    the = _the(device.name)
    if args.get("stop"):
        reading = box.watcher.reading(device)
        if reading is not None and not reading.cleaning:
            raise ToolFailed(f"{_cap(the)} isn't cleaning.", reply=f"{_cap(the)} isn't cleaning.")
        return Proposal(CONTROL, f"Stop {_possessive(the)} clean", CLEAN,
                        {"device": device.id, "clean": False})  # fmt: skip
    why = box.cant_clean(device)
    if why:
        raise ToolFailed(why, reply=why)
    return Proposal(CONTROL, f"Start a clean on {the}", CLEAN, {"device": device.id, "clean": True})


ON_OFF = {"type": "string", "enum": ["", "on", "off"], "default": ""}


@staged_tool(
    "litter_box_settings",
    "Change the CatGenie litter box's settings (appliance_status says what they are now). "
    "box: its name, blank when there's one. mode: 'automatic' (cleans after the cat) or "
    "'manual' (only when started). quiet_from, quiet_to: no cleaning between these times, "
    "24-hour 'HH:MM' ('22:00', '07:00'); 'off' in both clears it. extra_wash, extra_shake, "
    "extra_dry, panel_lock: 'on' or 'off'. volume: 1 to 7. Leave out what they didn't ask "
    "to change. Changes ask for their yes first.",
    {
        "box": {"type": "string", "default": ""},
        "mode": {"type": "string", "enum": ["", "automatic", "manual"], "default": ""},
        "quiet_from": {"type": "string", "default": ""},
        "quiet_to": {"type": "string", "default": ""},
        "extra_wash": ON_OFF,
        "extra_shake": ON_OFF,
        "extra_dry": ON_OFF,
        "panel_lock": ON_OFF,
        "volume": {"type": "integer", "minimum": 0, "maximum": 7, "default": 0},
    },
)
async def litter_box_settings(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    box = _box(ctx)
    device = box.which(str(args.get("box") or ""))
    the = _the(device.name)
    fields, words = settings_change(args)
    if not fields:
        said = settings_words(box.watcher.raw(device))
        raise ToolFailed(
            f"Nothing to change. {_cap(the)} now: {said or 'not read yet'}. Use appliance_status "
            "to say its settings."
        )
    return Proposal(
        CONTROL, f"Change {_possessive(the)} settings: {words}", CONFIGURE,
        {"device": device.id, "fields": fields, "words": words},
    )  # fmt: skip


def settings_change(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The tool's arguments as the box's fields, and in words. ToolFailed for a time that
    isn't one."""
    fields: dict[str, Any] = {}
    words: list[str] = []
    mode = str(args.get("mode") or "")
    if mode:
        fields["mode"] = 0 if mode == "automatic" else 1
        words.append("cleans automatically after the cat" if mode == "automatic"
                     else "cleans only when started")  # fmt: skip
    start, end = str(args.get("quiet_from") or "").strip(), str(args.get("quiet_to") or "").strip()
    if start or end:
        if start.lower() == "off" or end.lower() == "off":
            fields["dndFrom"], fields["dndTo"] = "", ""
            words.append("has no quiet hours")
        else:
            start, end = _hhmm(start), _hhmm(end)
            fields["dndFrom"], fields["dndTo"] = start, end
            words.append(f"doesn't clean {hours_words(start)} to {hours_words(end)}")
    extras: dict[str, bool] = {}
    for arg, key, said in (("extra_wash", "EXTRA_WASH", "extra wash"),
                           ("extra_shake", "EXTRA_SHAKE", "extra shake")):  # fmt: skip
        if args.get(arg) in ("on", "off"):
            extras[key] = args[arg] == "on"
            words.append(f"has {said} {args[arg]}")
    if extras:
        fields["binaryElements"] = extras
    if args.get("extra_dry") in ("on", "off"):
        fields["extraDry"] = args["extra_dry"] == "on"
        words.append(f"has extra dry {args['extra_dry']}")
    if args.get("panel_lock") in ("on", "off"):
        fields["childLock"] = int(args["panel_lock"] == "on")
        words.append(f"has its panel lock {args['panel_lock']}")
    volume = int(args.get("volume") or 0)
    if 1 <= volume <= 7:
        fields["volumeLevel"] = volume
        words.append(f"has its volume at {volume}")
    return fields, _and(words)


def _hhmm(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        said = "The quiet hours need a start and an end, like 22:00 and 07:00."
        raise ToolFailed(said, reply=said)
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
