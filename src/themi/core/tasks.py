"""Household tasks: created in conversation, matched to whoever has room, nudged gently.

A new task is assigned by the matcher and announced to its assignee as a
two-option message ("done already, or later?") that waits for their good
window, or goes by the due date's morning at the latest. "Later" snoozes it
for a few hours, after which it's offered again. The model gets the reason
for the assignment in words, so it can say who's taking what and why.

Every change (created, rescheduled, done, cancelled) goes to
`change_listeners`; the family calendar follows tasks that way.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member, NotFound, PermissionDenied
from themi.autonomy import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Outbox, Priority
from themi.core import praise
from themi.core.events import title_matches, words_in_common
from themi.core.progression import Progression, parse_plan
from themi.core.progression import read_back as plan_read_back
from themi.core.prompts import OpenItem
from themi.core.repeat import (
    Repeat,
    next_occurrences,
    parse,
    previous_occurrence,
    read_back,
    round_end,
)
from themi.core.services import Services
from themi.core.sun import sunset
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.energy.matching import Assignment, Matcher
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

# Rx1 (Erin's idea #48): a medicine task. Its nudge offers [Not sure], which never makes it
# done, and Themi never advises on doses.
MEDICINE = re.compile(
    r"\b(?:pills?|meds|medicines?|medications?|wegovy|ozempic|insulin|inhalers?|tablets?|"
    r"capsules?|prescriptions?|doses?|tabs?)\b",
    re.IGNORECASE,
)
MEDICINE_ASK = "Taken already, or later?"
NOT_SURE_TEXT = (
    "Not sure is okay. The safe way is no second dose until it's checked (a pill box, the "
    "pen, the pharmacy's record), or until the doctor or pharmacist says. It stays open here."
)
UNSURE = re.compile(
    r"\b(?:not sure|unsure|don'?t (?:remember|recall|know)|can'?t (?:remember|recall)|"
    r"no idea|forgot (?:if|whether)|maybe|might have|think i (?:took|did|had))\b",
    re.IGNORECASE,
)
# "Didn't I just clean the bird cage?" asks; it doesn't say it's done (#92).
QUESTION = re.compile(
    r"\?\s*$|^\s*(?:did|didn[\u2019']?t|have|haven[\u2019']?t|has|hasn[\u2019']?t|when|was|wasn[\u2019']?t)\b",
    re.IGNORECASE,
)
SAYS_DONE = re.compile(  # ...unless it says so too ("done, what's next?", "can you mark it")
    r"^\s*(?:done|all done|did it|i did|finished|yes|yep|yeah)\b|"
    r"\b(?:mark|tick|check (?:it |that )?off|cross (?:it |that )?off|log|note)\b",
    re.IGNORECASE,
)
SHORT_ANSWER = 3  # words or fewer ("Yes please"): read with what Themi asked before it
# "no" to "Walk dog... Done already?" marked eight other tasks done (#97).
NOT_DONE = frozenset(
    {"no", "n", "nope", "nah", "not yet", "not done", "not today", "no not yet", "nope not yet"}
)
_RELATIVE_DAY = re.compile(
    r"\b(?:today|tonight|yesterday|tomorrow|this (?:morning|afternoon|evening))\b",
    re.IGNORECASE,
)
ALL_OF_THEM = re.compile(r"\b(?:all|everything|every one|both)\b", re.IGNORECASE)


def is_medicine(title: str) -> bool:
    """A medicine, from the title's words ("Take Wegovy", "Mimi pill - 1 tab")."""
    return bool(MEDICINE.search(title))


SNOOZE_FOR = timedelta(hours=4)


class Keep:
    """An argument left as it is (a time that isn't changing)."""


KEEP = Keep()
# One task nudge at a time (idea #11): the next waits while one is unanswered, this long.
ONE_AT_A_TIME_FOR = timedelta(hours=2)
# A task someone just added for themselves in chat isn't asked about straight away.
FIRST_NUDGE_AFTER = timedelta(hours=4)
TASK_KINDS = ["text", "call", "physical", "errand"]
# Every nudge opens with a label: when it's due, "To do" without a date, or "Check-in"
# (Erin's rules 6-8, bug #9). Titles are often commands ("Call the vet"), so they never
# open a sentence; the label comes first.
NUDGE_LEAD = "{label}: {title}{who}{whenever}"
WHENEVER = ", whenever it suits"  # gentle phrasing only (idea #12)
# When someone else added it, the nudge says who, so it doesn't arrive out of nowhere.
ADDED_BY = " ({who} added this for you)"
# Repeating chores (F6b).
OVERDUE_TEXT = "Overdue: {title} (last done {ago})"
SHARED_OVERDUE_TEXT = "Overdue for both of you: {title} (last done {ago})"
NEXT_ROUND_TEXT = " Next round: {when}."
STEP_UP_CATEGORY = "chore_step_up"
STEP_UP_EXECUTOR = "tasks.step_up"
MISSED = ("roll", "catch_up", "next_day")  # what happens to a round that passes undone
IMPORTANCE = ("low", "normal", "high")  # how often an overdue task is raised (C2c)
URGENT_WORDS = re.compile(r"\b(?:urgent|urgently|asap|right away|straight away)\b")
BOTH_WORDS = ("both", "either", "either of us", "one of us", "both of us")
OTHER_WORDS = ("someone else", "somebody else", "the other one", "not me", "my partner")
STEP_UP_AFTER = 6  # on-time runs in a row before offering to go more often
DONE_TEXT = "Marked done: {title}. Thank you."
SETTLE_WITHIN = timedelta(hours=36)  # sent nudges that stop asking once it's done elsewhere
LAST_ROUND_TEXT = " That was the last one."
MORNING_LIST_TEXT = "This morning:\n{items}\nTap any that are done; the rest can wait."
MORNING_LIST_DONE = "This morning's list: all done."
MORNING_LIST_WITHIN = timedelta(minutes=45)  # after quiet hours end: the morning list
MORNING_LIST_BUTTONS = 6
TOO_MUCH = "Too much today"
LATER_TEXT = "No rush on that one ({title}). It'll come back around in a few hours."
UNTIL_TEXT = "No rush on that one ({title}). It waits until {when}."
# F19c: a shared task put off by one of them, for them alone.
YOURS_UNTIL_TEXT = "No rush on that one ({title}). It waits for you until {when}."
YOURS_LATER_TEXT = "No rush on that one ({title}). It'll come back to you in a few hours."
STILL_ON_TEXT = " It's still on {whose} list."
BOTH_MOVED_TEXT = " That's for both of you."
SETTLED_TEXT = "That one's already settled."
CANCELLED_TEXT = "Taken off the list: {title}."
RESCHEDULED_TEXT = "{title} is now due {due}."
UNSCHEDULED_TEXT = "{title} no longer has a date."


@dataclass(frozen=True)
class Done:
    """A task, or a round of one, done at a moment (by someone, for a repeating one)."""

    task: Task
    at: datetime
    by: int | None


@dataclass(frozen=True)
class Task:
    id: int
    title: str
    kind: str
    effort: int
    assignee: int | None
    default_owner: int | None
    assign_reason: str
    status: str
    due_on: date | None
    created_by: int | None = None
    steps: tuple[str, ...] = ()  # in the person's words; tags like "(Optional/Bonus)" included
    # A repeating chore's schedule (F6b); None when it doesn't repeat.
    times_per_week: float | None = None
    minimum_days: float | None = None  # overdue after this many days
    escalate_days: float | None = None  # escalated after this many days
    escalate_to: str | None = None  # "owner" or "both"
    shared: bool = False  # escalated to both: on everyone's list, anyone can do it
    # Anchored schedules (F7): fixed dates. Floating ones stay in times_per_week.
    repeat: Repeat | None = None
    missed: str = "roll"  # a missed anchored round: "roll" on, "catch_up", or "next_day"
    due_before_task: int | None = None  # due the day before that chore's round
    check_in: bool = False  # "did you...?": the nudge is labelled "Check-in:"
    either: bool = False  # a chore either of you can do, every round (on both lists)
    importance: str = "normal"  # low, normal or high: how often an overdue one is raised (C2c)
    due_time: time | None = None  # a time of day on the due date ("today around 2")
    from_time: time | None = None  # a window's start ("between 2 and 3"): the nudge comes then
    on_chart: bool = False  # a one-off on the wall's chore chart, not its to-do list (C2b)
    progression: Progression | None = None  # an amount that steps up weekly (F9c)
    off_wall: bool = False  # Themi's own (the email audit): never on the wall's to-do lists
    medicine: bool = False  # Rx1: "not sure" never makes it done

    @property
    def repeats(self) -> bool:
        return bool(self.times_per_week or self.repeat or self.due_before_task)


@dataclass(frozen=True)
class Run:
    done_by: int | None
    done_at: datetime
    due_on: date | None
    on_time: bool
    missed: bool = False  # a round that passed without anyone doing it


# "created", "rescheduled", "done", "cancelled", "reassigned", "reopened" or "moved"
TaskChange = str
# (task as it is now, what changed, whether whoever caused it is in the conversation)
TaskListener = Callable[[Task, TaskChange, bool], Awaitable[None]]
DoneHook = Callable[[Task, Member, bool], Awaitable[None]]
# Sends a task's nudge its own way (task, member, not_before, deadline); True if it did.
OwnNudge = Callable[[Task, Member, datetime | None, datetime | None], Awaitable[bool]]
# Extra text to send with a task's nudge (a call script, say), or None.
TaskDetails = Callable[[Task], str | None]


def _task_from_row(row: dict[str, Any]) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        kind=row["kind"],
        effort=row["effort"],
        assignee=row["assignee"],
        default_owner=row["default_owner"],
        assign_reason=row["assign_reason"],
        status=row["status"],
        due_on=date.fromisoformat(row["due_on"]) if row["due_on"] else None,
        created_by=row["created_by"],
        steps=tuple(json.loads(row["steps"])),
        times_per_week=row["times_per_week"],
        minimum_days=row["minimum_days"],
        escalate_days=row["escalate_days"],
        escalate_to=row["escalate_to"],
        shared=bool(row["shared"]),
        repeat=Repeat.from_json(json.loads(row["repeat"])) if row["repeat"] else None,
        missed="next_day" if row["missed_next_day"] else row["missed"],
        due_before_task=row["due_before_task"],
        check_in=bool(row["check_in"]),
        either=bool(row["either"]),
        importance=row["importance"],
        due_time=time.fromisoformat(row["due_time"]) if row["due_time"] else None,
        from_time=time.fromisoformat(row["from_time"]) if row["from_time"] else None,
        on_chart=bool(row["on_chart"]),
        progression=(
            Progression.from_json(json.loads(row["progression"])) if row["progression"] else None
        ),
        off_wall=bool(row["off_wall"]),
        medicine=bool(row["medicine"]),
    )


MAX_STEPS = 30
MAX_STEP_LENGTH = 200


def clean_steps(steps: Sequence[str]) -> list[str]:
    """Steps as given, trimmed, blanks dropped. The wording is the person's: never rewritten."""
    cleaned = [" ".join(str(s).split()) for s in steps]
    cleaned = [s.lstrip("-• ").strip() for s in cleaned]
    cleaned = [s for s in cleaned if s]
    if len(cleaned) > MAX_STEPS:
        raise ValueError(f"a task can have at most {MAX_STEPS} steps")
    if any(len(s) > MAX_STEP_LENGTH for s in cleaned):
        raise ValueError(f"each step can be at most {MAX_STEP_LENGTH} characters")
    return cleaned


