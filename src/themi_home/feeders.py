"""The pet feeders' chores (32): when a feeder needs a person, someone hears about it.

From the feeders' events (Tuya, `themi_home.connectors.tuya`):

- Food running low or out, the food stuck, or another fault makes one effort-1 hands-on
  task, for whoever has the most room right now (`Matcher.roomiest`, as the laundry's). It
  goes on the wall's lists like any chore: it lasts until someone sees to it. Starting while
  that person's in quiet hours, it's for either of you instead (as the vacuum's, F23d).
- Its nudge waits 10 minutes, so a reading that bounces never sends one. Out of food or
  stuck, the pet misses a meal, so it's due at once (the daily limit doesn't hold it to
  morning; quiet hours, busy times and "/pause feeders" still do). Running low or another
  fault can wait for the usual limits. Done / Later; Later asks again in an hour.
- Running low, then out: the same task, asked again with the new words.
- The feeder showing it's sorted closes the task: done if the nudge had gone out, quietly
  taken off the list if not.
- Energy: someone saying they've done one is a small chore's effort for them (a "device
  activity" signal, kept only when that input is on for them), so the next one leans to
  whoever has more room. The feeder
  sorting itself says nothing about who did it, and nor do its feedings, so neither counts.

People see words, never codes. A problem marked done isn't raised again until the feeder
stops showing it.

Feeding now (F39a, bug #194: "Feed Juneau" went on Things to Buy): `feed_pet` dispenses
portions from the feeder named for the pet (the SmartLife app's name), or from each with
"all". It's a side effect, so it goes through the trust tiers ("pet_feed"): asked in so
many words, it's their yes. Tuya's `manual_feed` (1 to 12 portions on the family's model)
is the only command Themi sends a feeder.
"""

from __future__ import annotations

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
from themi.core.services import Services
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool
from themi.localtime import in_quiet_hours, to_local, to_utc_iso
from themi.standard.tasks import Task, TaskBoard, TaskChange, clock_words
from themi_home.connectors.tuya import (
    FAULT,
    FOOD,
    JAMMED,
    OUT,
    DeviceOffline,
    FeederEvent,
    TuyaError,
    TuyaWatcher,
)

log = logging.getLogger(__name__)

KIND = "feeder"  # the outbox kind: "/pause feeders" holds these
TITLES = {
    FOOD: "Refill {the}",
    JAMMED: "Unjam {the}",
    FAULT: "Check {the}",
}
LOW_TEXT = "{The} is running low on food{left}. Top it up when you can?"
OUT_TEXT = "{The} is out of food. Fill it before the next meal?"
TEXTS = {
    JAMMED: "{The} needs a hand: {detail}. Clear it so the next meal comes out?",
    FAULT: "{The} needs a look: {detail}. Check it when you can?",
}
BROKEN_TEXT = (
    "Tuya stopped answering for the feeders, so Themi can't see them for now: {why} It can be "
    "linked again on the website's Accounts page."
)
DONE, LATER = "Done", "Later"
WAIT = timedelta(minutes=10)  # a problem's first nudge waits this long
LATER_FOR = 60  # minutes: Later asks again in an hour
URGENT = (JAMMED,)  # with OUT: a meal would be missed
EFFORT = -0.5  # a small chore, for the energy model
FEED_CATEGORY, FEED_EXECUTOR = "pet_feed", "devices.feed"  # F39a
MOST_PORTIONS = 12  # the family's feeders take 1 to 12; a feeder's own range is kept too
EVERY = frozenset({"all", "every", "each", "both", "all of them", "everyone", "the cats"})
FEED_WORDS = re.compile(r"\b(?:feed|fed|dispens\w*|portions?|kibble|food|meal)\b", re.I)
GENERIC = re.compile(r"^(?:the |my |our )?(?:cats?|dogs?|pets?|kitty|feeders?)$")
NO_FEEDERS = "No pet feeder is linked to Themi, so nothing can be fed from here."


