"""Body double (BD1a, Erin's spec of 2026-11-06): Themi keeps someone company while they work.

"Sit with me while I do the taxes", "pomodoro the laundry", /bodydouble or [Body double]
on a bigger task's nudge starts a session, about a task or just their own words ("my
writing"). One at a time per person; a new one ends the old.

- Silent Anchor (`silent`): one line ("I'm here. Going quiet until 3:40."), then nothing
  until the planned end, when "That's the hour. How did it go?" [Done] [Not finished] [A bit
  longer]. Open-ended, the same question comes after four hours.
- Sprint Partner (`sprint`): work and break blocks, the person's own lengths (25 and 5 by
  default). "That's 25 minutes. Break for 5?" [Break] [Keep going] [Stop here]; "Break's
  done whenever you are." [Carry on] [A bit longer] [Stop here].
- Guided Step-Through (`guided`): BD1b.

While one runs, task nudges, check-ins and summaries wait (a "body_double" pause, B1's
machinery); replies, approvals and urgent alerts still come. A question nobody answers
leaves the session waiting, still paused, for an hour from the question, then it ends as
`left`, quietly. Each block's end is a scheduler job on `themi.clock`.

[Done] on a session with a task marks the task done, warm word and all (F19b). Starting a
break or burnout mode ends a session as `stopped`. The hour of the week and the energy
level at the start are kept for BD2's learning and never shown. Nothing here mentions
energy, scores or how past sessions went.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import BODY_DOUBLE_KIND, Priority
from themi.core import praise
from themi.core.tasks import NotFound, Task
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_local, to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.scheduler import Scheduler

log = logging.getLogger(__name__)

TOPIC = "body_double"
JOB = "body_double.tick"
KIND = BODY_DOUBLE_KIND
SILENT = "silent"
SPRINT = "sprint"
GUIDED = "guided"
MODES = (SILENT, SPRINT, GUIDED)
MODE_WORDS = {
    "": "",
    "silent": SILENT, "quiet": SILENT, "anchor": SILENT, "silent anchor": SILENT,
    "company": SILENT,
    "sprint": SPRINT, "sprints": SPRINT, "pomodoro": SPRINT, "sprint partner": SPRINT,
    "guided": GUIDED, "steps": GUIDED, "step": GUIDED, "step by step": GUIDED,
    "guided step-through": GUIDED,
}  # fmt: skip
OPEN_ENDED = timedelta(hours=4)  # an open session asks how it went after this long
LEFT_AFTER = timedelta(hours=1)  # a question with no answer: the session waits this long
LONGER = 15  # minutes: Silent Anchor's [A bit longer]
MAX_MINUTES = 8 * 60

START_UNTIL_TEXT = "I'm here. Going quiet until {until}."
START_OPEN_TEXT = "I'm here. Going quiet until you say you're done."
SPRINT_START_TEXT = "Sprint on: {work} minutes, then a {brk}-minute break. I'll say when."
END_ASK_TEXT = "That's {span}. How did it go?"
WORK_END_TEXT = "That's {work} minutes. Break for {brk}?"
BREAK_TEXT = "Break on, back at {until}."
BREAK_END_TEXT = "Break's done whenever you are."
KEEP_GOING_TEXT = "Another {work} minutes, then. I'll say when."
LONGER_TEXT = "A bit longer, then: quiet until {until}."
BREAK_LONGER_TEXT = "A longer break, then: back at {until}."
DONE_TEXT = "That's done. {praise}"
NOT_FINISHED_TEXT = "That's fine. It'll keep for another time."
STOPPED_TEXT = "Stopping there."
STOPPED_TASK_TEXT = "Stopping there. If {title} is done, tap below."
ENDED_TEXT = "That session's over."
NO_SESSION_TEXT = "There's no session going on."
SWITCHED_TEXT = {
    SILENT: "Quiet company instead: going quiet until {until}.",
    SPRINT: "Sprints instead: {work} minutes on, then a {brk}-minute break.",
    GUIDED: "Step by step instead.",
}
SWITCHED_OPEN_TEXT = "Quiet company instead: going quiet until you say you're done."
MODE_NAMES = {SILENT: "quiet company", SPRINT: "sprints", GUIDED: "step by step"}


@dataclass
class Session:
    id: int
    member_id: int
    task_id: int | None
    label: str
    category: str | None
    mode: str
    started_at: datetime
    planned_minutes: int | None
    work_minutes: int
    break_minutes: int
    blocks_done: int
    phase: str
    asking: str | None
    phase_ends_at: datetime | None
    seq: int
    pause_id: int | None
    ask_outbox_id: int | None
    ended_at: datetime | None
    outcome: str | None
    row: dict[str, Any]

    @property
    def ends_at(self) -> datetime | None:
        """When the whole session is planned to end (None: open-ended)."""
        if self.planned_minutes is None:
            return None
        return self.started_at + timedelta(minutes=self.planned_minutes)


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _session(row: dict[str, Any]) -> Session:
    started = datetime.fromisoformat(row["started_at"])
    return Session(
        id=row["id"],
        member_id=row["member_id"],
        task_id=row["task_id"],
        label=row["label"],
        category=row["category"],
        mode=row["mode"],
        started_at=started,
        planned_minutes=row["planned_minutes"],
        work_minutes=row["work_minutes"],
        break_minutes=row["break_minutes"],
        blocks_done=row["blocks_done"],
        phase=row["phase"],
        asking=row["asking"],
        phase_ends_at=_when(row["phase_ends_at"]),
        seq=row["seq"],
        pause_id=row["pause_id"],
        ask_outbox_id=row["ask_outbox_id"],
        ended_at=_when(row["ended_at"]),
        outcome=row["outcome"],
        row=row,
    )


def span_words(minutes: int) -> str:
    """ "the hour", "two hours", "30 minutes": how long, for "That's ... ." """
    if minutes == 60:
        return "the hour"
    if minutes % 60 == 0:
        hours = minutes // 60
        names = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
        return f"{names.get(hours, str(hours))} hours"
    return f"{minutes} minutes"


def parse_command(argument: str) -> tuple[str, int]:
    """`/bodydouble [mode] [minutes]`: ("", 0) when neither is given. Raises ValueError."""
    words = argument.lower().split()
    minutes = 0
    mode_words = []
    for word in words:
        if word.isdigit():
            minutes = int(word)
        elif word not in ("min", "mins", "minutes"):
            mode_words.append(word)
    said = " ".join(mode_words)
    if said not in MODE_WORDS:
        raise ValueError(said)
    return MODE_WORDS[said], minutes


# Something that starts a session may want to change how (BD2: the mode it picks, and the
# offer to switch). (member, task, label) -> the mode to use, when none was said.
ModeChooser = Callable[[Member, Task | None, str], str]
# What else a start says or offers (BD2's offer, BD3a's [Open], BD5c's music):
# (session, text, buttons) -> (text, buttons).
StartDecorator = Callable[[Session, str, list[Button]], Awaitable[tuple[str, list[Button]]]]
EndListener = Callable[[Session, str], Awaitable[None]]


class BodyDouble:
    def __init__(self, services: Services, jobs: Scheduler) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        self.jobs = jobs
        self.pauses = services.outbox.pauses
        self.choose_mode: ModeChooser = lambda member, task, label: SILENT
        self.start_decorators: list[StartDecorator] = []
        self.end_listeners: list[EndListener] = []
        self.guided: Any = None  # BD1b's GuidedSteps, once installed

    def install(self) -> None:
        s = self.services
        s.body_double = self
        self.jobs.handler(JOB)(self.run_job)
        s.button_handlers["body_double"] = self.on_button
        s.add_command(
            "/bodydouble",
            self.on_command,
            "Company while you work: /bodydouble, /bodydouble sprint, /bodydouble quiet 45",
        )
        s.open_item_sources.append(self.open_items)
        if s.taskboard is not None:
            s.taskboard.nudge_buttons.append(self.nudge_buttons)
        s.group_sources.append(lambda m: {"body_double"} if self.current(m) else set())
        for t in (start_body_double, switch_body_double_mode, end_body_double):
            s.tools.register(t)

    # ----- the stored session ------------------------------------------------------------

    def get(self, session_id: int) -> Session | None:
        row = self.db.one("SELECT * FROM body_double_sessions WHERE id = ?", (session_id,))
        return _session(row) if row else None

    def current(self, member: Member) -> Session | None:
        row = self.db.one(
            "SELECT * FROM body_double_sessions WHERE member_id = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (member.id,),
        )
        return _session(row) if row else None

    def _set(self, session: Session, **changes: Any) -> Session:
        """Save changes and bump `seq`, so jobs and buttons from before are stale."""
        changes["seq"] = session.seq + 1
        values = {k: to_utc_iso(v) if isinstance(v, datetime) else v for k, v in changes.items()}
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        self.db.execute(
            f"UPDATE body_double_sessions SET {assignments} WHERE id = :id",
            {**values, "id": session.id},
        )
        fresh = self.get(session.id)
        assert fresh is not None
        return fresh

    def _owner(self, session: Session) -> Member:
        return self.store.get_member(session.member_id)

    def _tz(self) -> str:
        family = self.store.get_family()
        return family.timezone if family else "UTC"

    def _clock(self, moment: datetime) -> str:
        local = to_local(moment, self._tz())
        hour = local.hour % 12 or 12
        suffix = "am" if local.hour < 12 else "pm"
        return f"{hour}:{local.minute:02d} {suffix}" if local.minute else f"{hour} {suffix}"

    def hour_of_week(self, moment: datetime) -> int:
        local = to_local(moment, self._tz())
        return local.weekday() * 24 + local.hour

    def _hold(self, session: Session, until: datetime) -> None:
        """Nudges wait until `until` and the hour after it (a question waits that long)."""
        if session.pause_id is not None:
            self.pauses.move(session.pause_id, until + LEFT_AFTER)

    def _schedule(self, session: Session, at: datetime) -> None:
        self.jobs.enqueue(JOB, {"session": session.id, "seq": session.seq}, run_after=at)

    # ----- starting -------------------------------------------------------------------------

    def task_for(self, member: Member, task_id: int) -> Task:
        board = self.services.taskboard
        if board is None:
            raise ValueError("tasks aren't set up")
        try:
            task = board.get(task_id)
        except NotFound:
            raise ValueError("there's no task with that number") from None
        if task.status in ("done", "cancelled"):
            raise ValueError(f"{task.title} is already settled")
        return task

    async def start(
        self,
        member: Member,
        *,
        mode: str = "",
        minutes: int = 0,
        task: Task | None = None,
        label: str = "",
    ) -> tuple[Session, str, list[Button]]:
        """Start a session (ending any going on). Returns it with its first message and
        buttons, for the caller to send or edit in."""
        if mode and mode not in MODES:
            raise ValueError(f"the modes are {', '.join(MODES)}")
        if not 0 <= minutes <= MAX_MINUTES:
            raise ValueError(f"a session is up to {MAX_MINUTES // 60} hours")
        label = (task.title if task is not None else label.strip()) or "this"
        if not mode:
            mode = self.choose_mode(member, task, label)
        await self.stop_for_other(member)  # one at a time: a new one ends the old
        if self.services.breaks is not None and self.services.breaks.current(member):
            self.services.breaks.end(member)  # back from a break, to work
        member = self.store.get_member(member.id)
        now = clock.now()
        pause = self.pauses.pause(member, TOPIC, now + OPEN_ENDED + LEFT_AFTER)
        session_id = self.db.execute(
            "INSERT INTO body_double_sessions (member_id, task_id, label, mode, started_at, "
            "planned_minutes, work_minutes, break_minutes, hour_of_week, energy_level, phase, "
            "pause_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'work', ?)",
            (
                member.id, task.id if task is not None else None, label, mode, to_utc_iso(now),
                minutes or None, member.sprint_work_minutes, member.sprint_break_minutes,
                self.hour_of_week(now), self.services.energy.suggested_level(member), pause.id,
            ),
        )  # fmt: skip
        session = self.get(session_id)
        assert session is not None
        log.info("Body double %s started for member %s (%s)", mode, member.id, session_id)
        session, text, buttons = await self._begin(session)
        for decorate in self.start_decorators:
            text, buttons = await decorate(session, text, buttons)
        return session, text, buttons

    async def _begin(self, session: Session) -> tuple[Session, str, list[Button]]:
        """The first block of a session in its mode, and what to say."""
        now = clock.now()
        if session.mode == GUIDED and self.guided is not None:
            session = self._set(session, phase="work", asking=None, phase_ends_at=None)
            self._hold(session, now + OPEN_ENDED)
            return await self.guided.begin(session)
        if session.mode == SPRINT:
            return self._work_block(session, SPRINT_START_TEXT)
        ends = session.ends_at or session.started_at + OPEN_ENDED
        ends = max(ends, now + timedelta(minutes=1))
        session = self._set(session, phase="work", asking=None, phase_ends_at=ends)
        self._hold(session, ends)
        self._schedule(session, ends)
        if session.ends_at is None:
            return session, START_OPEN_TEXT, []
        return session, START_UNTIL_TEXT.format(until=self._clock(ends)), []

    def _work_block(self, session: Session, template: str) -> tuple[Session, str, list[Button]]:
        now = clock.now()
        ends = now + timedelta(minutes=session.work_minutes)
        if session.ends_at is not None and session.ends_at > now:
            ends = min(ends, max(session.ends_at, now + timedelta(minutes=1)))
        session = self._set(session, phase="work", asking=None, phase_ends_at=ends)
        self._hold(session, ends)
        self._schedule(session, ends)
        text = template.format(work=session.work_minutes, brk=session.break_minutes)
        return session, text, []

    # ----- the blocks' ends ------------------------------------------------------------------

    async def run_job(self, payload: dict[str, Any]) -> None:
        session = self.get(int(payload.get("session", 0)))
        if session is None or session.ended_at is not None:
            return
        if int(payload.get("seq", -1)) != session.seq:
            return  # something changed since: a newer job carries it
        if session.phase == "asking":
            await self._end(session, "left", quietly=True)
            return
        if session.phase == "break":
            await self._ask(session, "break_end")
            return
        elapsed = clock.now() - session.started_at
        planned = session.ends_at
        over = (planned is not None and clock.now() >= planned - timedelta(seconds=30)) or (
            planned is None and elapsed >= OPEN_ENDED - timedelta(seconds=30)
        )
        if session.mode == SPRINT:
            session = self._set(session, blocks_done=session.blocks_done + 1)
        if session.mode == SPRINT and not over:
            await self._ask(session, "work_end")
        else:
            await self._ask(session, "end")

    def question(self, session: Session) -> tuple[str, list[Button]]:
        """The question being asked now, with its buttons."""
        tap = {"session": session.id, "seq": session.seq}

        def button(label: str, action: str) -> Button:
            return Button(label, "body_double", {**tap, "action": action})

        if session.asking == "work_end":
            return WORK_END_TEXT.format(work=session.work_minutes, brk=session.break_minutes), [
                button("Break", "break"),
                button("Keep going", "keep_going"),
                button("Stop here", "stop"),
            ]
        if session.asking == "break_end":
            return BREAK_END_TEXT, [
                button("Carry on", "carry_on"),
                button("A bit longer", "break_longer"),
                button("Stop here", "stop"),
            ]
        if session.planned_minutes is not None:
            span = span_words(session.planned_minutes)
        else:
            span = span_words(int((clock.now() - session.started_at).total_seconds() // 60))
        return END_ASK_TEXT.format(span=span), [
            button("Done", "done"),
            button("Not finished", "not_finished"),
            button("A bit longer", "longer"),
        ]

    async def _ask(self, session: Session, asking: str) -> None:
        now = clock.now()
        session = self._set(session, phase="asking", asking=asking, phase_ends_at=now)
        self._hold(session, now)
        self._schedule(session, now + LEFT_AFTER)
        text, buttons = self.question(session)
        member = self._owner(session)
        result = await self.services.outbox.send(
            member, text, priority=Priority.NORMAL, kind=KIND, buttons=buttons,
            deadline=now + timedelta(minutes=5),  # they set the time: on time
        )  # fmt: skip
        self.db.execute(
            "UPDATE body_double_sessions SET ask_outbox_id = ? WHERE id = ?",
            (result.outbox_id, session.id),
        )

    # ----- taps -------------------------------------------------------------------------------

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        payload = event.button.payload
        member = self.store.get_member(event.member.id)
        if payload.get("action") == "start":  # [Body double] on a task's nudge
            await self._start_from_nudge(event, member)
            return
        if payload.get("action") == "task_done":
            text = await self._task_done(member, int(payload["task"]))
            await self._reply(event, member, text, [])
            return
        session = self.get(int(payload.get("session", 0)))
        if session is None or session.member_id != member.id:
            return
        if session.ended_at is not None:
            await self._reply(event, member, ENDED_TEXT, [])
            return
        if int(payload.get("seq", -1)) != session.seq:
            return  # an old question: the session moved on
        text, buttons = await self.act(session, str(payload.get("action", "")))
        await self._reply(event, member, text, buttons)

    async def act(self, session: Session, action: str) -> tuple[str, list[Button]]:
        """What a tap does, from chat or the session page (BD3a). Returns what to show."""
        now = clock.now()
        if action in ("break", "break_longer"):
            ends = now + timedelta(minutes=session.break_minutes)
            session = self._set(session, phase="break", asking=None, phase_ends_at=ends)
            self._hold(session, ends)
            self._schedule(session, ends)
            template = BREAK_TEXT if action == "break" else BREAK_LONGER_TEXT
            return template.format(until=self._clock(ends)), []
        if action in ("keep_going", "carry_on"):
            session, text, buttons = self._work_block(session, KEEP_GOING_TEXT)
            return text, buttons
        if action == "longer":
            ends = now + timedelta(minutes=LONGER)
            planned = int((ends - session.started_at).total_seconds() // 60)
            session = self._set(
                session, phase="work", asking=None, phase_ends_at=ends, planned_minutes=planned
            )
            self._hold(session, ends)
            self._schedule(session, ends)
            return LONGER_TEXT.format(until=self._clock(ends)), []
        if action == "done":
            return await self.finish(session), []
        if action == "not_finished":
            await self._end(session, "stopped")
            return NOT_FINISHED_TEXT, []
        if action == "stop":
            return await self.stop(session)
        if self.guided is not None:
            return await self.guided.act(session, action)
        return ENDED_TEXT, []

    async def _reply(
        self, event: InboundEvent, member: Member, text: str, buttons: list[Button]
    ) -> None:
        assert event.button is not None
        if event.button.message_id is not None:
            await self.services.outbox.edit(member, event.button.message_id, text, buttons)
        else:
            await self.services.outbox.send(
                member, text, priority=Priority.REPLY, kind=KIND, buttons=buttons
            )

    async def _start_from_nudge(self, event: InboundEvent, member: Member) -> None:
        assert event.button is not None
        try:
            task = self.task_for(member, int(event.button.payload["task"]))
        except ValueError as exc:
            await self._reply(event, member, f"Not started: {exc}.", [])
            return
        if self.services.burnout is not None and self.services.burnout.current(member):
            return  # burnout mode wins; a held nudge shouldn't have been tapped
        _, text, buttons = await self.start(member, task=task)
        await self._reply(event, member, text, buttons)

    # ----- ending -------------------------------------------------------------------------

    async def finish(self, session: Session) -> str:
        """Done: the task too, as `complete_task` would (its warm word with it)."""
        await self._end(session, "finished")
        return await self._done_text(session)

    async def _done_text(self, session: Session) -> str:
        member = self._owner(session)
        if session.task_id is not None and self.services.taskboard is not None:
            return await self._task_done(member, session.task_id)
        return DONE_TEXT.format(praise=praise.word(f"bd-{session.id}"))

    async def _task_done(self, member: Member, task_id: int) -> str:
        board = self.services.taskboard
        assert board is not None
        said = await board.complete(task_id, member, interactive=True)
        last = self.db.one(
            "SELECT * FROM body_double_sessions WHERE member_id = ? AND task_id = ? "
            "AND outcome = 'stopped' ORDER BY id DESC LIMIT 1",
            (member.id, task_id),
        )
        if last is not None:  # "Stop here", then it was done after all
            self.db.execute(
                "UPDATE body_double_sessions SET outcome = 'finished' WHERE id = ?", (last["id"],)
            )
        return said

    async def stop(self, session: Session) -> tuple[str, list[Button]]:
        await self._end(session, "stopped")
        if session.task_id is None or self.services.taskboard is None:
            return STOPPED_TEXT, []
        task = self.services.taskboard.get(session.task_id)
        if task.status != "open":
            return STOPPED_TEXT, []
        return STOPPED_TASK_TEXT.format(title=task.title), [
            Button("It's done", "body_double", {"action": "task_done", "task": task.id})
        ]

    async def _end(self, session: Session, outcome: str, *, quietly: bool = False) -> None:
        if session.ended_at is not None:
            return
        self._set(session, ended_at=clock.now(), outcome=outcome, asking=None)
        member = self._owner(session)
        if session.phase == "asking" and session.ask_outbox_id is not None:
            message_id = self.services.outbox.message_id(session.ask_outbox_id)
            if message_id is not None:  # the question loses its buttons
                text, _ = self.question(session)
                await self.services.outbox.edit(member, message_id, text, ())
            else:
                self.services.outbox.cancel(session.ask_outbox_id)
        if self.current(member) is None and self.pauses.resume(member, TOPIC):
            self.services.outbox.release_held(member)  # what waited goes at the next flush
        log.info("Body double %s ended: %s%s", session.id, outcome, " (quietly)" * quietly)
        for listener in self.end_listeners:
            try:
                await listener(session, outcome)
            except Exception:
                log.exception("A body double end listener failed")

    async def stop_for_other(self, member: Member, outcome: str = "stopped") -> bool:
        """A break, burnout mode or a new session takes over: the one going on ends."""
        session = self.current(member)
        if session is None:
            return False
        await self._end(session, outcome)
        return True

    async def end(self, member: Member, *, finished: bool) -> str:
        session = self.current(member)
        if session is None:
            return NO_SESSION_TEXT
        if finished:
            return await self.finish(session)
        text, _ = await self.stop(session)
        return text

    async def switch(self, member: Member, mode: str) -> tuple[Session, str, list[Button]]:
        """A new mode for the session going on: the old row ends as `switched`, the new one
        keeps its start time (and its task)."""
        old = self.current(member)
        if old is None:
            raise ValueError("there's no session going on")
        if mode not in MODES:
            raise ValueError(f"the modes are {', '.join(MODES)}")
        if mode == old.mode:
            return old, f"It's {MODE_NAMES[mode]} already.", []
        await self._end(old, "switched")
        pause = self.pauses.pause(member, TOPIC, clock.now() + OPEN_ENDED + LEFT_AFTER)
        session_id = self.db.execute(
            "INSERT INTO body_double_sessions (member_id, task_id, label, category, mode, "
            "started_at, planned_minutes, work_minutes, break_minutes, blocks_done, "
            "hour_of_week, energy_level, phase, pause_id, switched_from) "
            "SELECT member_id, task_id, label, category, ?, started_at, planned_minutes, "
            "work_minutes, break_minutes, blocks_done, hour_of_week, energy_level, 'work', ?, id "
            "FROM body_double_sessions WHERE id = ?",
            (mode, pause.id, old.id),
        )
        session = self.get(session_id)
        assert session is not None
        if mode == GUIDED and self.guided is not None:
            return await self._begin(session)
        if mode == SPRINT:
            return self._work_block(session, SWITCHED_TEXT[SPRINT])
        session, _, buttons = await self._begin(session)
        if session.ends_at is None:
            return session, SWITCHED_OPEN_TEXT, buttons
        assert session.phase_ends_at is not None
        text = SWITCHED_TEXT[SILENT].format(until=self._clock(session.phase_ends_at))
        return session, text, buttons

    # ----- chat ---------------------------------------------------------------------------

    async def on_command(self, member: Member, argument: str) -> None:
        try:
            mode, minutes = parse_command(argument)
            _, text, buttons = await self.start(member, mode=mode, minutes=minutes)
        except ValueError:
            text, buttons = (
                "Try /bodydouble, /bodydouble sprint or /bodydouble quiet 45 (minutes).",
                [],
            )
        await self.services.outbox.send(
            member, text, priority=Priority.REPLY, kind=KIND, buttons=buttons
        )

    def open_items(self, member: Member) -> list[Any]:
        from themi.core.prompts import OpenItem, as_data

        session = self.current(member)
        if session is None:
            return []
        what = as_data("their words", session.label) if session.task_id is None else ""
        task = f" (task {session.task_id})" if session.task_id is not None else ""
        return [
            OpenItem(
                f"Keeping them company now ({MODE_NAMES[session.mode]}){task}"
                f"{': ' + what if what else ''}. 'I'm done' or 'finished' is end_body_double "
                "finished=true; 'stop' or 'I'm back' is finished=false; 'switch to sprints' "
                "or 'quiet instead' is switch_body_double_mode."
            )
        ]

    def nudge_buttons(self, task: Task) -> list[Button]:
        """[Body double] on a bigger job's nudge (effort 3 or more, or steps); never on a
        medicine or a check-in."""
        if task.medicine or task.check_in or (task.effort < 3 and not task.steps):
            return []
        return [Button("Body double", "body_double", {"action": "start", "task": task.id})]


def _body_double(ctx: ToolContext) -> BodyDouble:
    body_double = ctx.services.body_double
    if body_double is None:
        raise ToolFailed("Body double sessions aren't set up.")
    return body_double


def _mode_arg(value: Any) -> str:
    said = str(value or "").strip().lower()
    if said not in MODE_WORDS:
        raise ToolFailed("mode is '', 'quiet', 'sprint' or 'steps'.")
    return MODE_WORDS[said]


async def _send(ctx: ToolContext, text: str, buttons: list[Button]) -> None:
    await ctx.services.outbox.send(
        ctx.member, text, priority=Priority.REPLY, kind=KIND, buttons=buttons
    )


@tool(
    "start_body_double",
    "Keep them company while they do something, when they ask ('sit with me while I do the "
    "taxes', 'body double the dishes', 'pomodoro the laundry', 'keep me company while I "
    "write'). It's a session, never a new task: 'pomodoro X' is a sprint on X. mode: '' "
    "unless they said one; 'quiet' (quiet company), 'sprint' (pomodoro: work and break "
    "blocks) or 'steps' (one step at a time). minutes: how long they said, or 0. task_id: "
    "their open task it's for, or 0; what: their own words for it when it isn't a task.",
    {
        "mode": {"type": "string", "enum": ["", "quiet", "sprint", "steps"]},
        "minutes": {"type": "integer"},
        "task_id": {"type": "integer"},
        "what": {"type": "string"},
    },
)
async def start_body_double(ctx: ToolContext, args: dict[str, Any]) -> str:
    body_double = _body_double(ctx)
    burnout = ctx.services.burnout
    if burnout is not None and burnout.current(ctx.member):
        raise ToolFailed(
            "Not started: burnout mode is on, and it comes first. Keep them company in words "
            "if they'd like; nothing to do is asked of them."
        )
    mode = _mode_arg(args.get("mode"))
    task = None
    if int(args.get("task_id") or 0):
        try:
            task = body_double.task_for(ctx.member, int(args["task_id"]))
        except ValueError as exc:
            raise ToolFailed(f"Not started: {exc}.") from exc
    try:
        session, text, buttons = await body_double.start(
            ctx.member,
            mode=mode,
            minutes=int(args.get("minutes") or 0),
            task=task,
            label=str(args.get("what") or ""),
        )
    except ValueError as exc:
        raise ToolFailed(f"Not started: {exc}.") from exc
    await _send(ctx, text, buttons)
    ctx.cards.append(f"body double {session.mode}")
    return f"Started ({MODE_NAMES[session.mode]}); Themi told them itself: {text!r}"


@tool(
    "switch_body_double_mode",
    "Change how Themi keeps them company in the session going on ('switch to sprints', "
    "'quiet instead', 'let's do it step by step'). mode: 'quiet', 'sprint' or 'steps'.",
    {"mode": {"type": "string", "enum": ["quiet", "sprint", "steps"]}},
)
async def switch_body_double_mode(ctx: ToolContext, args: dict[str, Any]) -> str:
    mode = _mode_arg(args.get("mode"))
    try:
        _, text, buttons = await _body_double(ctx).switch(ctx.member, mode or SILENT)
    except ValueError as exc:
        raise ToolDeclined(f"Not switched: {exc}.") from exc
    await _send(ctx, text, buttons)
    ctx.cards.append("body double switched")
    return f"Switched; Themi told them itself: {text!r}"


@tool(
    "end_body_double",
    "End the session going on when they say they're done or stopping ('I'm done', 'stop', "
    "'I'm back', 'that's enough for now'). finished: true when they say the work is done "
    "(a task it's for is then marked done), false when they're just stopping.",
    {"finished": {"type": "boolean"}},
)
async def end_body_double(ctx: ToolContext, args: dict[str, Any]) -> str:
    body_double = _body_double(ctx)
    session = body_double.current(ctx.member)
    if session is None:
        raise ToolDeclined(NO_SESSION_TEXT)
    if bool(args.get("finished")):
        said = await body_double.finish(session)
        if session.task_id is not None:
            ctx.done.append(said)
            return (
                f'Ended, and the task is done. Themi tells them itself, word for word: "{said}" '
                "Don't say it again."
            )
        await _send(ctx, said, [])
    else:
        said, buttons = await body_double.stop(session)
        await _send(ctx, said, buttons)
    ctx.cards.append("body double ended")
    return f"Ended; Themi told them itself: {said!r}"
