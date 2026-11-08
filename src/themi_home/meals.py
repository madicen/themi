"""Zero-effort meals: two low-prep options from what the pantry has, as buttons.

`suggest_meals` asks the model (structured output) for two options, giving
it the pantry with what's close to its use-by date first and staples marked,
and leaving out anything that's run out. The options go to the person as two
buttons; picking one is recorded, and counts as a meal (35a).

35a, meal reminders:
- Meals are logged from chat (`log_meal`: "just had lunch"), from a meal idea they pick,
  or by a device (`Meals.log_eaten(..., source="device")`, the hook a device module calls).
- Each person's usual gap between meals is learned from the last month: the median of
  the gaps between meals on the same day, times 1.3, kept between a floor and a ceiling.
  Until there are enough gaps, a default stands in.
- The `meals.nudges` job sends one reminder per gap, during their waking hours, with two
  meal ideas: the gap counts from their last meal or from when their quiet hours ended,
  whichever is later. Someone who hasn't logged a meal in two days isn't reminded (they've
  stopped logging, or never started). "No meal reminders today" pauses them (kind "meal").
"""

from __future__ import annotations

import itertools
import json
import logging
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from themi import clock
from themi.accounts import Member
from themi.ai.errors import AIError
from themi.ai.settings import AITask
from themi.ai.types import CallKind
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.services import Services
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import in_quiet_hours, to_local, to_utc_iso
from themi.modules import Module, ModuleContext
from themi_home import home_groups
from themi_home.pantry import Pantry, PantryItem

log = logging.getLogger(__name__)

SOON_DAYS = 3  # "use soon" within this many days of its use-by date

# 35a: the usual gap between meals
DEFAULT_GAP = timedelta(hours=5)
GAP_FACTOR = 1.3
GAP_FLOOR = timedelta(hours=3)
GAP_CEILING = timedelta(hours=7)
MIN_GAPS = 5  # fewer gaps than this learned: the default
LEARN_OVER = timedelta(days=30)
STOPPED_LOGGING = timedelta(days=2)  # no meal logged for this long: no reminders
NUDGE_LASTS = timedelta(hours=1)  # a reminder held (a pause, the daily limit) lapses
NUDGE_EVERY = timedelta(minutes=15)
LATEST_LOG = timedelta(hours=12)  # "ate a while ago": at most this far back
SOURCES = ("chat", "suggestion", "device")
NUDGE_TEXT = "It's been a while since you last ate, as far as I know."
NUDGE_NO_IDEAS = NUDGE_TEXT + " A bite might help, whenever suits."