class Feeders:
    def __init__(self, services: Services, board: TaskBoard, watcher: TuyaWatcher) -> None:
        self.services = services
        self.board = board
        self.watcher = watcher
        self.store = services.store
        self.db = services.store.db

    def install(self) -> None:
        self.services.provide(keys.feeders, self)
        self.services.autonomy.executors.register(FEED_EXECUTOR)(self._execute_feed)
        self.services.tools.register(feed_pet)
        self.watcher.listeners.append(self.on_event)
        self.watcher.broken_listeners.append(self._broken)
        self.board.own_nudges.append(self._nudge)
        self.board.change_listeners.append(self._task_changed)
        self.board.done_hooks.append(self._done)

    # ----- the feeder -------------------------------------------------------------------

    async def on_event(self, event: FeederEvent) -> None:
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
            "INSERT INTO feeder_problems (device_id, problem, detail, status, opened_at) "
            "VALUES (?, ?, ?, 'open', ?)",
            (event.device_id, event.kind, event.detail, to_utc_iso(event.at)),
        )
        task = await self.board.create(
            assignment.assignee,
            TITLES[event.kind].format(the=_the(device.name)),
            "physical",
            1,
            nudge=False,
            assignment=assignment,
        )
        self.db.execute("UPDATE feeder_problems SET task_id = ? WHERE id = ?", (task.id, row_id))
        if in_quiet_hours(assignment.assignee, event.at, self._timezone()):
            await self.board.make_either(task.id)  # each asked as they wake; first one wins
        else:
            await self.board.prompt(task)  # now it's known as the feeder's: its own nudge

    async def _changed(self, row: dict[str, Any], event: FeederEvent) -> None:
        """The same problem in new words. Running low, then out: asked again, if it's open."""
        if row["detail"] == event.detail:
            return
        self.db.execute(
            "UPDATE feeder_problems SET detail = ? WHERE id = ?", (event.detail, row["id"])
        )
        task = self._task(row)
        if row["status"] == "open" and task is not None and event.detail == OUT:
            await self.board.prompt(task)

    async def _gone(self, event: FeederEvent) -> None:
        now = to_utc_iso(event.at)
        for row in self._live(event.device_id, event.kind):
            self.db.execute("UPDATE feeder_problems SET gone_at = ? WHERE id = ?", (now, row["id"]))
            if row["status"] != "open":
                continue
            # Closed before the task, so `_task_changed` doesn't take it for a person's word.
            self.db.execute(
                "UPDATE feeder_problems SET status = 'cleared', closed_at = ? WHERE id = ?",
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

    # ----- the nudge ------------------------------------------------------------------

    async def _nudge(
        self, task: Task, member: Member, not_before: datetime | None, deadline: datetime | None
    ) -> bool:
        row = self.db.one("SELECT * FROM feeder_problems WHERE task_id = ?", (task.id,))
        if row is None:
            return False
        if row["status"] != "open":
            return True  # already handled; nothing to ask
        device = self._device(int(row["device_id"])) if row["device_id"] else None
        the = _the(device.name if device else "feeder")
        now = clock.now()
        kind, detail = str(row["problem"]), str(row["detail"])
        not_before = max(now, datetime.fromisoformat(row["opened_at"]) + WAIT, not_before or now)
        if kind == FOOD and detail == OUT:
            text = OUT_TEXT.format(The=_cap(the))
        elif kind == FOOD:
            text = LOW_TEXT.format(The=_cap(the), left=self._left(row))
        else:
            text = TEXTS[kind].format(The=_cap(the), detail=detail)
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
        handled as far as Themi's concerned."""
        if change not in ("done", "cancelled"):
            return
        self.db.execute(
            "UPDATE feeder_problems SET status = 'done', closed_at = ? "
            "WHERE task_id = ? AND status = 'open'",
            (to_utc_iso(clock.now()), task.id),
        )

    async def _done(self, task: Task, by: Member, interactive: bool) -> None:
        """Someone did it: a small chore's effort for them. Not when the feeder showed it
        sorted (that's 'cleared'), which says nothing about who did it."""
        row = self.db.one(
            "SELECT * FROM feeder_problems WHERE task_id = ? AND status = 'done'", (task.id,)
        )
        if row is not None:
            note = f"saw to the feeder ({row['problem']})"
            self.services.energy.record(by, "device_activity", EFFORT, note)

    async def _broken(self, why: str) -> None:
        for member in self.store.list_members():
            if member.is_admin:
                await self.services.outbox.send(
                    member,
                    BROKEN_TEXT.format(why=why),
                    priority=Priority.NORMAL,
                    kind=KIND,
                    dedupe_key=f"tuya-broken-{clock.now().date().isoformat()}",
                )

    # ----- asked about ------------------------------------------------------------------

    def chores(self, device_id: int) -> list[str]:
        """Each open chore for the feeder: whose it is, and whether they've been asked."""
        lines = []
        for row in self.db.query(
            "SELECT * FROM feeder_problems WHERE device_id = ? AND status = 'open' "
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

    # ----- feeding now (F39a) -------------------------------------------------------------

    def which(self, named: str) -> list[Device]:
        """The feeders `named` means: the pet's (or feeder's) name as said, "all", or, with
        just one feeder, "the cat". ToolFailed, naming them, when it's not clear."""
        feeders = self.watcher.devices("feeder")
        if not feeders:
            raise ToolFailed(NO_FEEDERS, reply=NO_FEEDERS)
        key = _key(named)
        if key in EVERY:
            return feeders
        if not key or GENERIC.match(key):
            if len(feeders) == 1:
                return feeders
            raise ToolFailed(f"Which feeder? The linked ones: {_names(feeders)}.")
        exact = [d for d in feeders if _key(d.name) == key]
        if exact:
            return exact
        close = [d for d in feeders if key in _key(d.name) or _key(d.name) in key]
        if close:
            return close
        raise ToolFailed(f"No feeder is called {named!r}. The linked ones: {_names(feeders)}.")

    def asked(self, text: str, named: str, devices: list[Device]) -> bool:
        """Their own words asked for this feeding (never the model's say-so): a word of
        feeding, and each feeder named, or "all", or "the cat" with just one feeder."""
        if not FEED_WORDS.search(text):
            return False
        said = f" {_plain(text)} "
        if _key(named) in EVERY:
            return any(f" {word} " in said for word in EVERY if " " not in word) or (
                "cats" in said or "dogs" in said or "pets" in said
            )
        if len(self.watcher.devices("feeder")) == 1 and len(devices) == 1:
            return True
        return all(f" {_key(d.name)} " in said or f" {_key(d.name)}s " in said for d in devices)

    async def _execute_feed(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        """Feeds each; raises when none could be, so the action is failed and can be tried
        again (never "done" with nothing fed)."""
        portions = int(payload.get("portions") or 1)
        fed: list[str] = []
        missed: list[str] = []
        for device_id in payload["devices"]:
            device = self._device(int(device_id))
            if device is None:
                missed.append("a feeder that isn't linked any more")
                continue
            try:
                sent = await self.watcher.feed(device, portions)
            except DeviceOffline:
                missed.append(f"{device.name}'s (offline)")
                continue
            except TuyaError as exc:
                log.warning("Couldn't feed from %s: %s", device.name, exc)
                missed.append(f"{device.name}'s (couldn't be reached)")
                continue
            fed.append(f"Fed {device.name}: {sent} portion{'s' if sent != 1 else ''}.")
        if not fed:
            raise FeedFailed(f"No feeder dispensed: {', '.join(missed)}")
        if missed:
            fed.append(f"Nothing came out of {_names_and(missed)} feeder.")
        return " ".join(fed)

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
        level = self.db.scalar(
            "SELECT level FROM feeder_states WHERE device_id = ?", (row["device_id"],)
        )
        return f" (about {level}% left)" if level is not None else ""

    def _timezone(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    def _live(self, device_id: int, problem: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM feeder_problems WHERE device_id = ? AND problem = ? "
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
    """ "the cat feeder" from the SmartLife app's "Cat Feeder"; "Mochi's feeder" as it is."""
    name = name.strip() or "feeder"
    if "'" in name or "\u2019" in name:
        return name
    return f"the {name.lower()}"


def _cap(words: str) -> str:
    return words[0].upper() + words[1:]


def _key(name: str) -> str:
    """ "Juneau's feeder" and "juneau" alike: lower case, no "feeder", no possessive."""
    key = " ".join(re.sub(r"[^\w' ]+", " ", name.lower().replace("\u2019", "'")).split())
    key = re.sub(r"(?:'s)?\s*(?:cat |pet )?feeders?$", "", key).strip()
    return re.sub(r"'s$", "", key).strip()


def _plain(text: str) -> str:
    """Their words, lower case, with no possessives or punctuation: "feed juneau s" -> no:
    "Feed Juneau's" -> "feed juneau"."""
    text = re.sub(r"'s\b", "", text.lower().replace("\u2019", "'"))
    return " ".join(re.sub(r"[^\w ]+", " ", text).split())


def _names(devices: list[Device]) -> str:
    return ", ".join(d.name for d in devices)


def _names_and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


class FeedFailed(Exception):
    """No feeder dispensed: the action fails, and is still there to try again."""


@staged_tool(
    "feed_pet",
    "Dispense food now from a pet feeder, when they ask ('feed Juneau', 'give Merlin a "
    "portion', 'feed the cats'). feeder: the pet's or feeder's name as they said it, or "
    "'all'; blank when there's just one. portions: how many, 1 unless they said. This is "
    "the feeder, never a list or a task: 'Feed Juneau' is never added to a list.",
    {
        "feeder": {"type": "string", "default": ""},
        "portions": {"type": "integer", "minimum": 1, "maximum": MOST_PORTIONS, "default": 1},
    },
)
async def feed_pet(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    feeders = ctx.services.maybe(keys.feeders)
    if feeders is None:
        raise ToolDeclined(NO_FEEDERS)
    named = str(args.get("feeder") or "")
    devices = feeders.which(named)
    offline = [d.name for d in devices if feeders.watcher.states().get(d.id) == "offline"]
    if offline and len(offline) == len(devices):
        said = f"{_names_and(offline)}'s feeder is offline, so nothing can come out right now."
        raise ToolFailed(said, reply=said)
    portions = int(args.get("portions") or 1)
    names = _names_and([d.name for d in devices])
    each = f"{portions} portion{'s' if portions != 1 else ''}"
    return Proposal(
        FEED_CATEGORY,
        f"Feed {names} {each} from the feeder",
        FEED_EXECUTOR,
        {"devices": [d.id for d in devices], "portions": portions},
        requested=feeders.asked(ctx.request_text, named, devices),
        said=f"Fed {names}: {each}." if len(devices) == 1 else None,
    )