class TaskBoard:
    def __init__(self, services: Services, matcher: Matcher) -> None:
        self.services = services
        self.matcher = matcher
        self.store = services.store
        self.db = services.store.db
        self.change_listeners: list[TaskListener] = []
        self.details: list[TaskDetails] = []  # steps come first, from _steps_for
        self.own_nudges: list[OwnNudge] = []
        # Where a task is on the Cozyla wall, for the model ("Shows on the wall's chore chart
        # on Sunday 1 Nov."), so it answers with the day rather than guessing.
        self.wall_notes: list[Callable[[Task], str | None]] = []
        # Chores waiting their turn for someone's chart (C2d): no nudges to them meanwhile.
        self.holds: list[Callable[[Task, Member], bool]] = []
        # Called each time a task is done (a repeating one, each round): (task, by whom,
        # whether they're in the conversation). F17b's follow-ups.
        self.done_hooks: list[DoneHook] = []
        self._pending_prompts: list[int] = []

    @property
    def outbox(self) -> Outbox:
        return self.services.outbox

    def install(self) -> None:
        s = self.services
        s.taskboard = self
        s.tools.register(create_task)
        s.tools.register(complete_task)
        s.tools.register(set_task_medicine)
        s.tools.register(cancel_task)
        s.tools.register(reschedule_task)
        s.tools.register(snooze_task)
        s.tools.register(update_task)
        s.tools.register(set_task_schedule)
        s.tools.register(set_task_plan)
        s.button_handlers["task"] = self.on_button
        s.open_item_sources.append(self.open_items)
        s.autonomy.executors.register(STEP_UP_EXECUTOR)(self._step_up)
        self.outbox.gates["task"] = self._one_at_a_time
        self.outbox.orders["task"] = self._nudge_order
        self.outbox.bundlers["task"] = self._morning_list
        praise.install(self.outbox)

    def _one_at_a_time(self, member: Member, when: datetime) -> datetime | None:
        """While a task nudge sent to this person is unanswered (still open, not put off),
        the next waits, for up to two hours (idea #11)."""
        row = self.db.one(
            "SELECT MAX(o.sent_at) AS sent_at FROM tasks t "
            "JOIN outbox o ON o.id = t.prompt_outbox_id WHERE o.member_id = ? "
            "AND o.status = 'sent' AND t.status = 'open' AND o.sent_at > ?",
            (member.id, to_utc_iso(when - ONE_AT_A_TIME_FOR)),
        )
        if row is None or row["sent_at"] is None:
            return None
        return datetime.fromisoformat(row["sent_at"]) + ONE_AT_A_TIME_FOR

    def _nudge_order(self, row: dict[str, Any]) -> tuple[Any, ...]:
        """Which waiting task nudge goes first (T1, Erin's idea #44)."""
        from themi.core import priority

        task_id = str(row.get("dedupe_key") or "").split("-")
        if len(task_id) < 2 or not task_id[1].isdigit():
            return (9,)
        found = self.db.one(
            "SELECT t.created_at, (SELECT MAX(done_at) FROM task_runs WHERE task_id = t.id) "
            "AS last_done FROM tasks t WHERE t.id = ?",
            (int(task_id[1]),),
        )
        if found is None:
            return (9,)
        since = datetime.fromisoformat(found["last_done"] or found["created_at"])
        return priority.rank(self.get(int(task_id[1])), self._today(), since, clock.now())

    # ----- reading ------------------------------------------------------------

    def held(self, task: Task, member: Member) -> bool:
        """Waiting its turn for this person's chore chart, so not raised with them."""
        return any(hold(task, member) for hold in self.holds)

    def get(self, task_id: int) -> Task:
        row = self.db.one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise NotFound(f"no task with id {task_id}")
        return _task_from_row(row)

    def open_for(self, member: Member) -> list[Task]:
        rows = self.db.query(  # shared (escalated to both) chores come first, for everyone
            "SELECT * FROM tasks WHERE (assignee = ? OR shared = 1) "
            "AND status IN ('open', 'snoozed') ORDER BY shared DESC, due_on IS NULL, due_on, id",
            (member.id,),
        )
        return [_task_from_row(r) for r in rows]

    def runs(self, task_id: int) -> list[Run]:
        rows = self.db.query(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY done_at, id", (task_id,)
        )
        return [
            Run(
                r["done_by"],
                datetime.fromisoformat(r["done_at"]),
                date.fromisoformat(r["due_on"]) if r["due_on"] else None,
                bool(r["on_time"]),
                bool(r["missed"]),
            )
            for r in rows
        ]

    def done_between(self, member: Member, start: datetime, end: datetime) -> list[Done]:
        """What was done in [start, end) on this person's list, soonest first: one-off
        tasks, and each round of a repeating one (bug #105: "what happened yesterday?")."""
        span = (to_utc_iso(start), to_utc_iso(end))
        rows = self.db.query(
            "SELECT t.*, r.done_at AS at, r.done_by AS by FROM task_runs r "
            "JOIN tasks t ON t.id = r.task_id WHERE r.missed = 0 AND r.done_at >= ? "
            "AND r.done_at < ? AND (r.done_by = ? OR t.assignee = ? OR t.shared = 1) "
            "UNION ALL SELECT t.*, t.completed_at AS at, NULL AS by FROM tasks t "
            "WHERE t.status = 'done' AND t.completed_at >= ? AND t.completed_at < ? "
            "AND (t.assignee = ? OR t.shared = 1) "
            "AND NOT EXISTS (SELECT 1 FROM task_runs r WHERE r.task_id = t.id) ORDER BY at",
            (*span, member.id, member.id, *span, member.id),
        )
        return [Done(_task_from_row(r), datetime.fromisoformat(r["at"]), r["by"]) for r in rows]

    def added_by(self, member: Member) -> list[Task]:
        """Open tasks this member added, whoever is doing them."""
        rows = self.db.query(
            "SELECT * FROM tasks WHERE created_by = ? AND status IN ('open', 'snoozed') "
            "ORDER BY due_on IS NULL, due_on, id",
            (member.id,),
        )
        return [_task_from_row(r) for r in rows]

    def open_items(self, member: Member) -> list[OpenItem]:
        from themi.core import priority

        items, today = [], self._today()
        for t in self.open_for(member):
            due = f", due {_day_words(t.due_on, today)}" if t.due_on else ""  # weekday (#64)
            if t.either:
                whose = "either of you"
            elif t.shared:
                whose = "shared, overdue: either of you"
            else:
                whose = "theirs"
            steps = f" Steps: {'; '.join(t.steps)}" if t.steps else ""
            if any(_step_level(step) for step in t.steps):
                level = self.services.energy.suggested_level(member)
                if level is not None:
                    steps += (
                        f" Suggested today: the {_LEVEL_WORD[level]} ({level.title()}) version."
                    )
            schedule = f" {self.summary(t)}." if t.repeats else ""
            if t.repeats and (last := self._last_done(t)) is not None:
                # Bug #64: without it, the model guessed a run "was missed".
                schedule += f" Last done {last.astimezone(self._tz()):%a %d %b}."
            if t.progression is not None:
                week = t.progression.words_on(self._today())
                schedule += f" Plan: {plan_read_back(t.progression)}" + (
                    f"; {week}." if week else "."
                )
            wall = "".join(f" {note}" for source in self.wall_notes if (note := source(t)))
            matters = priority.words(t, today)  # T1: in words, never a score
            matters = f", {matters}" if matters else ""
            if t.medicine:
                matters += ", medicine"
            items.append(
                OpenItem(f"Task {t.id} ({whose}{due}{matters}): {t.title}.{schedule}{wall}{steps}")
            )
        return items

    # ----- changing -----------------------------------------------------------

    async def create(
        self,
        requester: Member,
        title: str,
        kind: str,
        effort: int,
        due_on: date | None = None,
        *,
        interactive: bool = False,
        nudge: bool = True,
        assignee: Member | None = None,
        steps: Sequence[str] = (),
        check_in: bool = False,
        due_time: time | None = None,
        from_time: time | None = None,
        importance: str = "normal",
        off_wall: bool = False,
    ) -> Task:
        """Add and assign a task. With `nudge=False` the caller sends `prompt()` itself
        (after attaching details, like a call script). An `assignee` (someone took it on,
        or was named) skips matching; without one, matching decides."""
        title = title.strip().rstrip(".")
        if not title:
            raise ValueError("a task needs a title")
        if importance not in IMPORTANCE:
            raise ValueError("importance is low, normal or high")
        cleaned_steps = clean_steps(steps)
        if assignee is None:
            assignment = self.matcher.assign(kind, effort, requester)
        elif assignee.id == requester.id:
            assignment = Assignment(assignee, assignee, f"{requester.name} said they'd do it.")
        else:
            assignment = Assignment(
                assignee, assignee, f"{requester.name} asked for {assignee.name} to do it."
            )
        task_id = self.db.execute(
            "INSERT INTO tasks (title, kind, effort, created_by, default_owner, assignee, "
            "assign_reason, due_on, created_at, steps, check_in, due_time, from_time, "
            "importance, off_wall, medicine) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                kind,
                effort,
                requester.id,
                assignment.default_owner.id,
                assignment.assignee.id,
                assignment.reason,
                due_on.isoformat() if due_on else None,
                to_utc_iso(clock.now()),
                json.dumps(cleaned_steps),
                int(check_in),
                due_time.strftime("%H:%M") if due_on and due_time else None,
                from_time.strftime("%H:%M") if due_on and from_time else None,
                importance,
                int(off_wall),
                int(is_medicine(title)),
            ),
        )
        if nudge:
            task = self.get(task_id)
            if task.due_on is not None:
                # Nothing is asked about before it's due (bug #14): its day, or its time.
                not_before = self._round_starts(task)
            elif interactive and assignment.assignee.id == requester.id:
                # They just said it themselves: an instant "done already, or later?" is noise.
                not_before = clock.now() + FIRST_NUDGE_AFTER
            else:
                not_before = None
            await self.prompt(task, not_before=not_before)
        task = self.get(task_id)
        await self._changed(task, "created", interactive)
        return task

    async def _changed(self, task: Task, change: TaskChange, interactive: bool) -> None:
        for listener in self.change_listeners:
            try:
                await listener(task, change, interactive)
            except Exception:
                log.exception("A task listener failed for task %s (%s)", task.id, change)

    async def prompt(
        self,
        task: Task,
        *,
        not_before: datetime | None = None,
        member: Member | None = None,
        overdue: str | None = None,
        priority: Priority = Priority.NORMAL,
        lead: str | None = None,
    ) -> None:
        """Nudge whoever does the task (or `member`). `overdue`: "own" or "shared" wording.
        `priority` LOW lets a batch of nudges trickle out in good moments. `lead` replaces
        the opening line (an overdue reminder's, C2c)."""
        if task.assignee is None and member is None:
            return
        if not_before is None and overdue is None and lead is None:
            starts = self._round_starts(task)  # nothing is asked about before it's due (#14)
            if starts is not None and starts > clock.now():
                not_before = starts
        deadline = self._deadline(task)
        if not_before is not None and deadline is not None:
            not_before = min(not_before, deadline)  # a due date still wins
        if member is None:
            assert task.assignee is not None
            member = self.store.get_member(task.assignee)
        if self.held(task, member):
            return  # it gets its nudge when it comes up on the chart
        if self._own_snooze(task, member) is not None:
            return  # they put it off themselves (F19c): asked again when that runs out
        for own in self.own_nudges:  # a task with its own kind of nudge (E2's email audit)
            if await own(task, member, not_before, deadline):
                return
        parts = [self._steps_for(task, member), *(source(task) for source in self.details)]
        details = "\n\n".join(d for d in parts if d)
        added_by = (
            self.store.get_member(task.created_by)
            if task.created_by is not None and task.created_by != member.id
            else None
        )
        goes_out = self.outbox.send_time(
            member, priority, deadline=deadline, kind="task", not_before=not_before
        )
        family = self.store.get_family()
        local_day = goes_out.astimezone(ZoneInfo(family.timezone if family else "UTC")).date()
        week = task.progression.words_on(local_day) if task.progression else None
        title = f"{task.title} ({week})" if week else task.title  # "(1.3 miles this week)"
        if lead is None and overdue is not None:
            template = SHARED_OVERDUE_TEXT if overdue == "shared" else OVERDUE_TEXT
            lead = template.format(title=title, ago=self._last_done_words(task))
        elif lead is None:
            lead = NUDGE_LEAD.format(
                label=_label(task, local_day),
                title=title,
                who=ADDED_BY.format(who=added_by.name) if added_by is not None else "",
                whenever=(
                    WHENEVER
                    if task.due_on is None and not task.check_in and member.phrasing == "gentle"
                    else ""
                ),
            )
        ask = MEDICINE_ASK if task.medicine else "Done already, or later?"
        text = f"{lead}.\n\n{details}\n\n{ask}" if details else f"{lead}. {ask}"
        for queued in self.db.query(  # one nudge per task waiting for them (bug #49)
            "SELECT id FROM outbox WHERE status = 'queued' AND member_id = ? AND dedupe_key LIKE ?",
            (member.id, f"task-{task.id}-%"),
        ):
            self.outbox.cancel(queued["id"])
        result = await self.outbox.send(
            member,
            text,
            priority=priority,
            kind="task",
            buttons=[
                Button(
                    "Taken" if task.medicine else "Done",
                    "task",
                    {"task": task.id, "action": "done"},
                ),
                *(
                    [Button("Not sure", "task", {"task": task.id, "action": "not_sure"})]
                    if task.medicine
                    else []
                ),
                Button("Later", "task", {"task": task.id, "action": "later"}),
            ],
            deadline=deadline,
            not_before=not_before,
            dedupe_key=f"task-{task.id}-{secrets.token_hex(4)}",  # tags it, for withdrawing
        )
        if result.outbox_id is not None:
            self.db.execute(
                "UPDATE tasks SET prompt_outbox_id = ? WHERE id = ?", (result.outbox_id, task.id)
            )

    async def _morning_list(self, member: Member, rows: list[dict[str, Any]]) -> bool:
        """Bug #49: when quiet hours end with several task nudges waiting, they go as one
        list, a button per task, instead of one after another. Later in the day they keep
        coming one at a time (idea #11)."""
        tz = self._tz()
        now = clock.now()
        local = now.astimezone(tz)
        end = member.quiet_end
        woke = datetime(local.year, local.month, local.day, end.hour, end.minute, tzinfo=tz)
        if not woke <= local < woke + MORNING_LIST_WITHIN:
            return False
        tasks: list[Task] = []
        seen: set[int] = set()
        for row in rows:  # already in their order (T1)
            task_id = _task_id(row)
            task = self.get(task_id) if task_id is not None else None
            if task is not None and task.status == "open" and task.id not in seen:
                seen.add(task.id)
                tasks.append(task)
        if len(tasks) < 2:
            return False
        text, buttons = self._list_message(tasks, local.date())
        result = await self.outbox.send(
            member,
            text,
            priority=Priority.NORMAL,
            kind="task_summary",
            buttons=buttons,
            deadline=now,
            dedupe_key=f"morning-list-{member.id}-{local.date().isoformat()}",
        )
        if result.outbox_id is None:
            return False
        for row in rows:
            self.outbox.cancel(row["id"])
        for task in tasks:  # the list is their nudge: the next one waits its turn after it
            self.db.execute(
                "UPDATE tasks SET prompt_outbox_id = ? WHERE id = ?", (result.outbox_id, task.id)
            )
        return True

    def _list_message(self, tasks: list[Task], today: date) -> tuple[str, list[Button]]:
        ids = [t.id for t in tasks]
        lines = "\n".join(f"- {_label(t, today)}: {t.title}" for t in tasks)
        buttons = [
            Button(
                f"✓ {_short(t.title)}", "task", {"task": t.id, "action": "list_done", "list": ids}
            )
            for t in tasks[:MORNING_LIST_BUTTONS]
        ]
        buttons.append(Button(TOO_MUCH, "focus", {"action": "focus"}))  # O1a, Erin's idea #94
        return MORNING_LIST_TEXT.format(items=lines), buttons

    async def _list_done(self, event: InboundEvent) -> None:
        """A tick on the morning list: that one's done, said so (bug #103: the line only went
        away, and the wall was slow, so was it done?), and the list shows the rest."""
        assert event.button is not None
        task_id = int(event.button.payload["task"])
        ticked = await self.complete(
            task_id, event.member, interactive=True, tapped=event.button.message_id
        )
        if event.button.message_id is None:
            return
        left = []
        for task_id in event.button.payload.get("list", []):
            try:
                task = self.get(int(task_id))
            except NotFound:
                continue
            if task.status == "open":
                left.append(task)
        if not left:
            done = f"{ticked} {MORNING_LIST_DONE}"
            await self.outbox.edit(event.member, event.button.message_id, done)
            return
        text, buttons = self._list_message(left, self._today())
        await self.outbox.edit(
            event.member, event.button.message_id, f"{ticked}\n\n{text}", buttons
        )

    def _deadline(self, task: Task) -> datetime | None:
        """By when a nudge should go out: its time on the due date (the task's, or the
        chore's), else 9 am."""
        if task.due_on is None:
            return None
        return _on(task.due_on, self.time_of(task) or time(9), self._tz())

    def time_of(self, task: Task, day: date | None = None) -> time | None:
        """When its nudge comes: a window's start, else its time, else the chore's (F9b: by
        sunset at home that day, or the earlier of its time and that)."""
        if task.from_time or task.due_time:
            return task.from_time or task.due_time
        if task.repeat is None:
            return None
        if task.repeat.before_sunset is None:
            return task.repeat.at
        by_sunset = self.sunset_time(day or task.due_on or self._today(), task.repeat.before_sunset)
        if by_sunset is None:
            return task.repeat.at  # no home on the map yet: its own time, if it has one
        return min(task.repeat.at, by_sunset) if task.repeat.at else by_sunset

    def sunset_time(self, day: date, before: int) -> time | None:
        """`before` minutes before sunset at home on `day`, on the five minutes."""
        home = self.db.one("SELECT lat, lon FROM family_home WHERE id = 1")
        if home is None:
            return None
        down = sunset(day, home["lat"], home["lon"], self._tz())
        if down is None:
            return None
        moment = down - timedelta(minutes=before)
        return time(moment.hour, moment.minute - moment.minute % 5)

    def _tz(self) -> ZoneInfo:
        family = self.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")

    def _round_starts(self, task: Task) -> datetime | None:
        """When this round's nudge may go: the chore's time on its due date, or that morning."""
        if task.due_on is None:
            return None
        at = self.time_of(task)
        return _on(task.due_on, at, self._tz()) if at else self._day_start(task.due_on)

    def _steps_for(self, task: Task, member: Member) -> str | None:
        """The steps for a nudge. With (Low)/(Medium)/(High) tags, only the level that suits
        the person today (each level takes in the ones below it), in words (S4)."""
        if not task.steps:
            return None
        levels = [_step_level(step) for step in task.steps]
        if not any(levels):
            return _quoted(task.steps)
        level = self.services.energy.suggested_level(member)
        if level is None:
            return _quoted(task.steps)
        keep = [
            step
            for step, tag in zip(task.steps, levels, strict=True)
            if tag is None or _LEVEL_ORDER[tag] <= _LEVEL_ORDER[level]
        ]
        lines = [_LEVEL_LEAD[level], _quoted(keep)]
        if any(tag and _LEVEL_ORDER[tag] > _LEVEL_ORDER[level] for tag in levels):
            lines.append("The rest is there too if you feel like more.")
        return "\n".join(lines)

    def can_edit(self, task: Task, member: Member) -> bool:
        return member.is_admin or member.id in (task.assignee, task.created_by)

    async def update(
        self,
        task_id: int,
        by: Member,
        *,
        title: str | None = None,
        steps: Sequence[str] | None = None,
        interactive: bool = False,
    ) -> Task:
        """Rename a task or replace its steps. The assignee, whoever added it, or an admin."""
        task = self.get(task_id)
        if not self.can_edit(task, by):
            raise PermissionDenied("only the person doing it, whoever added it, or an admin")
        changes: dict[str, Any] = {}
        if title is not None and title.strip().rstrip("."):
            changes["title"] = title.strip().rstrip(".")
        if steps is not None:
            changes["steps"] = json.dumps(clean_steps(steps))
        if changes:
            assignments = ", ".join(f"{c} = :{c}" for c in changes)
            self.db.execute(
                f"UPDATE tasks SET {assignments} WHERE id = :id", {**changes, "id": task_id}
            )
            await self._changed(self.get(task_id), "edited", interactive)
        return self.get(task_id)

    async def complete(
        self,
        task_id: int,
        by: Member,
        *,
        interactive: bool = False,
        tapped: int | None = None,
        wall: bool = False,
    ) -> str:
        """Mark it done (a repeating one: this round). `tapped`: the message whose Done
        button did it, which the caller edits itself. `wall`: ticked on the wall by `by`
        (the wall said who), who hears a warm word for it (F19b)."""
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        self._end_own_snoozes(task.id)
        await self._settle_sent(task, tapped)
        if task.repeats:
            said = await self._complete_round(task, by, interactive)
        else:
            self.db.execute(
                "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), task_id),
            )
            self.withdraw_prompt(task)
            await self._changed(self.get(task_id), "done", interactive)
            said = DONE_TEXT.format(title=task.title)
        thanks = DONE_TEXT.format(title=task.title)
        if interactive and by.done_praise and said.startswith(thanks):
            said = thanks.removesuffix("Thank you.") + _praise(task) + said.removeprefix(thanks)
        if wall:
            await praise.from_wall(self.outbox, by, task.title, str(task.id))
        for hook in self.done_hooks:  # each time it's done, a repeating one's every round
            try:
                await hook(task, by, interactive)
            except Exception:
                log.exception("A done hook failed for task %s", task.id)
        return said

    async def _settle_sent(self, task: Task, tapped: int | None) -> None:
        """Its nudges already sent stop asking once it's done some other way (bug #40: ticked
        on the wall, the check-in kept its Done and Later buttons)."""
        rows = self.db.query(
            "SELECT member_id, telegram_message_id FROM outbox WHERE status = 'sent' "
            "AND dedupe_key LIKE ? AND sent_at >= ? AND telegram_message_id IS NOT NULL",
            (f"task-{task.id}-%", to_utc_iso(clock.now() - SETTLE_WITHIN)),
        )
        for row in rows:
            if row["telegram_message_id"] != tapped:
                member = self.store.get_member(row["member_id"])
                await self.outbox.edit(
                    member, row["telegram_message_id"], DONE_TEXT.format(title=task.title)
                )

    async def reassign(self, task_id: int, member: Member | None, *, shared: bool = False) -> Task:
        """Give a one-off task to someone else, or to both of you (`shared`: on everyone's
        list, either can do it). The nudge goes to whoever has it now."""
        task = self.get(task_id)
        if task.status not in ("open", "snoozed"):
            return task
        assignee = member.id if member is not None else task.assignee
        if (assignee, shared) == (task.assignee, task.shared):
            return task
        self.db.execute(
            "UPDATE tasks SET assignee = ?, shared = ? WHERE id = ?",
            (assignee, int(shared), task_id),
        )
        self.withdraw_prompt(task)
        task = self.get(task_id)
        people = (
            [m for m in self.store.list_members() if m.telegram_user_id is not None]
            if shared
            else [self.store.get_member(assignee)]
            if assignee is not None
            else []
        )
        for person in people:
            await self.prompt(task, member=person)
        await self._changed(task, "reassigned", False)
        return task

    def whose_list(self, task: Task) -> str:
        """Whose list a task is on, in words (bug #97): "Erin's list", or "both lists"."""
        if task.shared:
            return "both lists"
        if task.assignee is None:
            return "nobody's list yet"
        return f"{self.store.get_member(task.assignee).name}'s list"

    async def put_on_chart(self, task_id: int, by: Member, on: bool = True) -> Task:
        """Put a one-off task on the wall's chore chart (or take it off, back to the to-do
        list). Repeating chores are always on the chart."""
        task = self.get(task_id)
        if not self.can_edit(task, by):
            raise PermissionDenied("only the person doing it, whoever added it, or an admin")
        self.db.execute("UPDATE tasks SET on_chart = ? WHERE id = ?", (int(on), task_id))
        task = self.get(task_id)
        await self._changed(task, "moved", True)
        return task

    async def reopen(self, task_id: int) -> Task:
        """A one-off task marked done that turns out not to be: open again, and nudged."""
        task = self.get(task_id)
        if task.status != "done" or task.repeats:
            return task
        self.db.execute(
            "UPDATE tasks SET status = 'open', completed_at = NULL WHERE id = ?", (task_id,)
        )
        task = self.get(task_id)
        await self.prompt(task)
        await self._changed(task, "reopened", False)
        return task

    # ----- repeating chores (F6b) ------------------------------------------------

    def _today(self) -> date:
        family = self.store.get_family()
        return clock.now().astimezone(ZoneInfo(family.timezone if family else "UTC")).date()

    def _day_start(self, day: date) -> datetime:
        family = self.store.get_family()
        tz = ZoneInfo(family.timezone if family else "UTC")
        return datetime(day.year, day.month, day.day, tzinfo=tz)

    def _last_done(self, task: Task) -> datetime | None:
        value = self.db.scalar(
            "SELECT MAX(done_at) FROM task_runs WHERE task_id = ? AND missed = 0", (task.id,)
        )
        return datetime.fromisoformat(value) if value else None

    def _last_done_words(self, task: Task) -> str:
        last = self._last_done(task)
        if last is None:
            return "not yet"
        days = int((clock.now() - last) / timedelta(days=1))
        return "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"

    async def set_schedule(
        self,
        task_id: int,
        by: Member,
        *,
        repeat: Repeat | None,
        minimum_days: float = 0,
        escalate_days: float = 0,
        escalate_to: str = "owner",
        missed: str = "roll",
        due_before_task: int | None = None,
        either: bool = False,
    ) -> Task:
        """Give a task a schedule, or take it away (no `repeat` and no `due_before_task`).
        Zeros mean "no minimum" or "no escalation". Anchored and deadline schedules get their
        first due date and a nudge for it."""
        task = self.get(task_id)
        if not self.can_edit(task, by):
            raise PermissionDenied("only the person doing it, whoever added it, or an admin")
        if repeat is None and due_before_task is None:
            self.db.execute(
                "UPDATE tasks SET times_per_week = NULL, repeat = NULL, due_before_task = NULL, "
                "minimum_days = NULL, escalate_days = NULL, escalate_to = NULL, shared = 0, "
                "either = 0 WHERE id = ?",
                (task_id,),
            )
            return self.get(task_id)
        if minimum_days < 0 or escalate_days < 0:
            raise ValueError("days can't be negative")
        if minimum_days and escalate_days and escalate_days < minimum_days:
            raise ValueError("escalation has to come after the minimum, not before it")
        if escalate_to not in ("owner", "both"):
            raise ValueError("escalate_to is 'owner' or 'both'")
        if missed not in MISSED:
            raise ValueError("missed is 'roll', 'catch_up' or 'next_day'")
        if due_before_task is not None:
            if due_before_task == task_id:
                raise ValueError("a chore can't be due before itself")
            target = self.get(due_before_task)  # NotFound if there's no such task
            if target.repeat is None and target.due_on is None:
                raise ValueError(f"'{target.title}' has no dates to be due before")
        floating = repeat is not None and not repeat.anchored
        self.db.execute(
            "UPDATE tasks SET times_per_week = ?, repeat = ?, due_before_task = ?, missed = ?, "
            "missed_next_day = ?, minimum_days = ?, escalate_days = ?, escalate_to = ?, "
            "either = ?, shared = ? WHERE id = ?",
            (
                repeat.times_per_week if floating and repeat else None,
                json.dumps(repeat.to_json()) if repeat and repeat.anchored else None,
                due_before_task,
                "roll" if missed == "next_day" else missed,  # its own column (0047)
                int(missed == "next_day"),
                minimum_days or None,
                escalate_days or None,
                escalate_to if escalate_days else None,
                int(either),
                int(either),
                task_id,
            ),
        )
        task = self.get(task_id)
        first = self._first_due(task)
        if first is not None and first != task.due_on:
            self.db.execute(
                "UPDATE tasks SET due_on = ? WHERE id = ?", (first.isoformat(), task_id)
            )
            task = self.get(task_id)
            self.withdraw_prompt(task)
            await self.prompt(task, not_before=self._round_starts(task))
            await self._changed(task, "rescheduled", True)
        elif task.due_on is not None and self.withdraw_prompt(task):
            # The nudge queued when the task was made waits for the chore's own day (bug #10).
            await self.prompt(task, not_before=self._round_starts(task))
        return task

    def set_progression(self, task_id: int, by: Member, plan: Progression | None) -> Task:
        """Give a task a plan that steps up week by week, or take it away (F9c)."""
        task = self.get(task_id)
        if not self.can_edit(task, by):
            raise PermissionDenied("only the person doing it, whoever added it, or an admin")
        self.db.execute(
            "UPDATE tasks SET progression = ? WHERE id = ?",
            (json.dumps(plan.to_json()) if plan else None, task_id),
        )
        return self.get(task_id)

    def summary(self, task: Task) -> str:
        """The schedule in plain words, from what's stored (the read-back)."""
        parts = []
        if task.due_before_task is not None:
            try:
                target = self.get(task.due_before_task)
                parts.append(f"Due the day before {target.title} ({self.summary(target)})")
            except NotFound:
                parts.append("Due the day before another chore that's gone")
        elif task.repeat is not None:
            parts.append(read_back(task.repeat))
        elif task.times_per_week:
            parts.append(read_back(Repeat("floating", times_per_week=task.times_per_week)))
        else:
            return "Doesn't repeat"
        if task.either:
            parts.append("either of you")
        if task.minimum_days:
            parts.append(f"overdue after {_days(task.minimum_days)}")
        if task.escalate_days:
            who = "both of you" if task.escalate_to == "both" else "a reminder to its owner"
            verb = "it goes to" if task.escalate_to == "both" else "comes"
            parts.append(f"after {_days(task.escalate_days)} {verb} {who}")
        if task.repeat is not None and task.missed == "catch_up":
            parts.append("a missed round stays owed")
        if task.repeat is not None and task.missed == "next_day":
            parts.append("a missed day moves to the next day")
        if task.repeat is not None and task.repeat.before_sunset is not None:
            at = self.time_of(task, self._today())
            parts.append(
                f"today that's about {clock_words(at)}"
                if at
                else "sunset needs the home address (the Family page)"
            )
        return "; ".join(parts)

    def next_dates(self, task: Task, count: int = 3) -> list[datetime]:
        """The coming rounds of an anchored chore, for the website."""
        if task.repeat is None:
            return []
        start = self._round_starts(task)
        upcoming = [start] if start else []
        after = start or clock.now()
        upcoming += next_occurrences(task.repeat, after, self._tz(), count)
        return upcoming[:count]

    def _first_due(self, task: Task) -> date | None:
        """An anchored chore's next date (today counts if its time hasn't passed), or a
        deadline chore's day-before date."""
        if task.due_before_task is not None:
            return self._deadline_due(task)
        if task.repeat is None:
            return None
        now = clock.now()
        if task.repeat.at is None:  # a date-only round today is still today's
            now = self._day_start(self._today()) - timedelta(microseconds=1)
        found = next_occurrences(task.repeat, now, self._tz())
        return self._after_rest(task, found[0].date()) if found else None

    def round_end(self, task: Task) -> date | None:
        """The last day the current round is on time: the day after its due date for an
        either-day round ("Saturday or Sunday"), else the due date (F9a)."""
        if task.due_on is None or task.repeat is None:
            return task.due_on
        return round_end(task.repeat, task.due_on)

    def round_days(self, task: Task) -> list[date]:
        """The days the current round can be done on time, for ticks on the wall."""
        end = self.round_end(task)
        if task.due_on is None or end is None:
            return []
        return [task.due_on + timedelta(days=n) for n in range((end - task.due_on).days + 1)]

    def done_day(self, due_on: date, done_at: datetime, task: Task) -> date:
        """Which day a round's tick goes on: the day it was done, when that was one of the
        round's days (Sunday for a weekend run done Sunday), else its due date."""
        day = done_at.astimezone(self._tz()).date()
        end = round_end(task.repeat, due_on) if task.repeat is not None else due_on
        return day if due_on <= day <= end else due_on

    def _after_rest(self, task: Task, day: date) -> date:
        """ "Never two days in a row": not the day after the last time it was done (F9a)."""
        if task.repeat is None or not task.repeat.rest:
            return day
        last = self._last_done(task)
        if last is None:
            return day
        return max(day, last.astimezone(self._tz()).date() + timedelta(days=2))

    def _deadline_due(self, task: Task) -> date | None:
        """The day before the other chore's round, unless this chore was already done for
        that round, in which case the day before its next one."""
        assert task.due_before_task is not None
        try:
            target = self.get(task.due_before_task)
        except NotFound:
            return task.due_on
        if target.due_on is None:
            return task.due_on
        tz = self._tz()
        round_day = target.due_on
        last = self._last_done(task)
        if last is not None and target.repeat is not None:
            previous = previous_occurrence(target.repeat, self._day_start(round_day), tz)
            if last.astimezone(tz).date() > (previous.date() if previous else date.min):
                end_of_round = self._day_start(round_day + timedelta(days=1))
                following = next_occurrences(target.repeat, end_of_round, tz)
                if following:
                    round_day = following[0].date()
        return round_day - timedelta(days=1)

    def _next_due_after_done(self, task: Task, today: date) -> date | None:
        """The next round's day; None when a course with an end date is over."""
        if task.due_before_task is not None:
            return self._deadline_due(task) or today + timedelta(days=7)
        if task.repeat is not None:
            # This round counts as done, early or late: the next one is after it.
            last_day = max(today, task.due_on or today)
            after = self._day_start(last_day + timedelta(days=1)) - timedelta(microseconds=1)
            found = next_occurrences(task.repeat, after, self._tz())
            if found:
                return self._after_rest(task, found[0].date())
            return None if task.repeat.until else today + timedelta(days=7)
        assert task.times_per_week is not None
        return today + timedelta(days=max(1, int(7 / task.times_per_week + 0.5)))

    async def _complete_round(self, task: Task, by: Member, interactive: bool) -> str:
        missed = self._just_missed(task)
        if missed is not None:
            return self._fill_missed(task, by, missed)
        self.withdraw_prompt(task)  # before its prompt_outbox_id is cleared below
        today = self._today()
        end = self.round_end(task)
        on_time = end is None or today <= end
        now = to_utc_iso(clock.now())
        self.db.execute(
            "INSERT INTO task_runs (task_id, done_by, done_at, due_on, on_time) "
            "VALUES (?, ?, ?, ?, ?)",
            (task.id, by.id, now, task.due_on.isoformat() if task.due_on else None, int(on_time)),
        )
        next_due = self._next_due_after_done(task, today)
        if next_due is None:
            await self._finish_course(task, interactive)
            return DONE_TEXT.format(title=task.title) + LAST_ROUND_TEXT
        self.db.execute(  # the next round: back to its owner, nothing overdue or unanswered
            "UPDATE tasks SET status = 'open', due_on = ?, shared = either, snoozed_until = NULL, "
            "overdue_notified_at = NULL, escalated_at = NULL, overdue_reminders = 0, "
            "overdue_reminded_on = NULL, prompt_outbox_id = NULL WHERE id = ?",
            (next_due.isoformat(), task.id),
        )
        fresh = self.get(task.id)
        await self.prompt(fresh, not_before=self._round_starts(fresh))
        await self._changed(fresh, "rescheduled", interactive)
        await self._maybe_offer_step_up(fresh)
        return DONE_TEXT.format(title=task.title) + NEXT_ROUND_TEXT.format(
            when=next_due.strftime("%a %d %b")
        )

    def _just_missed(self, task: Task) -> dict[str, Any] | None:
        """The run of a round that rolled on undone and ended yesterday, while the next hasn't
        begun: "I brought the bins in" the morning after is for that one, not next week's."""
        today = self._today()
        if task.repeat is None or task.due_on is None or task.due_on <= today:
            return None
        last = self.db.one(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task.id,)
        )
        if last is None or not last["missed"] or last["due_on"] is None:
            return None
        end = round_end(task.repeat, date.fromisoformat(last["due_on"]))
        return last if end >= today - timedelta(days=1) else None

    def _fill_missed(self, task: Task, by: Member, missed: dict[str, Any]) -> str:
        """Done a day late: the missed run becomes a late one and the next round stays. It's
        a new run, not the old one changed, so the wall's sync ticks its day; added before
        the old one goes, as SQLite would give a newest run's id to the next one."""
        self.db.execute(
            "INSERT INTO task_runs (task_id, done_by, done_at, due_on, on_time) "
            "VALUES (?, ?, ?, ?, 0)",
            (task.id, by.id, to_utc_iso(clock.now()), missed["due_on"]),
        )
        self.db.execute("DELETE FROM task_runs WHERE id = ?", (missed["id"],))
        assert task.due_on is not None
        return DONE_TEXT.format(title=task.title) + NEXT_ROUND_TEXT.format(
            when=task.due_on.strftime("%a %d %b")
        )

    async def _finish_course(self, task: Task, interactive: bool) -> None:
        """A chore with an end date has had its last round."""
        self.db.execute(
            "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task.id),
        )
        self.withdraw_prompt(task)
        await self._changed(self.get(task.id), "done", interactive)

    async def _settle_missed_round(self, task: Task) -> Task:
        """An anchored round whose day has passed: roll on to the next date (recording a missed
        run), for catch-up chores leave it owed, or for next-day ones move it to tomorrow
        (F9a). Deadline chores follow their target."""
        today = self._today()
        if task.due_before_task is not None:
            due = self._deadline_due(task)
            if due is not None and task.due_on is not None and due > task.due_on and due > today:
                # The other chore's round moved on; if this one wasn't done for it, it's missed.
                last = self._last_done(task)
                if last is None or last.astimezone(self._tz()).date() < task.due_on:
                    self._record_missed(task)
                self._move_round(task, due)
            return self.get(task.id)
        end = self.round_end(task)
        if task.repeat is None or end is None or end >= today:
            return task
        if task.missed == "catch_up":
            return task
        if task.missed == "next_day":  # unless the next round comes first: then it rolls on
            tomorrow = self._after_rest(task, today)
            following = next_occurrences(
                task.repeat, self._day_start(end + timedelta(days=1)), self._tz()
            )
            if following and tomorrow < following[0].date():
                self._move_round(task, tomorrow)
                return self.get(task.id)
        self._record_missed(task)
        found = next_occurrences(task.repeat, clock.now(), self._tz())
        if found:
            self._move_round(task, self._after_rest(task, found[0].date()))
        elif task.repeat.until is not None:
            await self._finish_course(task, False)
        return self.get(task.id)

    def _record_missed(self, task: Task) -> None:
        self.db.execute(
            "INSERT INTO task_runs (task_id, done_by, done_at, due_on, on_time, missed) "
            "VALUES (?, NULL, ?, ?, 0, 1)",
            (task.id, to_utc_iso(clock.now()), task.due_on.isoformat() if task.due_on else None),
        )

    def _move_round(self, task: Task, due: date) -> None:
        self.db.execute(
            "UPDATE tasks SET due_on = ?, status = 'open', snoozed_until = NULL, "
            "overdue_reminders = 0, overdue_reminded_on = NULL WHERE id = ?",
            (due.isoformat(), task.id),
        )
        self.withdraw_prompt(task)
        self._pending_prompts.append(task.id)

    async def check_schedules(self) -> int:
        """Scheduler job: settle missed anchored rounds, then overdue nudges past the minimum
        and escalation past its point (each once per round). Returns how many were nudged."""
        nudged = 0
        now = clock.now()
        self._pending_prompts = []
        rows = self.db.query(
            "SELECT * FROM tasks WHERE (times_per_week IS NOT NULL OR repeat IS NOT NULL "
            "OR due_before_task IS NOT NULL) AND status IN ('open', 'snoozed')"
        )
        for row in rows:
            task = await self._settle_missed_round(_task_from_row(row))
            if task.status == "done":  # a course that's over
                continue
            row = self.db.one("SELECT * FROM tasks WHERE id = ?", (task.id,)) or row
            since = self._last_done(task) or datetime.fromisoformat(row["created_at"])
            days = (now - since) / timedelta(days=1)
            stamp = to_utc_iso(now)
            if task.escalate_days and days >= task.escalate_days and not row["escalated_at"]:
                both = task.escalate_to == "both"
                self.db.execute(
                    "UPDATE tasks SET escalated_at = ?, overdue_notified_at = ?, shared = ? "
                    "WHERE id = ?",
                    (stamp, row["overdue_notified_at"] or stamp, int(both), task.id),
                )
                task = self.get(task.id)
                if both:
                    for member in self.store.list_members():
                        if member.telegram_user_id is not None:
                            await self.prompt(task, member=member, overdue="shared")
                else:
                    await self.prompt(task, overdue="own")
                nudged += 1
            elif task.minimum_days and days >= task.minimum_days and not row["overdue_notified_at"]:
                self.db.execute(
                    "UPDATE tasks SET overdue_notified_at = ? WHERE id = ?", (stamp, task.id)
                )
                await self.prompt(task, overdue="own")
                nudged += 1
        for task_id in self._pending_prompts:  # rounds that moved on get their nudge
            fresh = self.get(task_id)
            await self.prompt(fresh, not_before=self._round_starts(fresh))
        self._pending_prompts = []
        return nudged

    async def _maybe_offer_step_up(self, task: Task) -> None:
        """After STEP_UP_AFTER on-time runs in a row, offer one more time a week, as an
        approval. Nothing changes without a yes, and the next offer needs a new stretch."""
        times = task.times_per_week
        if times is None or times != int(times) or times >= 7 or task.assignee is None:
            return
        offered = self.db.scalar("SELECT step_up_offered_at FROM tasks WHERE id = ?", (task.id,))
        rows = self.db.query(
            "SELECT on_time FROM task_runs WHERE task_id = ? AND (? IS NULL OR done_at > ?) "
            "ORDER BY done_at DESC, id DESC LIMIT ?",
            (task.id, offered, offered, STEP_UP_AFTER),
        )
        if len(rows) < STEP_UP_AFTER or not all(r["on_time"] for r in rows):
            return
        current, more = int(times), int(times) + 1
        self.db.execute(
            "UPDATE tasks SET step_up_offered_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task.id),
        )
        await self.services.autonomy.stage(
            STEP_UP_CATEGORY,
            self.store.get_member(task.assignee),
            f"Step up: {task.title}, {more} times a week instead of {current}",
            {"task": task.id, "times": more},
            STEP_UP_EXECUTOR,
        )

    async def _step_up(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        task_id, times = int(payload["task"]), float(payload["times"])
        self.db.execute("UPDATE tasks SET times_per_week = ? WHERE id = ?", (times, task_id))
        task = self.get(task_id)
        return f"{task.title}: {self.summary(task)}, from now on."

    async def cancel(self, task_id: int, by: Member, *, interactive: bool = False) -> str:
        """Nobody needs to do it after all (deleting a task keeps its record)."""
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        self.db.execute(
            "UPDATE tasks SET status = 'cancelled', completed_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), task_id),
        )
        self.withdraw_prompt(task)
        await self._changed(self.get(task_id), "cancelled", interactive)
        return CANCELLED_TEXT.format(title=task.title)

    async def reschedule(
        self,
        task_id: int,
        due_on: date | None,
        *,
        due_time: time | Keep | None = KEEP,
        from_time: time | Keep | None = KEEP,
        interactive: bool = False,
    ) -> str:
        """A new date, and a new time if given (bug #54). A snooze ends and the nudge is
        asked again for the new moment, so nothing comes at the old one. A repeating
        chore's time is its schedule's: every round takes it (bug #56)."""
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        new_due = task.due_time if isinstance(due_time, Keep) else due_time
        new_from = task.from_time if isinstance(from_time, Keep) else from_time
        repeat = task.repeat
        if repeat is not None and not isinstance(due_time, Keep):
            repeat, new_due = replace(repeat, at=due_time), None
        if due_on is None:
            new_due = new_from = None
        if new_from and (new_due is None or new_from >= new_due):
            raise ValueError("a window needs its start before its end")
        self.db.execute(
            "UPDATE tasks SET due_on = ?, due_time = ?, from_time = ?, repeat = ?, "
            "status = 'open', snoozed_until = NULL, overdue_reminders = 0, "
            "overdue_reminded_on = NULL WHERE id = ?",
            (
                due_on.isoformat() if due_on else None,
                new_due.strftime("%H:%M") if new_due else None,
                new_from.strftime("%H:%M") if new_from else None,
                json.dumps(repeat.to_json()) if repeat else None,
                task_id,
            ),
        )
        self.withdraw_prompt(task)
        self._end_own_snoozes(task_id)  # a new day is for everyone who has it (F19c)
        task = self.get(task_id)
        if due_on is not None:
            if task.either:
                for member in self.store.list_members():
                    if member.telegram_user_id is not None:
                        await self.prompt(task, member=member)
            else:
                await self.prompt(task)
        await self._changed(task, "rescheduled", interactive)
        both = BOTH_MOVED_TEXT if task.shared and interactive else ""
        if due_on is None:
            return UNSCHEDULED_TEXT.format(title=task.title) + both
        return RESCHEDULED_TEXT.format(title=task.title, due=self.when_words(task)) + both

    def when_words(self, task: Task) -> str:
        """ "Thu 29 Oct, 2 pm", "Fri 30 Oct, 12-1 pm", or "Thu 29 Oct"."""
        assert task.due_on is not None
        day = f"{task.due_on:%a %d %b}"
        if task.due_on.year != self._today().year:  # a wrong year shows (#84)
            day += f" {task.due_on.year}"
        at = task.due_time or (task.repeat.at if task.repeat else None)
        if task.from_time and task.due_time:
            return f"{day}, {clock_words(task.from_time)}-{clock_words(task.due_time)}"
        return f"{day}, {clock_words(at)}" if at else day

    async def make_either(self, task_id: int) -> Task:
        """Either of them can do it (bug #26, "one of us"): on both lists, asked of both,
        and whoever does it closes it."""
        self.db.execute("UPDATE tasks SET either = 1, shared = 1 WHERE id = ?", (task_id,))
        task = self.get(task_id)
        self.withdraw_prompt(task)  # one nudge each, not a second for whoever had it
        for member in self.store.list_members():
            if member.telegram_user_id is not None:
                await self.prompt(task, member=member)
        return task

    def snooze(
        self,
        task_id: int,
        for_: timedelta = SNOOZE_FOR,
        *,
        until: datetime | None = None,
        by: Member | None = None,
    ) -> str:
        """Put a task off for a few hours, or until a time they gave ("tonight at 9", #18).
        On both lists, it's put off for `by` alone (F19c, idea #86)."""
        task = self.get(task_id)
        if task.status in ("done", "cancelled"):
            return SETTLED_TEXT
        if by is not None and task.shared:
            return self._snooze_for(task, by, until or clock.now() + for_, said=until is not None)
        self.db.execute(
            "UPDATE tasks SET status = 'snoozed', snoozed_until = ? WHERE id = ?",
            (to_utc_iso(until or clock.now() + for_), task_id),
        )
        self.withdraw_prompt(task)
        if until is not None:
            return UNTIL_TEXT.format(title=task.title, when=self._until_words(until))
        return LATER_TEXT.format(title=task.title)

    def _snooze_for(self, task: Task, by: Member, until: datetime, *, said: bool) -> str:
        """Erin's idea #86: "only snooze it for that user". Their nudges wait; the task stays
        open, on the other's list and the wall as it was."""
        self.db.execute(
            "INSERT INTO task_snoozes (task_id, member_id, until) VALUES (?, ?, ?) "
            "ON CONFLICT (task_id, member_id) DO UPDATE SET until = excluded.until",
            (task.id, by.id, to_utc_iso(until)),
        )
        for queued in self.db.query(
            "SELECT id FROM outbox WHERE status = 'queued' AND member_id = ? AND dedupe_key LIKE ?",
            (by.id, f"task-{task.id}-%"),
        ):
            self.outbox.cancel(queued["id"])
        text = (
            YOURS_UNTIL_TEXT.format(title=task.title, when=self._until_words(until))
            if said
            else YOURS_LATER_TEXT.format(title=task.title)
        )
        others = [
            m.name
            for m in self.store.list_members()
            if m.id != by.id and m.telegram_user_id is not None and not self._own_snooze(task, m)
        ]
        if others:
            text += STILL_ON_TEXT.format(whose=" and ".join(f"{n}'s" for n in others))
        return text

    def _until_words(self, until: datetime) -> str:
        local = until.astimezone(self._tz())
        when = clock_words(local)
        # Bug #54: which day, when it isn't today; #104: "until 2 pm" became "tomorrow".
        return f"{local:%a %d %b}, {when}" if local.date() != self._today() else f"{when} today"

    def put_off_until(self, task: Task, member: Member | None = None) -> datetime | None:
        """When a snooze that hasn't ended runs out ("tonight at 9", #18), else None. With a
        `member`, their own put-off of a shared task counts too (F19c)."""
        until = self.db.scalar(
            "SELECT snoozed_until FROM tasks WHERE id = ? AND status = 'snoozed'", (task.id,)
        )
        if until and (when := datetime.fromisoformat(until)) > clock.now():
            return when
        return self._own_snooze(task, member) if member is not None else None

    def _own_snooze(self, task: Task, member: Member) -> datetime | None:
        until = self.db.scalar(
            "SELECT until FROM task_snoozes WHERE task_id = ? AND member_id = ? AND until > ?",
            (task.id, member.id, to_utc_iso(clock.now())),
        )
        return datetime.fromisoformat(until) if until else None

    def _end_own_snoozes(self, task_id: int) -> None:
        """Done, or moved to a new day: nobody's own put-off of it stands (F19c)."""
        self.db.execute("DELETE FROM task_snoozes WHERE task_id = ?", (task_id,))

    def withdraw_prompt(self, task: Task) -> bool:
        """Take back any of the task's nudges that haven't gone out yet (shared ones too).
        True if there was one."""
        withdrawn = False
        row = self.db.one("SELECT prompt_outbox_id FROM tasks WHERE id = ?", (task.id,))
        if row and row["prompt_outbox_id"]:
            withdrawn = self.outbox.cancel(row["prompt_outbox_id"])
        for queued in self.db.query(
            "SELECT id FROM outbox WHERE status = 'queued' AND dedupe_key LIKE ?",
            (f"task-{task.id}-%",),
        ):
            withdrawn = self.outbox.cancel(queued["id"]) or withdrawn
        return withdrawn

    async def resurface(self) -> int:
        """Snoozed tasks whose time has come are offered again; one person's put-off of a
        shared task, to that person (F19c)."""
        now = to_utc_iso(clock.now())
        rows = self.db.query(
            "SELECT * FROM tasks WHERE status = 'snoozed' AND snoozed_until <= ?", (now,)
        )
        for row in rows:
            self.db.execute(
                "UPDATE tasks SET status = 'open', snoozed_until = NULL WHERE id = ?", (row["id"],)
            )
            await self.prompt(self.get(row["id"]))
        own = self.db.query("SELECT * FROM task_snoozes WHERE until <= ?", (now,))
        for row in own:
            self.db.execute(
                "DELETE FROM task_snoozes WHERE task_id = ? AND member_id = ?",
                (row["task_id"], row["member_id"]),
            )
            task = self.get(row["task_id"])
            if task.status == "open" and task.shared:
                await self.prompt(task, member=self.store.get_member(row["member_id"]))
        return len(rows) + len(own)

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        task_id = int(event.button.payload["task"])
        action = event.button.payload.get("action")
        if action == "list_done":
            await self._list_done(event)
            return
        if action == "done":
            reply = await self.complete(
                task_id, event.member, interactive=True, tapped=event.button.message_id
            )
        elif action == "not_sure":
            reply = NOT_SURE_TEXT  # Rx1: it stays open, and nothing is advised
        else:
            reply = self.snooze(task_id, by=event.member)
        if event.button.message_id is not None:
            await self.outbox.edit(event.member, event.button.message_id, reply)


def _task_id(row: dict[str, Any]) -> int | None:
    """The task a queued nudge is for, from its dedupe key ("task-12-ab12cd34")."""
    parts = str(row.get("dedupe_key") or "").split("-")
    return int(parts[1]) if len(parts) > 2 and parts[0] == "task" and parts[1].isdigit() else None


def _praise(task: Task) -> str:
    return praise.word(str(task.id))


def _short(title: str, limit: int = 28) -> str:
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def _label(task: Task, today: date) -> str:
    """What a nudge opens with, for the day it goes out. At most three words, so the
    phrasing check reads it as a label rather than an order."""
    if task.check_in:
        return "Check-in"
    if task.due_on is None:
        return "To do"
    days = (task.due_on - today).days
    if days == 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    if days == -1:
        return "Was due yesterday"
    named = f"{task.due_on:%A}" if abs(days) < 7 else f"{task.due_on.day} {task.due_on:%b}"
    return f"Due {named}" if days > 0 else f"Was due {named}"


def _on(day: date, at: time, tz: ZoneInfo) -> datetime:
    """That wall-clock time on that day, in the family's timezone."""
    return datetime(day.year, day.month, day.day, at.hour, at.minute, tzinfo=tz)


def _days(value: float) -> str:
    return f"{value:g} day{'s' if value != 1 else ''}"


_LEVEL_TAG = re.compile(r"^\((low|medium|high)\)", re.IGNORECASE)
_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}
_LEVEL_LEAD = {
    "low": "A lighter version for today:",
    "medium": "A middle version for today:",
    "high": "The full version for today:",
}
_LEVEL_WORD = {"low": "lighter", "medium": "middle", "high": "full"}


