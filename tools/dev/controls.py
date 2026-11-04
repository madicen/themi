"""D5b: the control panel's sections, each driving one or more of `make dev`'s fakes.

A `Section` names the fakes it drives, its `Action`s and a few lines of what those fakes
hold now. An `Action` has form `Field`s, a `run` that changes the fakes (on Themi's loop,
through `DevFakes.act`) and says what happened, and the checks that make Themi look at once.
The page (`control.html`) is drawn from `ControlPanel.schema()`, so a new connector adds
one `Section` here and nothing else.
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from tests.fakes.gmail_api import _Mailbox
from tests.fakes.gtasks_api import DEFAULT as MY_TASKS
from tests.fakes.roborock import CODE as ROBOROCK_CODE
from tests.fakes.roborock import EMAIL as ROBOROCK_EMAIL
from tests.fakes.safeway_helper import FakeSafewayHelper
from tests.fakes.thinq import TOKEN as THINQ_TOKEN
from tests.fakes.wiring import wall_list
from themi import clock
from themi.connectors.roborock import RoborockError
from themi.connectors.roborock.events import PARTS, problems, read_status, state_word
from tools.dev.fakes import ADDRESSES, DISHWASHER, DRYER, ROBOT, WASHER, Check, DevFakes
from tools.dev.scenes import SCENES, At, Do, describe

PEOPLE = tuple(ADDRESSES)  # ("Erin", "Husband")


class ControlError(ValueError):
    """Something the person can fix: a missing field, or nothing by that name."""


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"  # text, textarea, number, select, date or time
    options: tuple[str, ...] = ()
    default: str = ""
    required: bool = True


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    fields: tuple[Field, ...]
    run: Callable[[DevFakes, Values], str | Awaitable[str]]  # changes; says what happened
    # Then: periodic tasks by name, or reads of Themi's own (given the fakes).
    check: tuple[str | Callable[[DevFakes], Awaitable[object]], ...] = ()
    help: str = ""


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    uses: tuple[str, ...]  # the fakes it drives, by their names in `DevFakes.held()`
    actions: tuple[Action, ...]
    state: Callable[[DevFakes], list[str]] = field(default=lambda fakes: [])


class Values:
    """An action's form, checked against its fields."""

    def __init__(self, fields: tuple[Field, ...], raw: dict[str, Any]) -> None:
        self._values: dict[str, str] = {}
        for f in fields:
            value = str(raw.get(f.name, "") or f.default).strip()
            if f.required and not value:
                raise ControlError(f"{f.label} is needed")
            if f.kind == "select" and value and value not in f.options:
                raise ControlError(f"{f.label} can't be {value!r}")
            self._values[f.name] = value

    def __getitem__(self, name: str) -> str:
        return self._values[name]

    def number(self, name: str) -> float:
        try:
            return float(self._values[name])
        except ValueError:
            raise ControlError(f"{name} should be a number") from None

    def day(self, fakes: DevFakes, name: str = "date") -> date:
        """The date given, or today in the family's timezone."""
        if not self._values[name]:
            return clock.now().astimezone(_zone(fakes)).date()
        try:
            return date.fromisoformat(self._values[name])
        except ValueError:
            raise ControlError("the date should look like 2026-11-03") from None

    def at(self, fakes: DevFakes, day: str = "date", hour: str = "start") -> datetime:
        try:
            moment = time.fromisoformat(self._values[hour])
        except ValueError:
            raise ControlError("the time should look like 14:30") from None
        return datetime.combine(self.day(fakes, day), moment, _zone(fakes))


class ControlPanel:
    def __init__(self, fakes: DevFakes, sections: tuple[Section, ...] | None = None) -> None:
        self.fakes = fakes
        self.sections = SECTIONS if sections is None else sections

    def schema(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.id,
                "title": s.title,
                "actions": [
                    {
                        "id": a.id,
                        "label": a.label,
                        "help": a.help,
                        "fields": [
                            {
                                "name": f.name,
                                "label": f.label,
                                "kind": f.kind,
                                "options": list(f.options),
                                "default": f.default,
                                "required": f.required,
                            }
                            for f in a.fields
                        ],
                    }
                    for a in s.actions
                ],
            }
            for s in self.sections
        ]

    def state(self) -> dict[str, list[str]]:
        """What each section's fakes hold now, read on Themi's loop."""
        return self.fakes.read(lambda: {s.id: s.state(self.fakes) for s in self.sections})

    def act(self, section_id: str, action_id: str, raw: dict[str, Any]) -> str:
        """Run one action and its checks; returns what happened, as the transcript says it."""
        section = next((s for s in self.sections if s.id == section_id), None)
        action = next((a for a in section.actions if a.id == action_id), None) if section else None
        if section is None or action is None:
            raise ControlError(f"there's no {section_id}/{action_id}")
        values = Values(action.fields, raw)
        checks: list[Check] = [
            step if isinstance(step, str) else _bound(step, self.fakes) for step in action.check
        ]
        happened = self.fakes.act(lambda: action.run(self.fakes, values), checks)
        return f"{section.title}: {happened}"

    def scenes(self) -> list[dict[str, Any]]:
        return [
            {"name": sc.name, "about": sc.about, "steps": [describe(st) for st in sc.steps]}
            for sc in SCENES
        ]

    def run_scene(
        self, name: str, notice: Callable[[str], None], skip: Callable[[timedelta], object]
    ) -> list[str]:
        """Each step in turn, from another thread: actions as `act` runs them (each one told
        to `notice`), and skips through `skip`, after which Themi sends what came due.
        Stops at a step that fails, saying which. Returns what each action did."""
        scene = next((sc for sc in SCENES if sc.name == name), None)
        if scene is None:
            raise ControlError(f"there's no scene called {name!r}")
        notice(f"Scene: {scene.name}")
        done = []
        for n, step in enumerate(scene.steps, 1):
            try:
                if isinstance(step, Do):
                    done.append(self.act(step.section, step.action, step.values))
                    notice(done[-1])
                    continue
                if isinstance(step, At):
                    ahead = step.until(
                        self.fakes.read(lambda: clock.now().astimezone(_zone(self.fakes)))
                    )
                else:
                    ahead = timedelta(minutes=step.minutes)
                if ahead >= timedelta(minutes=1):
                    skip(ahead)
                    self.fakes.act(lambda: None, ("outbox.flush",))
            except ControlError as exc:
                raise ControlError(f"step {n} ({describe(step)}): {exc}") from exc
        return done