SYSTEM = """\
You suggest two zero-effort meals for a tired household: little prep, few
dishes, 20 minutes or less, nothing that needs a shop first. Build them from
the pantry list. Strongly prefer items marked "use soon" (closest first), then
shelf-stable staples. Make the two options different from each other. Titles
are short and plain ("Spinach and egg fried rice"). Steps are one short line.
"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "uses": {"type": "array", "items": {"type": "string"}},
                    "steps": {"type": "string"},
                    "minutes": {"type": "integer"},
                },
                "required": ["title", "uses", "steps", "minutes"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["options"],
    "additionalProperties": False,
}

OFFER_TEXT = "Two easy options, if either appeals:\n1. {first}\n2. {second}"
CHOSEN_TEXT = "{title} it is.\n> {steps}"  # quoted: recipe steps are kept as written
NO_IDEAS_TEXT = "Meal ideas aren't coming through at the moment (the AI couldn't be reached)."


def pantry_lines(items: list[PantryItem], today: date) -> list[str]:
    """The pantry as the model sees it: use-soon items first (soonest first), then staples,
    then the rest. Items that are out are left out."""

    def order(item: PantryItem) -> tuple[int, str, str]:
        if item.expiry is not None and (item.expiry - today).days <= SOON_DAYS:
            return (0, item.expiry.isoformat(), item.name)
        return (1 if item.staple else 2, "", item.name)

    lines = []
    for item in sorted((i for i in items if i.status != "out"), key=order):
        notes = []
        if item.expiry is not None:
            days = (item.expiry - today).days
            if days <= SOON_DAYS:
                when = "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"
                notes.append(f"use soon: by {when}")
            else:
                notes.append(f"use by {item.expiry.isoformat()}")
        if item.staple:
            notes.append("staple")
        if item.status == "low":
            notes.append("running low")
        lines.append(f"- {item.name}" + (f" ({', '.join(notes)})" if notes else ""))
    return lines


def usual_gap(times: list[datetime], timezone: str) -> timedelta:
    """A person's usual gap between meals: the median gap between meals on the same local
    day, times GAP_FACTOR, between GAP_FLOOR and GAP_CEILING. The overnight gap isn't a
    gap between meals. Fewer than MIN_GAPS gaps: DEFAULT_GAP."""
    ordered = sorted(times)
    gaps = [
        later - earlier
        for earlier, later in itertools.pairwise(ordered)
        if to_local(earlier, timezone).date() == to_local(later, timezone).date()
        and later > earlier
    ]
    if len(gaps) < MIN_GAPS:
        return DEFAULT_GAP
    median = timedelta(seconds=statistics.median(g.total_seconds() for g in gaps))
    return min(GAP_CEILING, max(GAP_FLOOR, median * GAP_FACTOR))


def waking_started(member: Member, moment: datetime, timezone: str) -> datetime | None:
    """When their latest quiet hours ended, at or before `moment` (None: no quiet hours)."""
    if member.quiet_start == member.quiet_end:
        return None
    local = to_local(moment, timezone)
    ended = local.replace(
        hour=member.quiet_end.hour, minute=member.quiet_end.minute, second=0, microsecond=0
    )
    return ended if ended <= local else ended - timedelta(days=1)


def _option(item: dict[str, Any]) -> dict[str, Any] | None:
    title = " ".join(str(item.get("title") or "").split())[:60]
    if not title:
        return None
    return {
        "title": title,
        "uses": [str(u) for u in item.get("uses") or []][:10],
        "steps": " ".join(str(item.get("steps") or "").split())[:300],
        "minutes": int(item.get("minutes") or 0),
    }


class Meals:
    def __init__(self, services: Services, pantry: Pantry) -> None:
        self.services = services
        self.pantry = pantry
        self.db = services.store.db

    def install(self) -> None:
        self.services.provide(keys.meals, self)
        self.services.button_handlers["meal"] = self.on_button
        self.services.tools.register(suggest_meals)
        self.services.tools.register(log_meal)

    @property
    def timezone(self) -> str:
        family = self.services.store.get_family()
        return family.timezone if family else "UTC"

    def prompt(self, request: str) -> str:
        today = to_local(clock.now(), self.timezone).date()
        lines = pantry_lines(self.pantry.items(), today)
        asked = f"They asked: {request}\n\n" if request.strip() else ""
        pantry = "\n".join(lines) if lines else "- (nothing recorded yet: suggest from staples)"
        return f"{asked}Today is {today.isoformat()}. The pantry:\n{pantry}"

    # ----- meals eaten (35a) ------------------------------------------------------------

    def log_eaten(
        self, member: Member, what: str = "", at: datetime | None = None, source: str = "chat"
    ) -> int:
        """A meal they ate. Devices call this with source "device" (the device hook)."""
        if source not in SOURCES:
            raise ValueError(f"a meal's source is one of {', '.join(SOURCES)}")
        now = clock.now()
        eaten = min(at or now, now)
        return self.db.execute(
            "INSERT INTO meals_eaten (member_id, eaten_at, what, source, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (member.id, to_utc_iso(eaten), " ".join(what.split())[:80], source, to_utc_iso(now)),
        )

    def eaten_since(self, member: Member, since: datetime) -> list[datetime]:
        rows = self.db.query(
            "SELECT eaten_at FROM meals_eaten WHERE member_id = ? AND eaten_at >= ? "
            "ORDER BY eaten_at",
            (member.id, to_utc_iso(since)),
        )
        return [datetime.fromisoformat(r["eaten_at"]) for r in rows]

    def last_meal(self, member: Member) -> datetime | None:
        at = self.db.scalar(
            "SELECT MAX(eaten_at) FROM meals_eaten WHERE member_id = ?", (member.id,)
        )
        return datetime.fromisoformat(at) if at else None

    def anyone_ate_since(self, since: datetime) -> bool:
        return bool(
            self.db.one("SELECT 1 FROM meals_eaten WHERE eaten_at >= ?", (to_utc_iso(since),))
        )

    def gap(self, member: Member, now: datetime | None = None) -> timedelta:
        now = now or clock.now()
        return usual_gap(self.eaten_since(member, now - LEARN_OVER), self.timezone)

    def nudge_due(self, member: Member, now: datetime) -> bool:
        """Whether a reminder is due: past their usual gap since their last meal (or since
        their quiet hours ended, if later), awake, still logging, none sent since then."""
        last = self.last_meal(member)
        if last is None or now - last > STOPPED_LOGGING:
            return False
        if in_quiet_hours(member, now, self.timezone):
            return False
        woke = waking_started(member, now, self.timezone)
        since = max(last, woke) if woke is not None else last
        if now < since + self.gap(member, now):
            return False
        sent = self.db.one(
            "SELECT 1 FROM meal_nudges WHERE member_id = ? AND sent_at >= ?",
            (member.id, to_utc_iso(since)),
        )
        return sent is None

    async def nudge(self) -> int:
        """Scheduler job: a reminder to each person past their usual gap. Returns how many."""
        now = clock.now()
        sent = 0
        for member in self.services.store.list_members():
            if not member.reachable or not self.nudge_due(member, now):
                continue
            self.db.execute(
                "INSERT INTO meal_nudges (member_id, sent_at) VALUES (?, ?)",
                (member.id, to_utc_iso(now)),
            )
            options = await self.suggest(
                member, lead=NUDGE_TEXT, priority=Priority.NORMAL, expires=now + NUDGE_LASTS
            )
            if options is None:
                await self.services.outbox.send(
                    member,
                    NUDGE_NO_IDEAS,
                    priority=Priority.NORMAL,
                    kind="meal",
                    expires=now + NUDGE_LASTS,
                )
            sent += 1
        return sent

    # ----- meal ideas -------------------------------------------------------------------

    async def suggest(
        self,
        member: Member,
        request: str = "",
        *,
        lead: str = "",
        priority: Priority = Priority.REPLY,
        expires: datetime | None = None,
    ) -> list[dict[str, Any]] | None:
        """Ask for two options and send them as buttons. None if the AI isn't available.
        `lead`: a line before them (a meal reminder's), sent at `priority`."""
        asked = CallKind.INTERACTIVE if priority is Priority.REPLY else CallKind.BACKGROUND
        try:
            response = await self.services.router.client_for(
                member.id, AITask.STRUCTURED_MISC
            ).structured(SYSTEM, self.prompt(request), SCHEMA, max_tokens=800, kind=asked)
        except AIError as exc:
            log.info("Meal ideas unavailable for member %s: %s", member.id, type(exc).__name__)
            return None
        options = [o for o in map(_option, response.data.get("options") or []) if o][:2]
        if len(options) < 2:
            return None
        suggestion_id = self.db.execute(
            "INSERT INTO meal_suggestions (member_id, options, created_at) VALUES (?, ?, ?)",
            (member.id, json.dumps(options), to_utc_iso(clock.now())),
        )
        text = OFFER_TEXT.format(
            first=f"{options[0]['title']} ({options[0]['minutes']} min)",
            second=f"{options[1]['title']} ({options[1]['minutes']} min)",
        )
        buttons = [
            Button(o["title"], "meal", {"suggestion": suggestion_id, "choice": n})
            for n, o in enumerate(options)
        ]
        ideas = self.services.maybe(keys.recipe_ideas)  # RC7: a cookbook recipe the pantry covers
        cookbook = ideas.offer(member) if ideas is not None else None
        if cookbook is not None:
            text = f"{text}\n{cookbook[0]}"
            buttons += cookbook[1]
        if lead:
            text = f"{lead}\n{text}"
        await self.services.outbox.send(
            member, text, priority=priority, kind="meal", buttons=buttons, expires=expires
        )
        return options

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        row = self.db.one(
            "SELECT * FROM meal_suggestions WHERE id = ? AND member_id = ?",
            (int(event.button.payload["suggestion"]), event.member.id),
        )
        if row is None:
            return
        choice = int(event.button.payload["choice"])
        options = json.loads(row["options"])
        if not 0 <= choice < len(options):
            return
        self.db.execute(
            "UPDATE meal_suggestions SET chosen = ?, chosen_at = ? WHERE id = ?",
            (choice, to_utc_iso(clock.now()), row["id"]),
        )
        option = options[choice]
        if row["chosen"] is None:  # 35a: what they picked is what they're eating
            self.log_eaten(event.member, option["title"], source="suggestion")
        if event.button.message_id is not None:
            await self.services.outbox.edit(
                event.member,
                event.button.message_id,
                CHOSEN_TEXT.format(title=option["title"], steps=option["steps"]),
            )


@tool(
    "suggest_meals",
    "Offer two zero-effort meal ideas from what's in the pantry, as buttons. Use when someone "
    "asks what to eat or make, or sounds too tired to cook; not after a pantry update "
    "(something to use up by Friday is update_pantry with its date, nothing more).",
    {
        "request": {
            "type": "string",
            "description": "Anything they said they want (e.g. 'something warm'), or ''.",
        }
    },
)
async def suggest_meals(ctx: ToolContext, args: dict[str, Any]) -> str:
    meals = ctx.services.maybe(keys.meals)
    assert meals is not None
    options = await meals.suggest(ctx.member, str(args.get("request") or ""))
    if options is None:
        return NO_IDEAS_TEXT
    titles = " / ".join(o["title"] for o in options)
    return (
        f"Sent two options as buttons ({titles}). They're already in the chat, so a short "
        "line is enough; don't list them again."
    )


@tool(
    "log_meal",
    "Note that they ate ('just had lunch', 'ate a sandwich an hour ago'), so meal reminders "
    "know when they last ate. what: the meal in a few words, or ''; minutes_ago: 0 for just "
    "now. Not a pantry change and not a spend (those are update_pantry and log_spending, "
    "which may come as well).",
    {
        "what": {"type": "string"},
        "minutes_ago": {"type": "integer"},
    },
)
async def log_meal(ctx: ToolContext, args: dict[str, Any]) -> str:
    meals = ctx.services.maybe(keys.meals)
    assert meals is not None
    ago = timedelta(minutes=max(0, int(args.get("minutes_ago") or 0)))
    if ago > LATEST_LOG:
        raise ToolFailed("Not noted: that's longer ago than meal reminders look back.")
    what = str(args.get("what") or "")
    at = clock.now() - ago
    meals.log_eaten(ctx.member, what, at)
    when = to_local(at, meals.timezone)
    meal = " ".join(what.split()) or "A meal"
    return f"Noted: {meal} at {when:%-I:%M %p}. A short line back is enough."


class MealsModule(Module):
    """Meal ideas from what the pantry has, and meal reminders (35a)."""

    name = "meals"
    title = "Meal ideas"
    summary = "Suggests meals from what's in the pantry, and reminds people to eat."
    tool_groups = (home_groups.PANTRY,)
    requires = ("pantry",)
    migrations = Path(__file__).parent / "meals_schema"  # 35a: the meal log

    def install(self, ctx: ModuleContext) -> None:
        meals = ctx.provide(Meals(ctx.services, ctx.get(Pantry)))
        meals.install()
        ctx.periodic("meals.nudges", NUDGE_EVERY, meals.nudge)