def _step_level(step: str) -> str | None:
    m = _LEVEL_TAG.match(step)
    return m.group(1).lower() if m else None


def _quoted(steps: Sequence[str]) -> str:
    """Steps as `> ` quotes, so the PDA shield keeps them word for word (steps are usually
    commands: "Wipe the counters")."""
    return "\n".join(f"> - {step}" for step in steps)


def _board(ctx: ToolContext) -> TaskBoard:
    board = ctx.services.taskboard
    assert board is not None
    return board


# P6: "new rule: the grocery order happens on Sundays" became a task (eval
# rule-husband-groceries). Said as a rule, it's propose_rule, unless it's a reminder.
CALLED_A_RULE = re.compile(r"\b(?:new|house(?:hold)?) rule\b|\bmake (?:it|that|this) a rule\b")


@tool(
    "create_task",
    "Add a household task and nudge whoever does it at a good moment. assign_to says who: "
    "'me' when the person asking will do it ('I want to...', 'I'll...', 'remind me to...'), "
    "a family member's name when they name someone ('have my husband get the pacifier', 'ask "
    "him to...'), 'both' when either of them can do it "
    "('one of us', 'either of us': on both lists, whoever does it closes it), or 'anyone' "
    "when it just needs doing ('can someone...'); then Themi works out who has room for it. "
    "A small thing at a set time where a nudge is all they want ('remind me to drink green "
    "tea at 2') is add_reminder, not a task.",
    {
        "title": {"type": "string", "description": "What needs doing, e.g. 'Call the vet'."},
        "kind": {"type": "string", "enum": TASK_KINDS},
        "effort": {
            "type": "integer",
            "enum": [1, 2, 3, 4, 5],
            "description": "1 = a quick thing, 5 = a big draining job.",
        },
        "due_date": {
            "type": "string",
            "description": "YYYY-MM-DD if it has a date, else an empty string.",
        },
        "due_time": {
            "type": "string",
            "description": "HH:MM (24-hour) if they gave a time of day ('around 2' is 14:00), "
            "or a window's end ('between 2 and 3' is 15:00), else an empty string. Nothing is "
            "asked about before it's due.",
        },
        "from_time": {
            "type": "string",
            "description": "HH:MM for a window's start ('between 2 and 3' is 14:00; the "
            "nudge comes then and it's overdue after due_time), else an empty string.",
        },
        "assign_to": {
            "type": "string",
            "description": "'me', a family member's name, 'both', 'anyone', or "
            "'someone else' (the other partner).",
        },
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The steps of the job, in their words and order (tags like "
            "'(Optional/Bonus)' included), or an empty list.",
        },
        "check_in": {
            "type": "boolean",
            "description": "True when they want Themi to check in on whether they did it "
            "('check in with me about running'), rather than to remind them of a job.",
        },
        "importance": {
            "type": "string",
            "enum": list(IMPORTANCE),
            "description": "'high' when it's important: there are consequences if it's never "
            "done ('important', 'we can't forget this', bills, medicine); 'low' for a "
            "nice-to-have; else 'normal'. Urgent is the due date, not this: 'urgent' or "
            "'asap' with no date is due today.",
        },
    },
)
async def create_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    said = ctx.request_text.lower()
    if CALLED_A_RULE.search(said) and "remind" not in said:
        raise ToolFailed(
            "Not created: they called it a rule, so it's propose_rule (a draft they lock in "
            "themselves), not a task."
        )
    due = None
    if args["due_date"]:
        try:
            due = day_arg(args["due_date"], _board(ctx)._today())
        except ValueError:
            return "Not created: the due date should look like 2026-11-03."
    try:
        due_time = time.fromisoformat(args["due_time"]) if args["due_time"] else None
        from_time = time.fromisoformat(args["from_time"]) if args["from_time"] else None
    except ValueError:
        return "Not created: times should look like 14:30."
    if from_time and (due_time is None or from_time >= due_time):
        return "Not created: a window needs its start (from_time) before its end (due_time)."
    if due_time and due is None:
        due = _board(ctx)._today()  # a time with no date means today
    if due is None and URGENT_WORDS.search(ctx.request_text.lower()):
        due = _board(ctx)._today()  # T1: urgent is a due date that's soon
    try:
        chosen, both = _assignee(ctx, args["assign_to"])
    except ValueError as exc:
        return f"Not created: {exc}."
    whose = [chosen] if chosen is not None else ctx.services.store.list_members()
    same = next(
        (
            t
            for m in whose
            for t in _board(ctx).open_for(m)
            if title_matches(args["title"], t.title)
        ),
        None,
    )
    if same is not None:  # bug #56: a second "Mimi pill" to change the first one's time
        return (  # bug #88: the model asked instead, and couldn't make it both of theirs
            f"Not created: task {same.id} ({same.title}) is already open. Change that one "
            "instead, now, to everything they asked for (don't ask them first): its day or "
            "time with reschedule_task (a repeating chore's time goes for every round), who "
            "does it with update_task's assign_to, its schedule with set_task_schedule. If "
            "this is a different job, give it a title that says how."
        )
    try:
        task = await _board(ctx).create(
            ctx.member,
            args["title"],
            args["kind"],
            args["effort"],
            due,
            interactive=True,
            assignee=chosen,
            steps=args["steps"],
            check_in=bool(args["check_in"]),
            due_time=due_time,
            from_time=from_time,
            nudge=not both,
            importance=args["importance"],
        )
        if both:
            task = await _board(ctx).make_either(task.id)
    except ValueError as exc:
        return f"Not created: {exc}"
    ctx.tasks.append(task.id)
    assignee = ctx.services.store.get_member(task.assignee) if task.assignee else ctx.member
    nudged, tell = f"{assignee.name} gets", ""
    if both:  # bug #97: this said "assigned to Michael", and so did the reply
        who = "for both of them, on both lists (either can do it; whoever does it closes it)"
        nudged, tell = "Each of them gets", " Say it's on both lists, not one person's."
    elif assignee.id == ctx.member.id:
        who = f"and assigned to {assignee.name} (the person asking)"
    else:
        who = f"and assigned to {assignee.name}"
        tell = f" Let {ctx.member.name} know it went to {assignee.name}."
    due = f", due {_board(ctx).when_words(task)}" if task.due_on else ""
    said = (
        _RELATIVE_DAY.search(task.title)
        if task.due_on and task.due_on != _board(ctx)._today()
        else None
    )
    rename = (  # bug #95: "...the tutoring session today", read tomorrow
        f' Its title says "{said.group(0)}", which won\'t be true then: rename it now with '
        "update_task to name the thing itself and its date (from the calendar or the "
        "conversation, e.g. 'Send the invoice for Tutor Gabriel (Thu 29 Oct)')."
        if said
        else ""
    )
    return (
        f"Task {task.id} created {who}{due}."
        + ("" if both else f" Why: {task.assign_reason}")
        + f" {nudged} a gentle nudge at a good moment.{tell}{rename} Say its title "
        "and when in one line."
    )