def _bound(read: Callable[[DevFakes], Awaitable[object]], fakes: DevFakes) -> Check:
    return lambda: read(fakes)


def _zone(fakes: DevFakes) -> ZoneInfo:
    assert fakes.app is not None
    family = fakes.app.store.get_family()
    return ZoneInfo(family.timezone if family else "America/Los_Angeles")


def _person(required: bool = True) -> Field:
    return Field("person", "Who", "select", PEOPLE, PEOPLE[0], required)


def _short(moment: str) -> str:
    """An event's start, briefly."""
    if "T" not in moment:
        return moment
    return datetime.fromisoformat(moment.replace("Z", "+00:00")).strftime("%a %d %b %H:%M")


# ----- email ------------------------------------------------------------------------------

TABS = {
    "Primary": (),
    "Promotions": ("CATEGORY_PROMOTIONS",),
    "Updates": ("CATEGORY_UPDATES",),
    "Social": ("CATEGORY_SOCIAL",),
    "Forums": ("CATEGORY_FORUMS",),
}
# name -> (from, subject, text, Gmail category labels)
EMAILS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "A bill due Friday": (
        "City Power <billing@citypower.example>",
        "Your bill is ready: $84.20 due Friday",
        "Your October electricity bill of $84.20 is due this Friday. Pay online or set up "
        "autopay from your account.",
        (),
    ),
    "A package delivered": (
        "Parcel Co <tracking@parcelco.example>",
        "Delivered: your package is at the front door",
        "Your package was delivered at 2:14 pm and left at the front door.",
        ("CATEGORY_UPDATES",),
    ),
    "A school notice": (
        "Maple Elementary <office@maple.example>",
        "Field trip permission slip due Thursday",
        "Please sign and return the permission slip for the aquarium trip by Thursday. "
        "The cost is $12, in cash or online.",
        (),
    ),
    "Urgent: an appointment moved": (
        "Dr. Patel's Office <appointments@patelfamilymed.example>",
        "Your appointment tomorrow has moved to 8:00 am",
        "We had to move your appointment tomorrow from 10:30 am to 8:00 am. Please call "
        "us today if that time doesn't work.",
        (),
    ),
    "Newsletter noise": (
        "ShopMart Deals <news@shopmart.example>",
        "This week's top 20 deals, just for you",
        "Save up to 40% on home goods, kitchen gadgets and more. Offers end Sunday.",
        ("CATEGORY_PROMOTIONS",),
    ),
    "A monthly statement": (
        "First Bank <statements@firstbank.example>",
        "Your October statement is ready",
        "Your statement for the account ending 4821 is ready to view online.",
        (),
    ),
}


async def _read_mail(fakes: DevFakes) -> None:
    """Every inbox read now (a poll waits 3 minutes after the last one)."""
    assert fakes.app is not None
    gmail, store = fakes.app.services.gmail, fakes.app.store
    if gmail is None:
        return
    for member in store.list_members():
        for account in store.linked_accounts(member.id):
            if account.enabled:
                await gmail.poll(account)


EMAIL_CHECK = (_read_mail, "email.triage")


def _deliver(
    fakes: DevFakes, person: str, sender: str, subject: str, text: str, tabs: tuple[str, ...]
) -> str:
    fakes.gmail.deliver(
        ADDRESSES[person],
        sender=sender,
        subject=subject,
        text=text,
        labels=("INBOX", "UNREAD", *tabs),
    )
    return f'"{subject}" from {sender.split(" <")[0]} to {person}'


def _send_preset(fakes: DevFakes, v: Values) -> str:
    sender, subject, text, tabs = EMAILS[v["preset"]]
    return _deliver(fakes, v["person"], sender, subject, text, tabs)


def _send_email(fakes: DevFakes, v: Values) -> str:
    return _deliver(fakes, v["person"], v["sender"], v["subject"], v["text"], TABS[v["tab"]])


def _subject(box: _Mailbox, gid: str) -> str:
    headers = box.messages[gid].payload.get("headers", [])
    return next((h["value"] for h in headers if h["name"] == "Subject"), "(no subject)")


def _email_state(fakes: DevFakes) -> list[str]:
    lines = []
    for person, address in ADDRESSES.items():
        box = fakes.gmail.mailboxes.get(address)
        inbox = [m for m in box.messages.values() if "INBOX" in m.labels] if box else []
        unread = sum("UNREAD" in m.labels for m in inbox)
        lines.append(f"{person} ({address}): {len(inbox)} in the inbox, {unread} unread")
        if box:
            lines += [f"  · {_subject(box, m.id)}" for m in inbox[-3:]]
    return lines


EMAIL = Section(
    "email",
    "Email",
    ("google", "gmail"),
    (
        Action(
            "preset",
            "Send a ready-made email",
            (_person(), Field("preset", "Email", "select", tuple(EMAILS), next(iter(EMAILS)))),
            _send_preset,
            EMAIL_CHECK,
        ),
        Action(
            "custom",
            "Send an email",
            (
                _person(),
                Field("sender", "From", default="A Friend <friend@example.com>"),
                Field("subject", "Subject"),
                Field("text", "Text", "textarea"),
                Field("tab", "Gmail tab", "select", tuple(TABS), "Primary"),
            ),
            _send_email,
            EMAIL_CHECK,
        ),
    ),
    _email_state,
)


