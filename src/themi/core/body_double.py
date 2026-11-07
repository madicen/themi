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

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import field_validator

from themi import clock
from themi.accounts import Member
from themi.accounts.preferences import Preferences
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import BODY_DOUBLE_KIND, Priority
from themi.core import groups, keys, praise
from themi.core.body_double_scene import CHEER_FOR, pick_state
from themi.core.lists import name_key
from themi.core.tasks import NotFound, Task
from themi.core.tools import ToolContext, ToolDeclined, ToolFailed, tool
from themi.localtime import to_local, to_utc_iso
from themi.modules import Module, ModuleContext

if TYPE_CHECKING:
    from themi.core.routines import Routine
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
NEXT_UP_TEXT = "{done}\n\nNext up: {label}.\n\n{start}"
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


def _span(delta: timedelta) -> str:
    """ "24:59" or "1:05:00", as the page's timer shows it before its script runs."""
    seconds = max(0, round(delta.total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


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


# What else a start says or offers (BD2's offer, BD3a's [Open], BD5c's music):
# (session, text, buttons) -> (text, buttons).
StartDecorator = Callable[[Session, str, list[Button]], Awaitable[tuple[str, list[Button]]]]
EndListener = Callable[[Session, str], Awaitable[None]]


class BodyDoublePreferences(Preferences):
    """CR7a: each person's body double settings (BD1a, BD5a)."""

    module: ClassVar[str] = "body_double"
    sprint_work_minutes: int = 25  # a sprint's work block
    sprint_break_minutes: int = 5  # and its break
    body_double_sound: str = "lofi"  # the session page's built-in loop
    body_double_volume: int = 50  # 0-100

    @field_validator("sprint_work_minutes")
    @classmethod
    def _work(cls, value: int) -> int:
        if not 5 <= value <= 90:
            raise ValueError("a sprint's work block is between 5 and 90 minutes")
        return value

    @field_validator("sprint_break_minutes")
    @classmethod
    def _break(cls, value: int) -> int:
        if not 1 <= value <= 30:
            raise ValueError("a sprint's break is between 1 and 30 minutes")
        return value

    @field_validator("body_double_sound")
    @classmethod
    def _sound(cls, value: str) -> str:
        from themi.core.body_double_music import LOOPS  # a cycle at the top

        if value not in LOOPS:
            raise ValueError(f"the sounds are {', '.join(LOOPS)}")
        return value

    @field_validator("body_double_volume")
    @classmethod
    def _volume(cls, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError("the volume is between 0 and 100")
        return value


class BodyDouble:
    def __init__(self, services: Services, jobs: Scheduler) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        self.jobs = jobs
        self.pauses = services.outbox.pauses
        self.modes: Any = None  # BD2's ModeChooser: the job's category and the mode to use
        self.start_decorators: list[StartDecorator] = []
        self.end_listeners: list[EndListener] = []
        self.guided: Any = None  # BD1b's GuidedSteps, once installed
        self.pictures: Any = None  # BD4b's StepPictures, once installed

    def install(self) -> None:
        s = self.services
        s.provide(keys.body_double, self)
        self.jobs.handler(JOB)(self.run_job)
        s.button_handlers["body_double"] = self.on_button
        s.add_command(
            "/bodydouble",
            self.on_command,
            "Company while you work: /bodydouble, /bodydouble sprint, /bodydouble quiet 45",
        )
        s.open_item_sources.append(self.open_items)
        if s.maybe(keys.taskboard) is not None:
            s.get(keys.taskboard).nudge_buttons.append(self.nudge_buttons)
        s.group_sources.append(lambda m: {"body_double"} if self.current(m) else set())
        for t in (start_body_double, switch_body_double_mode, end_body_double):
            s.tools.register(t)
        from themi.core.body_double_music import choose_session_sound

        s.tools.register(choose_session_sound)  # BD5a
        self.start_decorators.append(self._open_button)

    async def _open_button(
        self, session: Session, text: str, buttons: list[Button]
    ) -> tuple[str, list[Button]]:
        """[Open]: the session page as a Telegram Mini App (BD3a). Telegram only opens https
        pages, so a site without one (local runs) has no button."""
        base = self.services.site_url.rstrip("/")
        if not base.startswith("https://"):
            return text, buttons
        return text, [*buttons, Button("Open", "web_app", web_app=f"{base}/session")]

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

    def remember_message(self, session: Session, message_id: int | None) -> None:
        """The chat message showing the session (its start, or the guided card)."""
        if message_id is not None:
            self.db.execute(
                "UPDATE body_double_sessions SET card_message_id = ? WHERE id = ?",
                (message_id, session.id),
            )

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
        board = self.services.maybe(keys.taskboard)
        if board is None:
            raise ValueError("tasks aren't set up")
        try:
            task = board.get(task_id)
        except NotFound:
            raise ValueError("there's no task with that number") from None
        if task.status in ("done", "cancelled"):
            raise ValueError(f"{task.title} is already settled")
        return task

    def find_task(self, member: Member, what: str) -> Task | None:
        """F34h, bug #181: the open task they named, theirs first, then anyone's (doing a
        partner's chore is fine; whoever finishes it closes it)."""
        board = self.services.maybe(keys.taskboard)
        if board is None or not what.strip():
            return None
        from themi.core.events import title_matches

        theirs = board.open_for(member)
        rows = self.db.query("SELECT id FROM tasks WHERE status IN ('open', 'snoozed')")
        others = [board.get(r["id"]) for r in rows if r["id"] not in {t.id for t in theirs}]
        for task in (*theirs, *others):
            if title_matches(what, task.title) or title_matches(task.title, what):
                return task
        return None

    def find_routine(self, member: Member, what: str) -> Routine | None:
        """F34h: "my evening routine", "the morning one"."""
        routines = self.services.maybe(keys.routines)
        if routines is None:
            return None
        said = re.sub(r"^(?:my|the|our)\s+", "", name_key(what))
        said = re.sub(r"\s+(?:one|routine)$", "", said).strip()
        return next((r for r in routines.of(member) if name_key(r.name) == said), None)

    async def start(
        self,
        member: Member,
        *,
        mode: str = "",
        minutes: int = 0,
        task: Task | None = None,
        label: str = "",
        routine: Routine | None = None,
        then: list[dict[str, Any]] | None = None,
        part: tuple[int, int] | None = None,
    ) -> tuple[Session, str, list[Button]]:
        """Start a session (ending any going on). Returns it with its first message and
        buttons, for the caller to send or edit in. With a routine (F34h), its open items
        are the steps. `then`: what comes after, in order (F34hb, `resolve`'s parts);
        `part`: (this one, of how many), for the next part of a run, which starts without
        the mode offer or the music offer."""
        if mode and mode not in MODES:
            raise ValueError(f"the modes are {', '.join(MODES)}")
        if not 0 <= minutes <= MAX_MINUTES:
            raise ValueError(f"a session is up to {MAX_MINUTES // 60} hours")
        if routine is not None:
            label = f"{routine.name} routine"
        label = (task.title if task is not None else label.strip()) or "this"
        now = clock.now()
        energy = self.services.energy.suggested_level(member)
        category = None
        chosen = False  # Themi picked the mode: the start says so, as an offer (BD2)
        queue = list(then or [])
        part_no, parts = part if part is not None else (1, 1 + len(queue))
        if routine is not None:
            category = "chores"  # F34h: a routine is household jobs; no call to ask
        elif self.modes is not None:
            category = await self.modes.category(member, task, label)
        if not mode and self.modes is not None and category is not None:
            mode = self.modes.default_for(member, category) or ""
            if not mode:
                mode = self.modes.choose(member, category, self.hour_of_week(now), energy)
                chosen = True
        mode = mode or SILENT
        await self.stop_for_other(member)  # one at a time: a new one ends the old
        if self.services.maybe(keys.breaks) is not None and self.services.get(keys.breaks).current(
            member
        ):
            self.services.get(keys.breaks).end(member)  # back from a break, to work
        member = self.store.get_member(member.id)
        pause = self.pauses.pause(member, TOPIC, now + OPEN_ENDED + LEFT_AFTER)
        prefs = self.store.preferences(member.id, BodyDoublePreferences)  # CR7a
        session_id = self.db.execute(
            "INSERT INTO body_double_sessions (member_id, task_id, label, category, mode, "
            "mode_chosen, started_at, planned_minutes, work_minutes, break_minutes, "
            "hour_of_week, energy_level, phase, pause_id, routine_id, queue, part, parts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'work', ?, ?, ?, ?, ?)",
            (
                member.id, task.id if task is not None else None, label, category, mode,
                int(chosen), to_utc_iso(now), minutes or None, prefs.sprint_work_minutes,
                prefs.sprint_break_minutes, self.hour_of_week(now), energy, pause.id,
                routine.id if routine is not None else None,
                json.dumps(queue) if queue else None, part_no if parts > 1 else None,
                parts if parts > 1 else None,
            ),
        )  # fmt: skip
        session = self.get(session_id)
        assert session is not None
        log.info("Body double %s started for member %s (%s)", mode, member.id, session_id)
        session, text, buttons = await self._begin(session)
        if part is not None:
            return session, text, buttons  # the next part of a run: no offers again
        if chosen and session.mode == mode:  # once, as an offer (BD2)
            text, buttons = self.offer(session, text, buttons)
        for decorate in self.start_decorators:
            text, buttons = await decorate(session, text, buttons)
        return session, text, buttons

    def resolve(self, member: Member, what: str) -> dict[str, Any]:
        """F34hb: one part of a run, from their words: "task 12", a routine of theirs, an
        open task by its name, or else just their words."""
        said = what.strip()
        if m := re.fullmatch(r"(?:task\s*)?#?(\d+)", said, re.IGNORECASE):
            return {"task": self.task_for(member, int(m.group(1))).id}
        if (routine := self.find_routine(member, said)) is not None:
            return {"routine": routine.id}
        if (task := self.find_task(member, said)) is not None:
            return {"task": task.id}
        return {"label": said}

    async def finish_or_next(self, session: Session) -> tuple[str, list[Button]]:
        """Done with this part: it's finished (its task closed), and the next part of the
        run, if there is one, starts in the same mode: "Next up: Put the laundry away"."""
        said = await self.finish(session)
        queue = list(json.loads(session.row.get("queue") or "[]"))
        member = self._owner(session)
        while queue:
            item = queue.pop(0)
            task = routine = None
            try:
                if "task" in item:
                    task = self.task_for(member, int(item["task"]))
                elif "routine" in item and self.services.maybe(keys.routines) is not None:
                    routine = self.services.get(keys.routines).get(int(item["routine"]))
            except (ValueError, NotFound):
                continue  # done or gone since the run began: on to the one after
            done_so_far = session.row.get("part") or 1
            new, text, buttons = await self.start(
                member, mode=session.mode, task=task, routine=routine,
                label=str(item.get("label") or ""), then=queue,
                part=(done_so_far + 1, session.row.get("parts") or done_so_far + 1),
            )  # fmt: skip
            self.db.execute(  # F34i: the playlists read for the run stay with it
                "UPDATE body_double_sessions SET playlists = ? WHERE id = ?",
                (session.row.get("playlists"), new.id),
            )
            return NEXT_UP_TEXT.format(done=said, label=new.label, start=text), buttons
        return said, []

    def part_words(self, session: Session) -> str:
        """ "Part 2 of 3" for a part of a run, else ''."""
        parts = session.row.get("parts") or 0
        return f"Part {session.row.get('part') or 1} of {parts}" if parts > 1 else ""

    def offer(self, session: Session, text: str, buttons: list[Button]) -> tuple[str, list[Button]]:
        """The mode Themi picked, said once with the other two as buttons: never a reason."""
        from themi.core.body_double_modes import OFFER_BUTTONS, OFFER_TEXT

        others = [
            Button(OFFER_BUTTONS[m], "body_double", {"session": session.id, "action": "switch",
                                                     "mode": m, "seq": session.seq})
            for m in MODES
            if m != session.mode and (m != GUIDED or self.guided is not None)
        ]  # fmt: skip
        return f"{OFFER_TEXT[session.mode]}\n{text}", [*buttons, *others]

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
        if session.mode == GUIDED and self.guided is not None and session.phase != "asking":
            await self.guided.on_job(session)
            return
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
        if session.mode == SPRINT:  # a block done: the chameleon cheers for a moment (BD3b)
            session = self._set(
                session, blocks_done=session.blocks_done + 1, cheer_until=clock.now() + CHEER_FOR
            )
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
            await self._show_current(event, member, session)  # an older card: where it is now
            return
        self.remember_message(session, event.button.message_id)
        if payload.get("action") == "switch":  # BD2's offer: another mode instead
            new, text, buttons = await self.switch(member, str(payload.get("mode")))
            self.remember_message(new, event.button.message_id)
            await self._reply(event, member, text, buttons)
            return
        text, buttons = await self.act(session, str(payload.get("action", "")))
        self._carry_message(session, member, event.button.message_id)
        await self._reply(event, member, text, buttons)

    def _carry_message(self, session: Session, member: Member, message_id: int | None) -> None:
        """F34hb: the next part of a run shows on the same message as the part before."""
        now = self.current(member)
        if now is not None and now.id != session.id:
            self.remember_message(now, message_id)

    async def _show_current(self, event: InboundEvent, member: Member, session: Session) -> None:
        """A tap on a button from an earlier moment: never nothing. A guided card or an open
        question is shown as it is now, with buttons that work; otherwise the old buttons go."""
        if session.mode == GUIDED and self.guided is not None and session.phase != "asking":
            text, buttons = self.guided.render(session)
        elif session.phase == "asking":
            text, buttons = self.question(session)
        else:
            text, buttons = self.page_line(session), self.page_buttons(session)
        await self._reply(event, member, text, buttons)
        self.remember_message(session, event.button.message_id if event.button else None)

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
            return await self.finish_or_next(session)
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
        if self.services.maybe(keys.burnout) is not None and self.services.get(
            keys.burnout
        ).current(member):
            return  # burnout mode wins; a held nudge shouldn't have been tapped
        session, text, buttons = await self.start(member, task=task)
        self.remember_message(session, event.button.message_id)
        await self._reply(event, member, text, buttons)

    # ----- ending -------------------------------------------------------------------------

    async def finish(self, session: Session) -> str:
        """Done: the task too, as `complete_task` would (its warm word with it)."""
        await self._end(session, "finished")
        return await self._done_text(session)

    async def _done_text(self, session: Session) -> str:
        member = self._owner(session)
        if session.task_id is not None and self.services.maybe(keys.taskboard) is not None:
            return await self._task_done(member, session.task_id)
        return DONE_TEXT.format(praise=praise.word(f"bd-{session.id}"))

    async def _task_done(self, member: Member, task_id: int) -> str:
        board = self.services.maybe(keys.taskboard)
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
        if session.task_id is None or self.services.maybe(keys.taskboard) is None:
            return STOPPED_TEXT, []
        task = self.services.get(keys.taskboard).get(session.task_id)
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

    # ----- the session page (BD3a) ------------------------------------------------------------

    def page_buttons(self, session: Session) -> list[Button]:
        """The same choices as chat, for the page."""
        if session.phase == "asking":
            return self.question(session)[1]
        if session.mode == GUIDED and self.guided is not None:
            return self.guided.render(session)[1]
        tap = {"session": session.id, "seq": session.seq}

        def button(label: str, action: str) -> Button:
            return Button(label, "body_double", {**tap, "action": action})

        if session.phase == "break":
            return [button("Carry on", "carry_on"), button("Stop here", "stop")]
        if session.mode == SPRINT:
            return [button("Break", "break"), button("Stop here", "stop")]
        return [button("Done", "done"), button("Not finished", "not_finished")]

    def page_line(self, session: Session) -> str:
        if session.phase == "asking":
            return self.question(session)[0]
        if session.mode == GUIDED and self.guided is not None:
            text = self.guided.render(session)[0]
            if session.phase == "work":  # the page shows the count itself
                text = text.split("\n", 1)[-1]
            return "\n".join(line.removeprefix("> ") for line in text.splitlines())
        if session.phase == "break":
            return "On a break."
        if session.mode == SPRINT:
            return f"Working, {session.work_minutes} minutes at a time."
        if session.phase_ends_at is not None and session.ends_at is not None:
            return f"Quiet until {self._clock(session.phase_ends_at)}."
        return "Quiet until you say you're done."

    def state(self, member: Member) -> dict[str, Any]:
        """What the session page shows, as JSON. Never the energy level or any score."""
        now = clock.now()
        session = self.current(member)
        if session is None:
            return {"active": False, "now": to_utc_iso(now)}
        if session.mode == SPRINT and session.phase in ("work", "break"):
            ends = session.phase_ends_at or now
            timer = {"kind": "down", "to": to_utc_iso(ends), "text": _span(ends - now)}
        else:
            timer = {"kind": "up", "from": to_utc_iso(session.started_at)}
            timer["text"] = _span(now - session.started_at)
        steps: dict[str, Any] = {}
        if session.mode == GUIDED and self.guided is not None:
            all_steps = self.guided.steps(session)
            steps = {"step": session.row["step"] + 1, "of": len(all_steps)}
        return {
            "active": True,
            "scene": self.scene(session),
            "chat": self.page_chat(session) if session.phase == "break" else [],
            "id": session.id,
            "seq": session.seq,
            "mode": session.mode,
            "mode_name": MODE_NAMES[session.mode],
            "label": session.label,
            "part": self.part_words(session),
            "phase": session.phase,
            "line": self.page_line(session),
            "timer": timer,
            "now": to_utc_iso(now),
            **steps,
            **(self.pictures.page_state(session) if self.pictures is not None else {}),
            "music": self.music_state(member),
            "spotify": json.loads(session.row.get("playlists") or "[]"),  # F34i
            "buttons": [
                {"label": b.label, "action": b.payload.get("action", ""),
                 "mode": b.payload.get("mode", "")}
                for b in self.page_buttons(session)
            ],
        }  # fmt: skip

    def note_music(self, member: Member, music: str, name: str) -> None:
        """What's playing in the session going on ("builtin:rain", a Spotify uri), for
        BD5c's suggestions."""
        session = self.current(member)
        if session is not None:
            self.db.execute(
                "UPDATE body_double_sessions SET music = ?, music_name = ? WHERE id = ?",
                (music, name, session.id),
            )

    def music_state(self, member: Member) -> dict[str, Any]:
        """The page's built-in loop and volume (BD5a); it plays only when they tap play."""
        from themi.core.body_double_music import LOOPS

        prefs = self.store.preferences(member.id, BodyDoublePreferences)  # CR7a
        loop = LOOPS.get(prefs.body_double_sound) or LOOPS["lofi"]
        return {
            "sound": loop.key,
            "volume": prefs.body_double_volume,
            "file": loop.file,
            "loops": [{"key": k.key, "name": k.name, "file": k.file} for k in LOOPS.values()],
        }

    def scene(self, session: Session) -> str:
        """The chameleon's animation state now (BD3b)."""
        now = clock.now()
        if session.phase in ("work", "break") and session.phase_ends_at is not None:
            length = session.break_minutes if session.phase == "break" else session.work_minutes
            started = session.phase_ends_at - timedelta(minutes=length)
        else:
            started = session.started_at
        if session.mode == GUIDED and session.row.get("step_since"):
            started = datetime.fromisoformat(session.row["step_since"])
        return pick_state(
            mode=session.mode,
            category=session.category,
            phase=session.phase,
            now=now,
            phase_started=started,
            cheer_until=_when(session.row.get("cheer_until")),
            chat_at=_when(session.row.get("chat_at")),
        )

    def page_chat(self, session: Session) -> list[dict[str, str]]:
        """The conversation since the break began, as chat has it (BD3b's break chat)."""
        if session.phase_ends_at is None:
            return []
        since = session.phase_ends_at - timedelta(minutes=session.break_minutes)
        rows = self.db.query(  # message_log keeps the clock's own offset: compared as times
            "SELECT direction, text, created_at FROM message_log WHERE member_id = ? "
            "AND kind != ? ORDER BY id DESC LIMIT 40",
            (session.member_id, KIND),
        )
        return [
            {"who": "you" if r["direction"] == "in" else "themi", "text": r["text"]}
            for r in reversed(rows)
            if datetime.fromisoformat(r["created_at"]) >= since
        ][-20:]

    def page_chat_event(self, member: Member, text: str) -> Any:
        """A message typed on the page during a break, as an inbound chat message for the
        agent (the same path as Telegram, so replies go to Telegram and show on the page).
        None when there's no break going on."""
        from themi.channels.events import InboundEvent

        session = self.current(member)
        text = text.strip()[:4000]
        if session is None or session.phase != "break" or not text:
            return None
        if member.telegram_user_id is None:
            return None
        now = clock.now()
        self.db.execute(
            "UPDATE body_double_sessions SET chat_at = ? WHERE id = ?",
            (to_utc_iso(now), session.id),
        )
        self.store.log_message(member.id, "in", text, "chat", None)
        return InboundEvent("text", member, member.telegram_user_id, None, now, 0, text=text)

    async def act_from_page(
        self, member: Member, session_id: int, action: str, seq: int, mode: str = ""
    ) -> bool:
        """A tap on the page: the same as in chat, and the chat message shows it too.
        False when it's not theirs, over, or out of date."""
        session = self.get(session_id)
        if session is None or session.member_id != member.id or session.ended_at is not None:
            log.info("Session page tap %r on session %s refused: not theirs or over",
                     action, session_id)  # fmt: skip
            return False
        if seq != session.seq:
            log.info("Session page tap %r on session %s refused: seq %s, now %s",
                     action, session_id, seq, session.seq)  # fmt: skip
            return False
        log.info("Session page tap %r on session %s", action, session_id)
        target = session.row["card_message_id"]
        if session.phase == "asking" and session.ask_outbox_id is not None:
            target = self.services.outbox.message_id(session.ask_outbox_id) or target
        if action == "switch":
            new, text, buttons = await self.switch(member, mode)
            self.remember_message(new, target)
        else:
            text, buttons = await self.act(session, action)
            self._carry_message(session, member, target)
        if target is not None:
            await self.services.outbox.edit(member, target, text, buttons)
        return True

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
        result = await self.services.outbox.send(
            member, text, priority=Priority.REPLY, kind=KIND, buttons=buttons
        )
        session = self.current(member)
        if session is not None and result.outbox_id is not None:
            self.remember_message(session, self.services.outbox.message_id(result.outbox_id))

    def open_items(self, member: Member) -> list[Any]:
        from themi.core.prompts import OpenItem, as_data

        session = self.current(member)
        if session is None:
            return []
        what = as_data("their words", session.label) if session.task_id is None else ""
        task = f" (task {session.task_id})" if session.task_id is not None else ""
        if self.guided is not None and session.mode == GUIDED:
            task += self.guided.open_item_words(session)
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
    body_double = ctx.services.maybe(keys.body_double)
    if body_double is None:
        raise ToolFailed("Body double sessions aren't set up.")
    return body_double


def _mode_arg(value: Any) -> str:
    said = str(value or "").strip().lower()
    if said not in MODE_WORDS:
        raise ToolFailed("mode is '', 'quiet', 'sprint' or 'steps'.")
    return MODE_WORDS[said]


async def _send(
    ctx: ToolContext, text: str, buttons: list[Button], session: Session | None = None
) -> None:
    result = await ctx.services.outbox.send(
        ctx.member, text, priority=Priority.REPLY, kind=KIND, buttons=buttons
    )
    if session is not None and result.outbox_id is not None:
        message_id = ctx.services.outbox.message_id(result.outbox_id)
        _body_double(ctx).remember_message(session, message_id)


@tool(
    "start_body_double",
    "Keep them company while they do something, when they ask ('sit with me while I do the "
    "taxes', 'body double the dishes', 'pomodoro the laundry', 'keep me company while I "
    "write'). It's a session, never a new task: 'pomodoro X' is a sprint on X. mode: '' "
    "unless they said one; 'quiet' (quiet company), 'sprint' (pomodoro: work and break "
    "blocks) or 'steps' (one step at a time). minutes: how long they said, or 0. task_id: "
    "their open task it's for, or 0; what: their own words for it ('the bird cage', 'my evening "
    "routine'): a task or routine of theirs by that name is found, with its own steps. "
    "Pass the task or routine whenever there is one. then: what comes after it in the same "
    "session, in order, as 'task 12' or their words ('the laundry', 'my evening routine'); "
    "[] for one thing.",
    {
        "mode": {"type": "string", "enum": ["", "quiet", "sprint", "steps"]},
        "minutes": {"type": "integer"},
        "task_id": {"type": "integer"},
        "what": {"type": "string"},
        "then": {"type": "array", "items": {"type": "string"}},
    },
)
async def start_body_double(ctx: ToolContext, args: dict[str, Any]) -> str:
    body_double = _body_double(ctx)
    burnout = ctx.services.maybe(keys.burnout)
    if burnout is not None and burnout.current(ctx.member):
        raise ToolFailed(
            "Not started: burnout mode is on, and it comes first. Keep them company in words "
            "if they'd like; nothing to do is asked of them."
        )
    mode = _mode_arg(args.get("mode"))
    task, routine = None, None
    what = str(args.get("what") or "")
    if int(args.get("task_id") or 0):
        try:
            task = body_double.task_for(ctx.member, int(args["task_id"]))
        except ValueError as exc:
            raise ToolFailed(f"Not started: {exc}.") from exc
    else:  # F34h, bug #181: the model left task_id 0 and made steps up
        routine = body_double.find_routine(ctx.member, what)
        task = None if routine is not None else body_double.find_task(ctx.member, what)
    if routine is not None and not mode:
        mode = GUIDED  # a routine is its items, one at a time
    try:
        then = [body_double.resolve(ctx.member, str(w)) for w in args.get("then") or [] if w]
        session, text, buttons = await body_double.start(
            ctx.member,
            mode=mode,
            minutes=int(args.get("minutes") or 0),
            task=task,
            label=what,
            routine=routine,
            then=then,
        )
    except ValueError as exc:
        raise ToolFailed(f"Not started: {exc}.") from exc
    await _send(ctx, text, buttons, session)
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
        session, text, buttons = await _body_double(ctx).switch(ctx.member, mode or SILENT)
    except ValueError as exc:
        raise ToolDeclined(f"Not switched: {exc}.") from exc
    await _send(ctx, text, buttons, session)
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
        said, buttons = await body_double.finish_or_next(session)
        new = body_double.current(ctx.member)
        if new is not None:  # F34hb: the next part of the run started
            await _send(ctx, said, buttons, new)
            ctx.cards.append("body double next part")
            return f"Done, and the next part started; Themi told them itself: {said!r}"
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


class BodyDoubleModule(Module):
    """BD1a: body double sessions; block ends are scheduler jobs."""

    name = "body_double"
    tool_groups = (groups.BODY_DOUBLE,)
    preferences = BodyDoublePreferences

    def install(self, ctx: ModuleContext) -> None:
        ctx.settings_section("settings/body_double.html", 40)
        from themi.web import session_pages

        ctx.web(session_pages.routes)
        ctx.provide(BodyDouble(ctx.services, ctx.scheduler)).install()