@tool(
    "update_task",
    "Rename a task, replace its steps (the full new list, in their words), e.g. when someone "
    "adds, removes or reorders steps of a chore, or change who does a one-off task. Empty "
    "title or steps keep what's there; clear_steps removes them all. assign_to as for "
    "create_task ('me', a name, 'both', 'someone else'), or '' to keep.",
    {
        "task_id": {"type": "integer"},
        "title": {"type": "string", "description": "A new title, or an empty string."},
        "steps": {"type": "array", "items": {"type": "string"}},
        "clear_steps": {"type": "boolean"},
        "assign_to": {"type": "string"},
    },
)
async def update_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = _board(ctx)
    steps = [] if args["clear_steps"] else (args["steps"] or None)
    try:
        task = await board.update(
            args["task_id"], ctx.member, title=args["title"], steps=steps, interactive=True
        )
        if args["assign_to"].strip():
            if task.repeats:
                raise ValueError(
                    "a chore's people are its schedule's: set_task_schedule's either, or "
                    "assign it when it's made"
                )
            chosen, both = _assignee(ctx, args["assign_to"])
            if chosen is not None or both:
                task = await board.reassign(task.id, chosen, shared=both)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except PermissionDenied as exc:
        raise ToolFailed("That task isn't theirs to change.") from exc
    except ValueError as exc:
        raise ToolFailed(str(exc)) from exc
    steps_now = "; ".join(task.steps) if task.steps else "none"
    if task.shared:
        who = "both of them (on both lists; whoever does it closes it)"
    else:
        who = ctx.services.store.get_member(task.assignee).name if task.assignee else "nobody yet"
    return f"Task {task.id} is now: {task.title}. Steps: {steps_now}. Who: {who}."