# ----- calendar ---------------------------------------------------------------------------


def _primary_events(fakes: DevFakes, person: str) -> dict[str, dict[str, Any]]:
    box = fakes.gcal.calendars.get(ADDRESSES[person], {})
    primary = box.get("primary")
    return primary.events if primary else {}


def _event_named(fakes: DevFakes, person: str, title: str) -> dict[str, Any]:
    for event in _primary_events(fakes, person).values():
        if event["summary"].lower() == title.lower() and event["status"] != "cancelled":
            return event
    raise ControlError(f"{person}'s calendar has no event called {title!r}")


def _add_event(fakes: DevFakes, v: Values) -> str:
    start = v.at(fakes)
    end = start + timedelta(minutes=v.number("minutes"))
    extra: dict[str, Any] = {"location": v["place"]} if v["place"] else {}
    fakes.gcal.add_event(
        ADDRESSES[v["person"]], start.isoformat(), end.isoformat(), summary=v["title"], **extra
    )
    return f"{v['title']} on {v['person']}'s calendar, {start:%a %d %b %H:%M}"


def _cancel_event(fakes: DevFakes, v: Values) -> str:
    event = _event_named(fakes, v["person"], v["title"])
    event["status"] = "cancelled"
    return f"{event['summary']} cancelled in Google"


def _move_event(fakes: DevFakes, v: Values) -> str:
    event = _event_named(fakes, v["person"], v["title"])
    start = v.at(fakes)
    old_start = datetime.fromisoformat(event["start"]["dateTime"])
    old_end = datetime.fromisoformat(event["end"]["dateTime"])
    event["start"] = {"dateTime": start.isoformat()}
    event["end"] = {"dateTime": (start + (old_end - old_start)).isoformat()}
    return f"{event['summary']} moved in Google to {start:%a %d %b %H:%M}"


def _calendar_state(fakes: DevFakes) -> list[str]:
    lines = []
    for person, address in ADDRESSES.items():
        for calendar in fakes.gcal.calendars.get(address, {}).values():
            events = [e for e in calendar.events.values() if e["status"] != "cancelled"]
            events.sort(key=lambda e: str(e["start"]))
            name = "their calendar" if calendar.id == "primary" else calendar.summary
            shown = ", ".join(
                f"{e['summary']} ({_short(next(iter(e['start'].values())))})" for e in events[-4:]
            )
            lines.append(f"{person}, {name}: {shown or 'nothing'}")
    return lines


CALENDAR_CHECK = ("calendar.busy",)
CALENDAR = Section(
    "calendar",
    "Calendar",
    ("gcal",),
    (
        Action(
            "add",
            "Add an event",
            (
                _person(),
                Field("title", "Title", default="Dentist"),
                Field("date", "Date", "date", required=False),
                Field("start", "Starts", "time", default="10:00"),
                Field("minutes", "Minutes", "number", default="60"),
                Field("place", "Place", required=False),
            ),
            _add_event,
            CALENDAR_CHECK,
            "On their own calendar, as if added in Google.",
        ),
        Action(
            "move",
            "Move an event in Google",
            (
                _person(),
                Field("title", "Event"),
                Field("date", "New date", "date", required=False),
                Field("start", "New start", "time", default="15:00"),
            ),
            _move_event,
            CALENDAR_CHECK,
        ),
        Action(
            "cancel",
            "Cancel an event in Google",
            (_person(), Field("title", "Event")),
            _cancel_event,
            CALENDAR_CHECK,
        ),
    ),
    _calendar_state,
)


# ----- Google Home: speakers, Google Tasks and Keep -----------------------------------------


def _say_task(fakes: DevFakes, v: Values) -> str:
    fakes.gtasks.add(ADDRESSES[v["person"]], v["text"])
    return f'{v["person"]} said "{v["text"]}" to a speaker (Google Tasks)'


def _say_keep(fakes: DevFakes, v: Values) -> str:
    fakes.keep.put(ADDRESSES[v["person"]], v["text"])
    return f'{v["person"]} said "{v["text"]}" to a speaker (Keep\'s shopping list)'


def _keep_item(fakes: DevFakes, person: str, text: str) -> str:
    items = fakes.keep.user(ADDRESSES[person]).lists["Shopping list"]
    for item in items:
        if item.text.lower() == text.lower():
            return item.id
    raise ControlError(f"{person}'s Keep list has no {text!r}")


def _keep_tick(fakes: DevFakes, v: Values) -> str:
    fakes.keep.check(ADDRESSES[v["person"]], _keep_item(fakes, v["person"], v["text"]))
    return f'"{v["text"]}" ticked in {v["person"]}\'s Keep'


def _keep_delete(fakes: DevFakes, v: Values) -> str:
    fakes.keep.delete(ADDRESSES[v["person"]], _keep_item(fakes, v["person"], v["text"]))
    return f'"{v["text"]}" deleted from {v["person"]}\'s Keep'


def _home_state(fakes: DevFakes) -> list[str]:
    lines = []
    for person, address in ADDRESSES.items():
        for title in (MY_TASKS, "Themi"):
            if fakes.gtasks.has_list(address, title):
                tasks = fakes.gtasks.titles(address, title)
                lines.append(f"{person}, Google Tasks {title}: {', '.join(tasks) or 'empty'}")
        items = fakes.keep.user(address).lists["Shopping list"]
        shown = ", ".join(f"{'✓ ' if i.checked else ''}{i.text}" for i in items)
        lines.append(f"{person}, Keep shopping list: {shown or 'empty'}")
    return lines


