"""D5b: the control panel's sections, each driving one or more of `make dev`'s fakes.

A `Section` names the fakes it drives, its `Action`s and a few lines of what those fakes
hold now. An `Action` has form `Field`s, a `run` that changes the fakes (on Themi's loop,
through `DevFakes.act`) and says what happened, and the checks that make Themi look at once.
The page (`control.html`) is drawn from `ControlPanel.schema()`, so a new connector adds
one `Section` here and nothing else.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tests.fakes.gmail_api import _Mailbox
from tests.fakes.gtasks_api import DEFAULT as MY_TASKS
from tests.fakes.wiring import wall_list
from themi import clock
from themi.connectors.roborock.events import PARTS, problems, read_status, state_word
from tools.dev.fakes import ADDRESSES, DISHWASHER, DRYER, ROBOT, WASHER, Check, DevFakes

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
    run: Callable[[DevFakes, Values], str]  # changes the fakes; returns what happened
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
    return [*lines, f"Pushes {'connected' if pushes else 'not connected yet'}"]


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
    return [
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

SECTIONS = (EMAIL, CALENDAR, HOME, WALL, GROCERIES, LAUNDRY, DISHWASHER_SECTION, VACUUM, ENERGY)