def _assignee(ctx: ToolContext, said: str) -> tuple[Member | None, bool]:
    """Who assign_to names, and whether it's both of them ("one of us", bug #26). Nobody in
    particular ('anyone', '') is (None, False). ValueError for a name not in the family."""
    target = said.strip().lower()
    if target in BOTH_WORDS:
        return None, True
    if target in ("me", "myself", "the person asking"):
        return ctx.member, False
    if target in OTHER_WORDS:  # "can someone else deal with it?"
        others = [m for m in ctx.services.store.list_members() if m.id != ctx.member.id]
        return (others[0] if len(others) == 1 else None), False
    if target in ("anyone", "someone", ""):
        return None, False
    members = ctx.services.store.list_members()
    chosen = next((m for m in members if m.name.lower() == target), None)
    if chosen is None:
        names = ", ".join(m.name for m in members)
        raise ValueError(f"there's nobody called {said.strip()} in the family ({names})")
    return chosen, False


@tool(
    "set_task_schedule",
    "Make a chore repeat, change its schedule, or stop it. repeat is a short phrase in plain "
    "words: 'every Tuesday at 6pm', 'every other Monday', 'every Tue and Fri', 'first Monday "
    "of the month', 'the 1st of every month', 'every 3 days', or 'twice a week' (counted from "
    "the last time it was done); empty to stop. Keep any time of day they gave ('Tuesday "
    "evenings' is 'every Tuesday evening'), and any end ('every 2 days until 30 Oct' for a "
    "course of medicine). due_before_task: the id of another chore this "
    "one is due the day before ('cardboard before garbage day'), else 0; repeat can then be "
    "empty. at_least_every_days: overdue after that many days (0 for none). "
    "escalate_after_days: past that, escalate (0 for none); escalate_to 'both' when they want "
    "it on both partners' lists (shared until done), else 'owner'. missed: 'roll' on to the "
    "next date if a round passes undone (usual), 'catch_up' to keep it owed, or 'next_day' "
    "('if I miss a day, prompt me the next day'). Either-day rounds, rest days and sunset go "
    "in the phrase: 'every Tue, Thu and Sat or Sun at 2pm, at least an hour before sunset, "
    "never two days in a row', 'every day 30 minutes before sunset'. either: true "
    "when either of them can do it each time (it's on both lists). Use it after "
    "create_task, also for repeating reminders ('always remind me about the bins on "
    "Tuesdays'). Themi reads the saved schedule back to them itself.",
    {
        "task_id": {"type": "integer"},
        "repeat": {"type": "string"},
        "at_least_every_days": {"type": "number"},
        "escalate_after_days": {"type": "number"},
        "escalate_to": {"type": "string", "enum": ["owner", "both"]},
        "missed": {"type": "string", "enum": list(MISSED)},
        "due_before_task": {"type": "integer"},
        "either": {"type": "boolean"},
    },
)
async def set_task_schedule(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = _board(ctx)
    phrase = args["repeat"].strip()
    try:
        _check_meant(ctx, board.get(args["task_id"]), "Not changed")
        repeat = parse(phrase, board._today()) if phrase else None
        task = await board.set_schedule(
            args["task_id"],
            ctx.member,
            repeat=repeat,
            minimum_days=float(args["at_least_every_days"]),
            escalate_days=float(args["escalate_after_days"]),
            escalate_to=args["escalate_to"],
            missed=args["missed"],
            due_before_task=args["due_before_task"] or None,
            either=bool(args["either"]),
        )
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except PermissionDenied as exc:
        raise ToolFailed("That task isn't theirs to change.") from exc
    except ValueError as exc:  # RepeatError included: its message lists phrases that work
        raise ToolFailed(str(exc)) from exc
    if not task.repeats:
        return f"Task {task.id} ({task.title}) doesn't repeat any more."
    # The read-back is built here from what was stored, and sent as it is.
    text = f"Saved: {board.summary(task)}."
    upcoming = board.next_dates(task, 1) if task.repeat else []
    if upcoming:
        when = upcoming[0]
        clock_time = f", {clock_words(when)}" if task.repeat and task.repeat.at else ""
        text += f" Next: {when:%a %d %b}{clock_time}."
    elif task.due_on is not None and task.due_before_task is not None:
        text += f" Next: {task.due_on:%a %d %b}."
    await ctx.services.outbox.send(ctx.member, text, priority=Priority.REPLY)
    return (
        f"Task {task.id} ({task.title}) is scheduled, and it was read back to them already, "
        f'word for word: "{text}". Don\'t restate the schedule; a short acknowledgement is '
        "enough, or ask if anything sounds wrong. If they asked for something that read-back "
        "doesn't show, say which part isn't set up and keep it with remember_fact."
    )


def _day_words(day: date, today: date) -> str:
    """ "Thu 29 Oct", with the year only when it isn't this one (bug #70 read "2020")."""
    return f"{day:%a %d %b}" if day.year == today.year else f"{day:%a %d %b %Y}"


def clock_words(moment: datetime | time) -> str:
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d} {suffix}" if moment.minute else f"{hour} {suffix}"