TEXT = Field("text", "What")
HOME = Section(
    "home",
    "Google Home",
    ("gtasks", "keep"),
    (
        Action(
            "task",
            "Said to a speaker: a task",
            (_person(), TEXT),
            _say_task,
            ("google_tasks.inbox",),
            "Lands in Google Tasks' My Tasks, which Themi empties (GT1a).",
        ),
        Action(
            "keep",
            "Said to a speaker: shopping",
            (_person(), Field("text", "What", default="oat milk")),
            _say_keep,
            ("groceries.keep",),
            "Lands on Keep's shopping list (GK1).",
        ),
        Action("keep_tick", "Ticked in Keep", (_person(), TEXT), _keep_tick, ("groceries.keep",)),
        Action(
            "keep_delete", "Deleted in Keep", (_person(), TEXT), _keep_delete, ("groceries.keep",)
        ),
    ),
    _home_state,
)


# ----- the wall (Cozyla) ------------------------------------------------------------------

WALL_PEOPLE = ("Nobody", *PEOPLE)


def _member_uid(person: str) -> str | None:
    return None if person == "Nobody" else f"m-{person.lower()}"


def _todo(fakes: DevFakes, title: str) -> int:
    family = wall_list(fakes.cozyla)
    for todo in fakes.cozyla.in_list(family):
        if todo["todoTitle"].lower() == title.lower() and not todo["completeStatus"]:
            return todo["todoId"]
    raise ControlError(f"the wall's list has no open {title!r}")


def _add_todo(fakes: DevFakes, v: Values) -> str:
    fakes.cozyla.add_todo(wall_list(fakes.cozyla), v["title"], assignee=_member_uid(v["person"]))
    whose = "" if v["person"] == "Nobody" else f" for {v['person']}"
    return f'"{v["title"]}" added on the wall{whose}'


def _tick_todo(fakes: DevFakes, v: Values) -> str:
    fakes.cozyla.tick(_todo(fakes, v["title"]))
    return f'"{v["title"]}" ticked on the wall'


def _to_top(fakes: DevFakes, v: Values) -> str:
    todo_id = _todo(fakes, v["title"])
    top = max(float(t["profileDisplayOrder"]) for t in fakes.cozyla.todos.values())
    fakes.cozyla.edit(todo_id, displayOrder=top + 1, profileDisplayOrder=top + 1)
    return f'"{v["title"]}" moved to the top of the wall\'s list'


def _tick_chore(fakes: DevFakes, v: Values) -> str:
    chores = [
        c for c in fakes.cozyla.chores.values() if c["choreName"].lower() == v["chore"].lower()
    ]
    if not chores:
        raise ControlError(f"the chore chart has no {v['chore']!r}")
    day = v.day(fakes)
    uid = _member_uid(v["person"])
    assert uid is not None
    fakes.cozyla.tick_chore(chores[0]["choreUid"], uid, day)
    return f"{chores[0]['choreName']} ticked for {v['person']} on the chore chart, {day:%a %d %b}"


def _tick_routine(fakes: DevFakes, v: Values) -> str:
    uid = _member_uid(v["person"])
    routines = [
        r
        for r in fakes.cozyla.routines.values()
        if r["routineTitle"].lower() == v["item"].lower() and r["memberUid"] == uid
    ]
    if not routines:
        raise ControlError(f"{v['person']} has no routine item {v['item']!r} on the wall")
    day = v.day(fakes)
    fakes.cozyla.tick_routine(routines[0]["id"], day)
    return f"{routines[0]['routineTitle']} ticked in {v['person']}'s routine, {day:%a %d %b}"


def _wall_state(fakes: DevFakes) -> list[str]:
    cozyla = fakes.cozyla
    family = wall_list(cozyla)
    names = {m["memberUid"]: m["memberName"] for m in cozyla.members}
    todos = sorted(cozyla.in_list(family), key=lambda t: -float(t["profileDisplayOrder"]))
    open_ = [
        t["todoTitle"]
        + (f" ({names.get(t['assignMemberUid'], '?')})" if t["assignMemberUid"] else "")
        for t in todos
        if not t["completeStatus"]
    ]
    done = sum(1 for t in todos if t["completeStatus"])
    return [
        f"Family list: {', '.join(open_) or 'nothing open'}" + (f"; {done} done" if done else ""),
        "Chores: " + (", ".join(sorted(c["choreName"] for c in cozyla.chores.values())) or "none"),
        "Routines: "
        + (
            ", ".join(
                f"{r['routineTitle']} ({names.get(r['memberUid'], '?')})"
                for r in cozyla.routines.values()
            )
            or "none"
        ),
    ]


WALL = Section(
    "wall",
    "The wall",
    ("cozyla",),
    (
        Action(
            "add",
            "Add a to-do",
            (Field("title", "To-do"), Field("person", "For", "select", WALL_PEOPLE, "Nobody")),
            _add_todo,
            ("cozyla.sync",),
        ),
        Action("tick", "Tick a to-do", (Field("title", "To-do"),), _tick_todo, ("cozyla.sync",)),
        Action(
            "top", "Move a to-do to the top", (Field("title", "To-do"),), _to_top, ("cozyla.sync",)
        ),
        Action(
            "chore",
            "Tick a chore",
            (Field("chore", "Chore"), _person(), Field("date", "Day", "date", required=False)),
            _tick_chore,
            ("cozyla.chores",),
        ),
        Action(
            "routine",
            "Tick a routine item",
            (_person(), Field("item", "Item"), Field("date", "Day", "date", required=False)),
            _tick_routine,
            ("cozyla.routines",),
        ),
    ),
    _wall_state,
)


# ----- OurGroceries -----------------------------------------------------------------------


def _grocery(fakes: DevFakes, value: str) -> str:
    for item in fakes.ourgroceries.list.values():
        if item.value.lower() == value.lower():
            return item.id
    raise ControlError(f"OurGroceries has no {value!r}")


