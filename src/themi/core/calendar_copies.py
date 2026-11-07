"""A calendar of theirs shown on the family calendar (F34f, Erin's idea #175).

"Michael's work calendar would show all the details on his private calendar, but on the
family calendar the time would simply be blocked off using generic labels such as 'Michael
work meeting' or 'Michael focus block'."

A rule per calendar of theirs (on the Calendars page): shown on the family calendar as
Full details (title and place), Title only, A label, or Busy only. Themi keeps a copy of
each of its events there, in step at every read: moved, changed or deleted at the source,
the copy follows. A label is picked from the event alone, here, without a model: other
guests is a meeting, a focus or hold block is a focus block, anything else is busy.

A copy never carries the source's notes or guests, and its place only at Full details. It
carries `copy:<source event id>` in its private extended properties, so it's never copied
back and never taken for a twin (F34e), and it's free time, so nobody else looks busy
because of it.

Setting a rule up is the yes: one `calendar_write` action (the family calendar's category).
Once it's on, keeping its copies in step needs no more asking, as maintenance's events do.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.connectors.gcal import CalendarNotFound, event_id
from themi.connectors.gcal.busy import TASK_BLOCK
from themi.core import keys
from themi.core.events import When, _times
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

CATEGORY = "calendar_write"  # the family calendar's category (26)
SHOW = "calendar.show_on_family"
COPY = "copy:"
LEVELS = ("full", "title", "label", "busy")
LEVEL_WORDS = {"full": "full details", "title": "titles only", "label": "labels",
               "busy": "busy only"}  # fmt: skip
BUSY_TITLE = "Busy"
FOCUS = re.compile(
    r"\b(?:focus\w*|deep work|heads?[- ]down|hold|block(?:ed)?|do not (?:book|schedule)|dnb|"
    r"no meetings?|prep time|work time)\b",
    re.IGNORECASE,
)
KINDS = ("meeting", "focus", "other")


def default_labels(name: str) -> dict[str, str]:
    return {"meeting": f"{name} work meeting", "focus": f"{name} focus block",
            "other": f"{name} busy"}  # fmt: skip


def kind_of(title: str, guests: int) -> str:
    """Which label an event gets, from its own title and guests, never sent anywhere."""
    if guests:
        return "meeting"
    return "focus" if FOCUS.search(title) else "other"


@dataclass(frozen=True)
class Rule:
    id: int
    member_id: int
    account_id: int
    calendar_id: str
    name: str
    level: str
    status: str


class CalendarCopies:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.provide(keys.calendar_copies, self)
        s.autonomy.executors.register(SHOW)(self._execute_show)
        if s.maybe(keys.calendars) is not None:
            s.get(keys.calendars).listeners.append(self.sync)

    # ----- rules ------------------------------------------------------------------------

    def rules(self, member: Member) -> list[Rule]:
        rows = self.db.query(
            "SELECT * FROM calendar_shown_on WHERE member_id = ? ORDER BY name", (member.id,)
        )
        return [_rule(r) for r in rows]

    def labels(self, member: Member) -> dict[str, str]:
        raw = self.db.scalar("SELECT calendar_labels FROM members WHERE id = ?", (member.id,))
        own = json.loads(raw) if raw else {}
        usual = default_labels(member.name)
        return {k: str(own.get(k) or usual[k]).strip()[:60] or usual[k] for k in KINDS}

    def set_labels(self, member: Member, labels: dict[str, str]) -> None:
        usual = default_labels(member.name)
        kept = {k: v.strip()[:60] for k, v in labels.items() if k in KINDS and v.strip()}
        kept = {k: v for k, v in kept.items() if v != usual[k]}
        self.db.execute(
            "UPDATE members SET calendar_labels = ? WHERE id = ?",
            (json.dumps(kept) if kept else None, member.id),
        )

    async def set_rule(
        self, member: Member, account_id: int, calendar_id: str, name: str, level: str
    ) -> str:
        """Show that calendar on the family calendar at `level`, or 'off'. Returns a line
        for them. A new or changed rule is staged once; its yes covers the copies."""
        if level not in (*LEVELS, "off"):
            raise ValueError(f"the levels are {', '.join(LEVELS)} or off")
        own = {a.id for a in self.services.store.linked_accounts(member.id)}
        if account_id not in own:
            raise ValueError("that calendar isn't one of theirs")
        existing = self.db.one(
            "SELECT * FROM calendar_shown_on WHERE account_id = ? AND calendar_id = ?",
            (account_id, calendar_id),
        )
        if level == "off":
            if existing is not None:
                await self._remove_copies(_rule(existing))
                self.db.execute("DELETE FROM calendar_shown_on WHERE id = ?", (existing["id"],))
            return f"{name} isn't shown on the family calendar now."
        target = await self._target()
        if target is not None and (target[0], target[1]) == (account_id, calendar_id):
            raise ValueError("that's the family calendar itself")
        if existing is not None and existing["level"] == level and existing["status"] == "on":
            return f"{name} is shown on the family calendar as {LEVEL_WORDS[level]} already."
        if existing is None:
            rule_id = self.db.execute(
                "INSERT INTO calendar_shown_on (member_id, account_id, calendar_id, name, level, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (member.id, account_id, calendar_id, name[:120], level, to_utc_iso(clock.now())),
            )
        else:
            rule_id = existing["id"]
            self.db.execute(
                "UPDATE calendar_shown_on SET level = ?, name = ?, status = 'waiting' WHERE id = ?",
                (level, name[:120], rule_id),
            )
        outcome = await self.services.autonomy.stage(
            CATEGORY, member, f"Show {name} on the family calendar as {LEVEL_WORDS[level]}",
            {"rule": rule_id}, SHOW, requested=True,
        )  # fmt: skip
        self.db.execute(
            "UPDATE calendar_shown_on SET action_id = ? WHERE id = ?", (outcome.action.id, rule_id)
        )
        return str(outcome.message)

    async def _execute_show(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        row = self.db.one("SELECT * FROM calendar_shown_on WHERE id = ?", (int(payload["rule"]),))
        if row is None:
            return "That calendar isn't shown on the family calendar any more."
        self.db.execute("UPDATE calendar_shown_on SET status = 'on' WHERE id = ?", (row["id"],))
        rule = _rule({**row, "status": "on"})
        await self._sync_rule(ctx.member, rule)
        return f"{rule.name} shows on the family calendar as {LEVEL_WORDS[rule.level]}."

    # ----- the copies -------------------------------------------------------------------

    async def sync(self, member: Member) -> int:
        """The calendar read's listener: each rule's copies in step. Returns how many copies
        were written or taken away."""
        changed = 0
        for rule in self.rules(member):
            if rule.status != "on":
                continue
            try:
                changed += await self._sync_rule(member, rule)
            except Exception:
                log.exception("Couldn't keep calendar copies in step for rule %s", rule.id)
        return changed

    async def _target(self) -> tuple[int, str] | None:
        sync = self.services.maybe(keys.calendar)
        if sync is None or sync.account() is None:
            return None
        target = await sync.target()
        return target.account.id, target.calendar_id

    async def _sync_rule(self, member: Member, rule: Rule) -> int:
        target = await self._target()
        sync = self.services.maybe(keys.calendar)
        if target is None or sync is None or target == (rule.account_id, rule.calendar_id):
            return 0
        member = self.services.store.get_member(member.id)
        labels = self.labels(member)
        tz = self._tz()
        desired: dict[str, tuple[dict[str, Any], str]] = {}
        for row in self.db.query(
            "SELECT * FROM calendar_entries WHERE account_id = ? AND calendar_id = ?",
            (rule.account_id, rule.calendar_id),
        ):
            if str(row["source"] or "").startswith((COPY, TASK_BLOCK)):
                continue  # a copy is never copied again; Themi's time blocks stay where they are
            when = When(
                datetime.fromisoformat(row["starts_at"]),
                datetime.fromisoformat(row["ends_at"]),
                bool(row["all_day"]),
            )
            body = {
                "summary": _title(rule.level, row, labels),
                "location": row["location"] if rule.level == "full" else "",
                **_times(when, tz),
                "transparency": "transparent",
                "extendedProperties": {"private": {"themi": f"{COPY}{row['event_id']}"}},
            }
            desired[row["event_id"]] = (body, row["starts_at"])
        existing = {
            r["source_event_id"]: r
            for r in self.db.query("SELECT * FROM calendar_copies WHERE rule_id = ?", (rule.id,))
        }
        changed = 0
        for source, (body, starts) in desired.items():
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
            row = existing.get(source)
            if (
                row is not None
                and row["hash"] == digest
                and (row["account_id"], row["calendar_id"]) == target
            ):
                continue
            if row is None:
                copy_id = self.db.execute(
                    "INSERT INTO calendar_copies (rule_id, source_event_id, account_id, "
                    "calendar_id, starts_at) VALUES (?, ?, ?, ?, ?)",
                    (rule.id, source, *target, starts),
                )
                eid = event_id("copy", copy_id, self._seed())
            else:
                copy_id, eid = row["id"], row["event_id"]
            await sync.upsert(target[0], target[1], eid, body)
            self.db.execute(
                "UPDATE calendar_copies SET event_id = ?, hash = ?, starts_at = ?, account_id = ?, "
                "calendar_id = ? WHERE id = ?",
                (eid, digest, starts, *target, copy_id),
            )
            changed += 1
        now = to_utc_iso(clock.now())
        for source, row in existing.items():
            if source in desired or row["starts_at"] <= now:
                continue  # still there, or over (past copies stay as they were)
            await self._delete(row)
            changed += 1
        return changed

    async def _delete(self, row: dict[str, Any]) -> None:
        sync = self.services.maybe(keys.calendar)
        if sync is not None and row["event_id"]:
            with contextlib.suppress(CalendarNotFound):  # gone already
                await sync.client(row["account_id"]).delete_event(
                    row["calendar_id"], row["event_id"]
                )
        self.db.execute("DELETE FROM calendar_copies WHERE id = ?", (row["id"],))
        self.db.execute("DELETE FROM calendar_entries WHERE event_id = ?", (row["event_id"],))

    async def _remove_copies(self, rule: Rule) -> None:
        now = to_utc_iso(clock.now())
        for row in self.db.query(
            "SELECT * FROM calendar_copies WHERE rule_id = ? AND starts_at > ?", (rule.id, now)
        ):
            await self._delete(row)

    def _seed(self) -> str:
        family = self.services.store.get_family()
        return family.created_at.isoformat() if family else "themi"

    def _tz(self) -> Any:
        from zoneinfo import ZoneInfo

        family = self.services.store.get_family()
        return ZoneInfo(family.timezone if family else "UTC")


def _title(level: str, row: dict[str, Any], labels: dict[str, str]) -> str:
    if level in ("full", "title"):
        return str(row["title"])
    if level == "label":
        return labels[kind_of(str(row["title"]), int(row["guests"] or 0))]
    return BUSY_TITLE


def _rule(row: dict[str, Any]) -> Rule:
    return Rule(
        row["id"], row["member_id"], row["account_id"], row["calendar_id"], row["name"],
        row["level"], row["status"],
    )  # fmt: skip