@tool(
    "complete_task",
    "Mark a task done when someone says it's been taken care of. The result is what to tell "
    "them, its warm word included; say it as it is.",
    {"task_id": {"type": "integer"}},
)
async def complete_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        task = _board(ctx).get(args["task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    if task.medicine and UNSURE.search(ctx.request_text):
        raise ToolFailed(  # Rx1, idea #48: "take it if you aren't sure" was the wrong advice
            "Not marked done: they aren't sure they took it. Leave it open. Say, gently, that "
            "the safe way is no second dose until they've checked, or until their doctor or "
            "pharmacist says; never tell them to take it, and give no other dose advice."
        )
    text = ctx.request_text
    if " ".join(re.findall(r"[a-z]+", text.lower())) in NOT_DONE:
        raise ToolFailed(
            "Not marked done: they said no. Nothing is done; leave it open, and offer to move "
            "it or hand it on only if that helps."
        )
    if QUESTION.search(text) and not SAYS_DONE.search(text):
        raise ToolFailed(  # #92: "Didn't I just clean the bird cage?" marked it done
            "Not marked done: they asked a question, not said it's done. Answer it (when it "
            "was last done is in its details); mark it done only when they say it is."
        )
    _check_meant(ctx, task, "Not marked done")
    if not _named(ctx, task):
        raise ToolFailed(
            f"Not marked done: nothing they said names {task.title}, and neither did Themi's "
            "last message. Mark only what they say is done; ask if it isn't clear."
        )
    return await _board(ctx).complete(task.id, ctx.member, interactive=True)


def _named(ctx: ToolContext, task: Task) -> bool:
    """Something said names this task: their message or the one before it, Themi's last one
    (the nudge they're answering), or all of them ("all done", "everything") (#97)."""
    said = (ctx.request_text, ctx.previous_text, ctx.said_before)
    return any(words_in_common(text, task.title) for text in said) or bool(
        ALL_OF_THEM.search(ctx.request_text)
    )


def _check_meant(ctx: ToolContext, task: Task, not_done: str) -> None:
    meant = _meant_instead(ctx, task)
    if meant is not None:
        raise ToolFailed(
            f"{not_done}: what they said names task {meant.id} ({meant.title}), not task "
            f"{task.id} ({task.title}). Use the one they mean, and say which by name."
        )


def _meant_instead(ctx: ToolContext, task: Task) -> Task | None:
    """Another open task the conversation names, when it names nothing of this one ("We
    contacted Erin's parents" marked the bins done, 2026-10-29). A short answer ("Yes please")
    is read with what Themi asked before it (#92). Just "done" names nothing: no check."""
    board = _board(ctx)
    rows = board.db.query(
        "SELECT id FROM tasks WHERE status IN ('open', 'snoozed') AND id != ?", (task.id,)
    )
    others = [board.get(r["id"]) for r in rows]
    texts = [ctx.request_text]
    if len(ctx.request_text.split()) <= SHORT_ANSWER:
        texts.append(ctx.said_before)
    for said in texts:
        if words_in_common(said, task.title):
            return None
        scored = [(words_in_common(said, t.title), t) for t in others]
        best = max(scored, key=lambda pair: pair[0], default=None)
        if best is not None and best[0] >= 2:
            return best[1]
        if best is not None and best[0]:
            return None  # a word of another's isn't enough to go on
    return None


@tool(
    "cancel_task",
    "Take a task off the list when it no longer needs doing (not when it's done).",
    {"task_id": {"type": "integer"}},
)
async def cancel_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        task = _board(ctx).get(args["task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    _check_meant(ctx, task, "Not taken off")
    return await _board(ctx).cancel(task.id, ctx.member, interactive=True)


@tool(
    "reschedule_task",
    "Change when a task is due: its day, its time, or both ('make it Friday at 1pm', "
    "'earlier on Friday', 'at 2 and 3 tomorrow'), or take its date away. For a repeating "
    "chore, a time changes every round ('the Mimi pill at 9pm, never before'); never make "
    "a second task for it. due_date: YYYY-MM-DD, '' to keep it, 'none' to take it away. "
    "Read the day from the whole conversation: 'tomorrow' or 'Friday' said earlier still "
    "counts. due_time and from_time: HH:MM (24-hour) as for create_task, '' to keep, "
    "'none' to clear. Anything put off earlier then waits for the new day and time.",
    {
        "task_id": {"type": "integer"},
        "due_date": {"type": "string"},
        "due_time": {"type": "string"},
        "from_time": {"type": "string"},
    },
)
async def reschedule_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = _board(ctx)
    try:
        task = board.get(args["task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    _check_meant(ctx, task, "Not changed")
    said = str(args["due_date"]).strip().lower()
    try:
        today = board._today()
        due = task.due_on if not said else None if said == "none" else day_arg(said, today)
        due_time = _time_arg(args["due_time"])
        from_time = _time_arg(args["from_time"])
    except ValueError as exc:
        raise ToolFailed("Not changed: dates look like 2026-11-03, and times like 14:30.") from exc
    if said and due == task.due_on and isinstance(due_time, Keep) and isinstance(from_time, Keep):
        return (  # bug #84: green tea was due Friday already, and the reply said it moved
            f"{task.title} is already due {board.when_words(task)}; nothing changed. Say so, "
            "rather than that it moved."
        )
    if due is None and said != "none":
        due = board._today() if not isinstance(due_time, Keep) else None  # a time: today
    try:
        return await board.reschedule(
            task.id, due, due_time=due_time, from_time=from_time, interactive=True
        )
    except ValueError as exc:
        raise ToolFailed(f"Not changed: {exc}.") from exc


def day_arg(text: str, today: date) -> date:
    """A date the model gave, YYYY-MM-DD. A past year is this year's, or next year's once
    that day has gone: nothing is due years ago ("Friday" became 2020-10-30, #84)."""
    day = date.fromisoformat(text)
    if day.year < today.year:
        day = day.replace(year=today.year, day=min(day.day, 28) if day.month == 2 else day.day)
        if day < today:
            day = day.replace(year=today.year + 1)
    return day


def _time_arg(value: Any) -> time | Keep | None:
    text = str(value).strip().lower()
    if not text:
        return KEEP
    return None if text == "none" else time.fromisoformat(text)


@tool(
    "snooze_task",
    "Put a task off when someone wants it later: until a time they gave ('I'll do it "
    "tonight around 9': until 21:00; HH:MM, 24-hour), on the day they gave ('tomorrow "
    "afternoon': day tomorrow's YYYY-MM-DD, until 14:00; a day alone is its morning), or "
    "for a few hours (both ''). With no day, the time is today's, or tomorrow's if that's "
    "passed. No nudge or reminder comes before then. Also for a nudge later today about a "
    "task they already have ('prompt me to run at 2pm': until 14:00): never a calendar "
    "block. A new due date or time for it is reschedule_task.",
    {"task_id": {"type": "integer"}, "until": {"type": "string"}, "day": {"type": "string"}},
)
async def snooze_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = _board(ctx)
    tz = board._tz()
    now = clock.now().astimezone(tz)
    said, day = str(args["until"]).strip(), str(args["day"]).strip()
    until = None
    try:
        at = time.fromisoformat(said) if said else time(9) if day else None
        on = day_arg(day, now.date()) if day else now.date()
    except ValueError as exc:
        raise ToolFailed("Times look like 21:00, and days like 2026-11-03.") from exc
    if at is not None:  # bug #104: "tomorrow afternoon" waited for 2 pm that day
        until = datetime(on.year, on.month, on.day, at.hour, at.minute, tzinfo=tz)
        if until <= now and not day:
            until += timedelta(days=1)
        elif until <= now:
            raise ToolFailed("That time has passed; ask when they'd like it.")
    try:
        return board.snooze(args["task_id"], until=until, by=ctx.member)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc


@tool(
    "set_task_plan",
    "Give a task an amount that steps up week by week, or stop it. plan is a short phrase: "
    "'1.3 miles, then 1.5, then up 0.25 a week, on Tuesdays', '20 minutes, up 5 a week up to "
    "45 minutes', '2 km, starting 2 Nov, on Mondays'; empty to stop. Its nudges then say the "
    "week's amount ('Go for a run (1.5 miles this week)'). For training plans and the like, "
    "not one-off numbers (those are part of the title or a step). Themi reads the saved plan "
    "back to them itself.",
    {"task_id": {"type": "integer"}, "plan": {"type": "string"}},
)
async def set_task_plan(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = _board(ctx)
    phrase = args["plan"].strip()
    try:
        plan = parse_plan(phrase, board._today()) if phrase else None
        task = board.set_progression(args["task_id"], ctx.member, plan)
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    except PermissionDenied as exc:
        raise ToolFailed("That task isn't theirs to change.") from exc
    except ValueError as exc:  # ProgressionError included: its message has an example
        raise ToolFailed(str(exc)) from exc
    if task.progression is None:
        return f"Task {task.id} ({task.title}) has no plan any more."
    # The read-back is built here from what was stored, and sent as it is.
    text = f"Saved for {task.title}: {plan_read_back(task.progression)}."
    week = task.progression.words_on(board._today())
    text += f" Now: {week}." if week else ""
    await ctx.services.outbox.send(ctx.member, text, priority=Priority.REPLY)
    return (
        f"Task {task.id} ({task.title}) has its plan, and it was read back to them already, "
        f'word for word: "{text}". Don\'t restate it; a short acknowledgement is enough, or '
        "ask if anything sounds wrong. If they asked for something that read-back doesn't "
        "show, say which part isn't set up and keep it with remember_fact."
    )


@tool(
    "set_task_medicine",
    "Mark a task as a medicine (or not) when they say so ('item 3 is my thyroid medicine'). "
    "A medicine's nudge asks 'Taken already?' with a Not sure button, and a 'not sure' never "
    "makes it done. Tasks whose titles name a pill, meds or a dose are marked already.",
    {"task_id": {"type": "integer"}, "medicine": {"type": "boolean"}},
)
async def set_task_medicine(ctx: ToolContext, args: dict[str, Any]) -> str:
    board = _board(ctx)
    try:
        task = board.get(args["task_id"])
    except NotFound as exc:
        raise ToolFailed("There's no task with that number.") from exc
    board.db.execute(
        "UPDATE tasks SET medicine = ? WHERE id = ?", (int(bool(args["medicine"])), task.id)
    )
    return f"{task.title}: {'a medicine' if args['medicine'] else 'not a medicine'}."