def _og_add(fakes: DevFakes, v: Values) -> str:
    fakes.ourgroceries.put(v["item"])
    return f'"{v["item"]}" added in the app'


def _og_cross(fakes: DevFakes, v: Values) -> str:
    fakes.ourgroceries.cross(_grocery(fakes, v["item"]))
    return f'"{v["item"]}" crossed off in the app'


def _og_delete(fakes: DevFakes, v: Values) -> str:
    fakes.ourgroceries.delete(_grocery(fakes, v["item"]))
    return f'"{v["item"]}" deleted in the app'


def _grocery_state(fakes: DevFakes) -> list[str]:
    items = fakes.ourgroceries.list.values()
    shown = ", ".join(f"{'✓ ' if i.crossed_off else ''}{i.value}" for i in items)
    return [f"{fakes.ourgroceries.list_name}: {shown or 'empty'}"]


ITEM = Field("item", "Item")
GROCERIES = Section(
    "groceries",
    "OurGroceries",
    ("ourgroceries",),
    (
        Action("add", "Add an item", (ITEM,), _og_add, ("groceries.mirror",)),
        Action("cross", "Cross an item off", (ITEM,), _og_cross, ("groceries.mirror",)),
        Action("delete", "Delete an item", (ITEM,), _og_delete, ("groceries.mirror",)),
    ),
    _grocery_state,
)


# ----- laundry (LG ThinQ) -----------------------------------------------------------------

MACHINES = {"Washer": WASHER, "Dryer": DRYER}
RUN_STATES = {"Running": "RUNNING", "Finished": "END", "Off": "POWER_OFF"}


def _laundry(fakes: DevFakes, v: Values) -> str:
    device, word = MACHINES[v["machine"]], RUN_STATES[v["state"]]
    fakes.thinq.set_run_state(device, word)  # what a read says from now on
    if any(c.connected() for c in fakes.thinq.connections):
        fakes.thinq.push_state(device, word)
    return f"{v['machine']}: {v['state'].lower()}"


def _run_state(state: Any) -> str:
    report = state[0] if isinstance(state, list) else state
    return str(report.get("runState", {}).get("currentState", "?"))


def _laundry_state(fakes: DevFakes) -> list[str]:
    pushes = any(c.connected() for c in fakes.thinq.connections)
    lines = [
        f"{device['deviceInfo']['alias']}: {_run_state(fakes.thinq.states[device_id])}"
        for device_id, device in fakes.thinq.devices.items()
    ]
    lines.append(f"Pushes {'connected' if pushes else 'not connected yet'}")
    if THINQ_TOKEN not in fakes.thinq.tokens:
        lines.append("LG turns the token down")
    return lines


LAUNDRY = Section(
    "laundry",
    "Laundry (LG)",
    ("thinq",),
    (
        Action(
            "state",
            "Set a machine",
            (
                Field("machine", "Machine", "select", tuple(MACHINES), "Washer"),
                Field("state", "State", "select", tuple(RUN_STATES), "Running"),
            ),
            _laundry,
            # A read while pushes aren't connected yet, then the push itself.
            ("devices.thinq", "devices.thinq_push"),
            "Sent as LG's push. Finished nudges someone half an hour on: skip ahead.",
        ),
    ),
    _laundry_state,
)


# ----- the dishwasher (Home Connect) --------------------------------------------------------

DISH_STATES = {"Running": "Run", "Finished": "Finished", "Ready": "Ready"}


def _dishwasher(fakes: DevFakes, v: Values) -> str:
    state = DISH_STATES[v["state"]]
    seconds = int(v.number("minutes") * 60) if state == "Run" else None
    fakes.home_connect.set_state(DISHWASHER, state, seconds_left=seconds)
    left = f", {int(v.number('minutes'))} minutes left" if state == "Run" else ""
    return f"Dishwasher: {v['state'].lower()}{left}"


def _dishwasher_state(fakes: DevFakes) -> list[str]:
    hc = fakes.home_connect
    revoked = [] if hc.refresh_tokens else ["Home Connect access revoked (Approve it again)"]
    return revoked + [
        f"{appliance['name']}: {hc.states.get(ha_id, '?')}"
        + (f", {hc.seconds_left[ha_id] // 60} min left" if ha_id in hc.seconds_left else "")
        for ha_id, appliance in hc.appliances.items()
    ]


DISHWASHER_SECTION = Section(
    "dishwasher",
    "Dishwasher (Bosch)",
    ("home_connect",),
    (
        Action(
            "state",
            "Set the dishwasher",
            (
                Field("state", "State", "select", tuple(DISH_STATES), "Running"),
                Field("minutes", "Minutes left (running)", "number", default="90"),
            ),
            _dishwasher,
            ("devices.dishwasher",),
        ),
    ),
    _dishwasher_state,
)


# ----- the vacuum (Roborock) ----------------------------------------------------------------

STATUSES = {  # label -> a payload in tests/fixtures/roborock
    "Cleaning": "cleaning",
    "Returning to the dock": "returning",
    "Docked": "docked",
    "Trapped": "trapped",
    "Main brush jammed": "main_brush_jammed",
    "Wheels jammed": "wheels_jammed",
    "Clean water tank empty": "clean_water_empty",
    "Dirty water tank full": "dirty_water_full",
    "Battery flat, away from the dock": "battery_flat_away",
    "Idle, away from the dock": "idle_away",
    "An unknown error": "unknown_error",
}
WORN = {name: (counter, lasts) for counter, (name, lasts) in PARTS.items()}


async def _read_robot(fakes: DevFakes) -> None:
    """The vacuum read now, as when someone asks how it's doing (a poll waits 5 minutes
    while it's docked and fine)."""
    assert fakes.app is not None
    watcher = fakes.app.services.roborock
    if watcher is None:
        return
    for device in watcher.devices():
        # Offline or signed out: what Themi does about it is the point.
        with contextlib.suppress(RoborockError):
            await watcher.read(device)


def _vacuum(fakes: DevFakes, v: Values) -> str:
    fakes.roborock.set_status(ROBOT, STATUSES[v["status"]])
    if v["room"]:
        fakes.roborock.rooms[ROBOT] = v["room"]
    where = f", in the {v['room']}" if v["room"] else ""
    return f"Robbie: {v['status'].lower()}{where}"


def _part(fakes: DevFakes, v: Values) -> str:
    counter, lasts = WORN[v["part"]]
    worn = v["how"] == "Worn out"
    fakes.roborock.set_parts(ROBOT, **{counter: lasts if worn else 0})
    return f"Robbie's {v['part']}: {'worn out' if worn else 'replaced'}"


def _vacuum_state(fakes: DevFakes) -> list[str]:
    rr = fakes.roborock
    lines = []
    for duid, robot in rr.robots.items():
        status = read_status(rr.statuses.get(duid, {}))
        trouble = "; ".join(problems(status).values())
        where = f", in the {rr.rooms[duid]}" if duid in rr.rooms else ""
        lines.append(
            f"{robot.name}: {state_word(status)}{where}"
            + (f" ({trouble})" if trouble else "")
            + (" (offline)" if duid in rr.offline_robots else "")
        )
        worn = [WORN_NAMES[c] for c, used in rr.parts.get(duid, {}).items() if _is_worn(c, used)]
        lines.append(f"Worn parts: {', '.join(worn) or 'none'}")
    if rr.expired:
        lines.append(f"Signed out: relink with {ROBOROCK_EMAIL} and the code {ROBOROCK_CODE}")
    return lines


WORN_NAMES = {counter: name for counter, (name, _) in PARTS.items()}


def _is_worn(counter: str, used: int) -> bool:
    return counter in PARTS and used >= PARTS[counter][1]


VACUUM = Section(
    "vacuum",
    "Vacuum (Roborock)",
    ("roborock",),
    (
        Action(
            "status",
            "Set Robbie's status",
            (
                Field("status", "Status", "select", tuple(STATUSES), "Trapped"),
                Field("room", "Room", required=False),
            ),
            _vacuum,
            (_read_robot,),
        ),
        Action(
            "part",
            "A part",
            (
                Field("part", "Part", "select", tuple(WORN), next(iter(WORN))),
                Field("how", "Now", "select", ("Worn out", "Replaced"), "Worn out"),
            ),
            _part,
            help="Themi reads the parts every 6 hours: skip ahead to see it.",
        ),
    ),
    _vacuum_state,
)


# ----- energy (dev only) --------------------------------------------------------------------

DAY_LEVELS = {"Low": -1.0, "Medium": 0.0, "High": 1.0}


def _member(fakes: DevFakes, person: str) -> Any:
    assert fakes.app is not None
    member = fakes.app.store.member_by_name(person)
    if member is None:
        raise ControlError(f"{person} isn't a member")
    return member


def _record(fakes: DevFakes, person: str, source: str, value: float, note: str) -> str:
    assert fakes.app is not None
    if not fakes.app.services.energy.record(_member(fakes, person), source, value, note):
        raise ControlError(f"{person} has that input switched off (/tracking)")
    return f"{person}: {source} {value:+.1f}" + (f" ({note})" if note else "")


def _day_level(fakes: DevFakes, v: Values) -> str:
    return _record(fakes, v["person"], "day_level", DAY_LEVELS[v["level"]], "control panel")


def _device_activity(fakes: DevFakes, v: Values) -> str:
    return _record(fakes, v["person"], "device_activity", v.number("value"), v["note"])


ENERGY = Section(
    "energy",
    "Energy (dev only)",
    (),
    (
        Action(
            "day",
            "Today's energy",
            (_person(), Field("level", "Level", "select", tuple(DAY_LEVELS), "Low")),
            _day_level,
            help="As if they said it's a low energy day. The Energy link shows the numbers.",
        ),
        Action(
            "device",
            "Device activity",
            (
                _person(),
                Field("value", "Value (-3 effort to 3 rest)", "number", default="-1"),
                Field("note", "Note", default="control panel"),
            ),
            _device_activity,
        ),
    ),
)


# ----- the Safeway helper (35d) -------------------------------------------------------------

SAFEWAY_OUTCOMES = {  # label -> the status the extension sends
    "Added": "added",
    "Out of stock": "out_of_stock",
    "Not found": "not_found",
    "Failed": "failed",
}


def _pair(fakes: DevFakes, v: Values) -> str:
    assert fakes.app is not None and fakes.app.services.safeway is not None
    fakes.safeway.token = fakes.app.services.safeway.connect(_member(fakes, v["person"]))
    return f"a helper connected by {v['person']}"


def _outcomes(text: str) -> dict[str, str]:
    """ "milk: not found" lines -> {"milk": "not_found"}."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        name, _, label = line.partition(":")
        status = {k.lower(): v for k, v in SAFEWAY_OUTCOMES.items()}.get(label.strip().lower())
        if not name.strip() or status is None:
            raise ControlError(f"write each exception as 'item: not found', not {line!r}")
        found[name.strip().lower()] = status
    return found


async def _answer_job(fakes: DevFakes, v: Values) -> str:
    """As the extension does: claim the next cart job and send what it found."""
    if fakes.web is None:
        raise ControlError("there's no website to reach the helper's API")
    usual = SAFEWAY_OUTCOMES[v["outcome"]]
    exceptions = _outcomes(v["except"])
    transport = httpx.ASGITransport(app=fakes.web)
    base = fakes.site_url or "http://themi.test"
    async with httpx.AsyncClient(transport=transport, base_url=base) as client:
        helper = FakeSafewayHelper(client, fakes.safeway.token)
        claimed = await helper.claim()
        if claimed.status_code == 401:
            raise ControlError("the helper isn't connected: pair it again")
        if claimed.status_code == 204:
            raise ControlError("no cart job is waiting")
        job = helper.jobs[-1]
        lines = []
        for n, item in enumerate(job["items"]):
            status = exceptions.get(item["name"].lower(), usual)
            product = item["product"] or {
                "id": str(970000000 + n),
                "name": f"{item['search'].title()} - 1 Each",
                "size": "1 Each",
                "price": 3.99,
            }
            lines.append(
                {
                    "name": item["name"],
                    "status": status,
                    "qty": item["qty"],
                    "product": product if status in ("added", "out_of_stock") else None,
                }
            )
        answered = await helper.answer(job["id"], {"items": lines, "stopped": False})
        if answered.status_code != 200:
            raise ControlError(f"Themi turned the answer down: {answered.text}")
    counts = Counter(line["status"].replace("_", " ") for line in lines)
    return f"cart job {job['id']} answered: " + ", ".join(f"{n} {s}" for s, n in counts.items())


def _safeway_state(fakes: DevFakes) -> list[str]:
    assert fakes.app is not None
    safeway = fakes.app.services.safeway
    if safeway is None:
        return ["Safeway isn't set up"]
    paired = safeway.helper_for(fakes.safeway.token) is not None if fakes.safeway.token else False
    lines = ["Helper: " + ("connected" if paired else "not connected (pair it)")]
    for row in fakes.app.db.query(
        "SELECT id, status, items FROM safeway_jobs WHERE status IN ('queued', 'claimed') "
        "ORDER BY id"
    ):
        names = ", ".join(i["name"] for i in json.loads(row["items"]))
        lines.append(f"Job {row['id']} ({row['status']}): {names}")
    return lines if len(lines) > 1 else [*lines, "No cart jobs waiting"]


SAFEWAY = Section(
    "safeway",
    "Safeway helper",
    ("safeway",),
    (
        Action(
            "answer",
            "Answer the next cart job",
            (
                Field("outcome", "Each item", "select", tuple(SAFEWAY_OUTCOMES), "Added"),
                Field(
                    "except",
                    "Except (one per line, e.g. milk: not found)",
                    "textarea",
                    required=False,
                ),
            ),
            _answer_job,
            help="As the Chrome extension does. Jobs come from asking Themi to fill the cart.",
        ),
        Action("pair", "Connect the helper again", (_person(),), _pair),
    ),
    _safeway_state,
)


# ----- travel (TomTom and OpenStreetMap) -------------------------------------------------

TRAVEL_KINDS = {
    "Finding a place (TomTom)": "geocode",
    "Drive time (TomTom)": "route",
    "Finding a place (OpenStreetMap)": "nominatim",
}


def _drive_time(fakes: DevFakes, v: Values) -> str:
    fakes.travel.minutes = int(v.number("minutes"))
    return f"drives take {fakes.travel.minutes} minutes"


def _place(fakes: DevFakes, v: Values) -> str:
    fakes.travel.place(v["address"], v.number("lat"), v.number("lon"))
    return f"{v['address']} can be found"


def _travel_fault(fakes: DevFakes, v: Values) -> str:
    fakes.travel.fail(TRAVEL_KINDS[v["kind"]], int(v.number("status")))
    return f"{v['kind']} fails next time ({int(v.number('status'))})"


def _travel_state(fakes: DevFakes) -> list[str]:
    places = ", ".join(sorted(fakes.travel.places)) or "none"
    return [f"Drive time: {fakes.travel.minutes} minutes", f"Places it can find: {places}"]


TRAVEL = Section(
    "travel",
    "Travel",
    ("travel",),
    (
        Action(
            "minutes",
            "Set the drive time",
            (Field("minutes", "Minutes", "number", default="30"),),
            _drive_time,
            ("travel.heads_up",),
        ),
        Action(
            "place",
            "Add a place it can find",
            (
                Field("address", "Address", default="Smile Dental"),
                Field("lat", "Latitude", "number", default="37.7749"),
                Field("lon", "Longitude", "number", default="-122.4194"),
            ),
            _place,
            ("travel.heads_up",),
            "An event's place must be found for its heads-up (K4).",
        ),
        Action(
            "fail",
            "Make the next lookup fail",
            (
                Field("kind", "Lookup", "select", tuple(TRAVEL_KINDS), "Drive time (TomTom)"),
                Field("status", "Status", "number", default="500"),
            ),
            _travel_fault,
        ),
    ),
    _travel_state,
)


# ----- faults: each section's way to fail, from the fakes' own switches --------------------

Fault = Callable[[DevFakes, Values], str | Awaitable[str]]


def _fault_action(
    faults: dict[str, Fault],
    check: tuple[str | Callable[[DevFakes], Awaitable[object]], ...],
    help: str = "",
    extra: tuple[Field, ...] = (),
) -> Action:
    def run(fakes: DevFakes, v: Values) -> str | Awaitable[str]:
        return faults[v["fault"]](fakes, v)

    field = Field("fault", "What goes wrong", "select", tuple(faults), next(iter(faults)))
    return Action("fault", "Make it fail", (field, *extra), run, check, help)


def _gmail_busy(fakes: DevFakes, v: Values) -> str:
    seconds = int(v.number("seconds"))
    fakes.gmail.fail("history", 429, retry_after=seconds)
    return f"Gmail answers the next read with 429 (Retry-After {seconds}s)"


def _gmail_down(fakes: DevFakes, v: Values) -> str:
    fakes.gmail.fail("history", 500)
    return "Gmail answers the next read with 500"


def _gmail_forgets(fakes: DevFakes, v: Values) -> str:
    fakes.gmail.expire_history(ADDRESSES[v["person"]])
    return f"Gmail forgot {v['person']}'s history (a 404, then a full sync)"


def _google_revoked(fakes: DevFakes, v: Values) -> str:
    address = ADDRESSES[v["person"]]
    fakes.google.revoke_everything_for(address)
    tokens = fakes.google.state.access_tokens
    for token in [t for t, a in tokens.items() if a == address]:
        del tokens[token]  # as if the hour they're good for had passed
    return f"{v['person']} removed Themi's access at Google"


def _thinq_back(fakes: DevFakes, v: Values) -> str:
    fakes.thinq.tokens.add(THINQ_TOKEN)
    for device in MACHINES.values():
        fakes.thinq.set_run_state(device, _run_state(fakes.thinq.states[device]))
    return f"LG works again (relink with the token {THINQ_TOKEN} if it was revoked)"


def _home_connect_again(fakes: DevFakes, v: Values) -> Awaitable[str]:
    async def relink() -> str:
        assert fakes.app is not None
        admin = next(m for m in fakes.app.store.list_members() if m.is_admin)
        await fakes.link_home_connect(fakes.app, admin, fakes.site_url)
        return "Home Connect approved again, as if relinked"

    return relink()


def _robot_back(fakes: DevFakes, v: Values) -> str:
    fakes.roborock.offline_robots.discard(ROBOT)
    return "Robbie is back online"


def _say(text: str, change: Callable[[DevFakes], object]) -> Fault:
    def run(fakes: DevFakes, v: Values) -> str:
        change(fakes)
        return text

    return run


FAULTS: dict[str, Action] = {
    "email": _fault_action(
        {
            "Gmail is busy (429)": _gmail_busy,
            "Gmail fails (500)": _gmail_down,
            "Gmail forgets the history": _gmail_forgets,
            "Access revoked at Google": _google_revoked,
        },
        (_read_mail,),
        "Relink on the website's Accounts page: the fake Google page asks which address "
        "(erin@gmail.com or husband@gmail.com).",
        (_person(), Field("seconds", "Retry-After (seconds)", "number", default="120")),
    ),
    "calendar": _fault_action(
        {
            "Reading events fails (500)": _say(
                "Google Calendar answers the next read with 500",
                lambda f: f.gcal.fail("list_events", 500),
            ),
            "Adding an event fails (500)": _say(
                "Google Calendar answers the next new event with 500",
                lambda f: f.gcal.fail("insert", 500),
            ),
        },
        CALENDAR_CHECK,
    ),
    "home": _fault_action(
        {
            "Google Tasks fails (503)": _say(
                "Google Tasks answers the next read with 503",
                lambda f: f.gtasks.fail("list", 503),
            ),
            "Keep fails the next read": _say(
                "Keep fails the next read", lambda f: f.keep.fail("items")
            ),
            "Keep loses the next save": _say(
                "Keep says the next save worked, and loses it", lambda f: f.keep.drop_next_write()
            ),
        },
        ("google_tasks.inbox", "groceries.keep"),
    ),
    "wall": _fault_action(
        {
            "Reading the to-dos fails": _say(
                "the wall answers the next to-do read with 500",
                lambda f: f.cozyla.fail("todosInfo/list", 500),
            ),
            "Every sign-in expires": _say(
                "the wall's sign-ins expired", lambda f: f.cozyla.expire_tokens()
            ),
        },
        ("cozyla.sync",),
    ),
    "groceries": _fault_action(
        {
            "Reading the list fails": _say(
                "OurGroceries fails the next read", lambda f: f.ourgroceries.fail("items")
            ),
            "Adding fails": _say(
                "OurGroceries fails the next add", lambda f: f.ourgroceries.fail("add")
            ),
        },
        ("groceries.mirror",),
    ),
    "laundry": _fault_action(
        {
            "The washer goes offline": _say(
                "the washer is offline", lambda f: f.thinq.offline(WASHER)
            ),
            "LG rate-limits (1306)": _say(
                "LG answers the next call with 1306", lambda f: f.thinq.limit()
            ),
            "LG revokes the token": _say("LG turned the token down", lambda f: f.thinq.revoke()),
            "LG works again": _thinq_back,
        },
        ("devices.thinq",),
        f"While pushes work, Themi reads LG only every so often. To relink: LG works again, "
        f"then the Accounts page with the token {THINQ_TOKEN} (US).",
    ),
    "dishwasher": _fault_action(
        {
            "It goes offline": _say(
                "the dishwasher is offline", lambda f: f.home_connect.offline(DISHWASHER)
            ),
            "Home Connect rate-limits (429)": _say(
                "Home Connect answers the next call with 429", lambda f: f.home_connect.limit()
            ),
            "Access revoked": _say(
                "Home Connect's access was revoked", lambda f: f.home_connect.revoke()
            ),
            "Approve it again": _home_connect_again,
        },
        ("devices.dishwasher",),
        "Home Connect's sign-in page can't be opened here, so relink with Approve it again.",
    ),
    "vacuum": _fault_action(
        {
            "Robbie goes offline": _say("Robbie is offline", lambda f: f.roborock.offline(ROBOT)),
            "The sign-in expires": _say(
                "Roborock's sign-in expired", lambda f: f.roborock.expire()
            ),
            "Robbie is back online": _robot_back,
        },
        (_read_robot,),
        f"Relink on the Accounts page with {ROBOROCK_EMAIL} and the code {ROBOROCK_CODE}.",
    ),
}


def _with_faults(section: Section) -> Section:
    fault = FAULTS.get(section.id)
    return replace(section, actions=(*section.actions, fault)) if fault else section


SECTIONS = tuple(
    _with_faults(s)
    for s in (
        EMAIL,
        CALENDAR,
        HOME,
        WALL,
        GROCERIES,
        LAUNDRY,
        DISHWASHER_SECTION,
        VACUUM,
        SAFEWAY,
        TRAVEL,
        ENERGY,
    )
)
