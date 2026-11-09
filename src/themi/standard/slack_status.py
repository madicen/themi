"""SL6: Themi's own state, written to the person's Slack status and Do Not Disturb.

Themi is the source of truth and never reads Slack's status back. Each minute it works out
where the person is, in this order:

- focus: a block of time Themi put on their calendar for a task (K5) is on now. Status
  "Focusing", and Do Not Disturb until it ends.
- meeting: a timed, busy event with other people or a video link is on now. Status "In a
  meeting" until it ends.
- quiet: their quiet hours. Do Not Disturb until they end.
- none.

Slack is written only when that state changes, as a side effect through the trust tiers
(`slack_status`, automatic to start). A status carries Slack's own expiration, so it clears
itself on time; Themi clears what it set only when the state ended early (an event moved
or deleted), never a status the person set by hand in between.

Slack lets only a person's own token change their status, so this needs the user token
(`xoxp-`) of whoever installed the app, and works for that one person.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.autonomy.engine import ExecutionContext
from themi.channels.slack_api import SlackApi, SlackError
from themi.localtime import in_quiet_hours, quiet_hours_end, to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

log = logging.getLogger(__name__)

CATEGORY = "slack_status"
EXECUTOR = "slack_status"
FOCUS = ("Focusing", ":dart:")
MEETING = ("In a meeting", ":calendar:")


@dataclass(frozen=True)
class State:
    kind: str  # focus, meeting, quiet, none
    until: datetime | None = None

    @property
    def status(self) -> tuple[str, str] | None:
        return {"focus": FOCUS, "meeting": MEETING}.get(self.kind)

    @property
    def dnd(self) -> bool:
        return self.kind in ("focus", "quiet")


NONE = State("none")


class SlackStatus:
    def __init__(self, services: Services, user_api: SlackApi) -> None:
        self.services = services
        self.db = services.store.db
        self.api = user_api
        self._user: str | None = None  # whose token it is (auth.test), once known

    # ----- whose -------------------------------------------------------------------------

    async def member(self) -> Member | None:
        """The member the user token belongs to, when they're paired on Slack."""
        if self._user is None:
            try:
                who = await self.api.call("auth.test")
            except SlackError as exc:
                log.warning("Slack's user token didn't work (%s); no status sync", exc.error)
                return None
            self._user = str(who.get("user_id") or "")
        return self.services.store.member_by_identity("slack", self._user) if self._user else None

    # ----- Themi's state -----------------------------------------------------------------

    def state(self, member: Member, now: datetime) -> State:
        stamp = to_utc_iso(now)
        block = self.db.scalar(
            "SELECT MAX(ends_at) FROM task_blocks WHERE member_id = ? AND removed_at IS NULL "
            "AND starts_at <= ? AND ends_at > ?",
            (member.id, stamp, stamp),
        )
        if block:
            return State("focus", datetime.fromisoformat(block))
        if member.tracks("calendar"):
            meeting = self.db.scalar(
                "SELECT MAX(ends_at) FROM calendar_entries WHERE member_id = ? AND busy = 1 "
                "AND all_day = 0 AND (guests > 0 OR video = 1) AND starts_at <= ? "
                "AND ends_at > ?",
                (member.id, stamp, stamp),
            )
            if meeting:
                return State("meeting", datetime.fromisoformat(meeting))
        family = self.services.store.get_family()
        timezone = family.timezone if family else "UTC"
        if in_quiet_hours(member, now, timezone):
            return State("quiet", quiet_hours_end(member, now, timezone))
        return NONE

    def _last(self, member: Member) -> tuple[State, bool, bool]:
        row = self.db.one("SELECT * FROM slack_status WHERE member_id = ?", (member.id,))
        if row is None:
            return NONE, False, False
        until = datetime.fromisoformat(row["until"]) if row["until"] else None
        return State(row["state"], until), bool(row["set_status"]), bool(row["set_dnd"])

    # ----- each minute -------------------------------------------------------------------

    async def tick(self) -> int:
        """Write a change of state to Slack. 1 when one was staged, else 0."""
        member = await self.member()
        if member is None:
            return 0
        now = clock.now()
        wanted = self.state(member, now)
        last, had_status, had_dnd = self._last(member)
        if (wanted.kind, wanted.until) == (last.kind, last.until):
            return 0
        early = last.until is not None and now < last.until  # ended before Slack clears it
        payload: dict[str, Any] = {}
        if (status := wanted.status) is not None:
            assert wanted.until is not None
            payload["status"] = {"text": status[0], "emoji": status[1],
                                 "expiration": int(wanted.until.timestamp())}  # fmt: skip
        elif had_status and early:
            payload["status"] = None  # clear what Themi set
        if wanted.dnd:
            assert wanted.until is not None
            payload["dnd_minutes"] = max(1, math.ceil((wanted.until - now).total_seconds() / 60))
        elif had_dnd and early:
            payload["dnd_minutes"] = 0  # end what Themi set
        self.db.execute(
            "INSERT INTO slack_status (member_id, state, until, set_status, set_dnd, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (member_id) DO UPDATE SET "
            "state = excluded.state, until = excluded.until, set_status = excluded.set_status, "
            "set_dnd = excluded.set_dnd, updated_at = excluded.updated_at",
            (member.id, wanted.kind, to_utc_iso(wanted.until) if wanted.until else None,
             int(wanted.status is not None), int(wanted.dnd), to_utc_iso(now)),
        )  # fmt: skip
        if not payload:
            return 0
        await self.services.autonomy.stage(
            CATEGORY, member, _summary(wanted), payload, EXECUTOR, expires=wanted.until
        )
        return 1

    # ----- the side effect ---------------------------------------------------------------

    async def execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        """Set or clear the status and Do Not Disturb; doing it twice is the same as once."""
        done = []
        if "status" in payload:
            status = payload["status"]
            profile = (
                {"status_text": status["text"], "status_emoji": status["emoji"],
                 "status_expiration": status["expiration"]}
                if status
                else {"status_text": "", "status_emoji": "", "status_expiration": 0}
            )  # fmt: skip
            await self.api.call("users.profile.set", profile=profile)
            done.append("status set" if status else "status cleared")
        if "dnd_minutes" in payload:
            minutes = int(payload["dnd_minutes"])
            if minutes > 0:
                await self.api.call("dnd.setSnooze", num_minutes=minutes)
                done.append(f"Do Not Disturb for {minutes} min")
            else:
                await self.api.call("dnd.endSnooze")
                done.append("Do Not Disturb ended")
        return ", ".join(done) or "nothing to change"


def _summary(state: State) -> str:
    words = {
        "focus": "Show Focusing in Slack and turn on Do Not Disturb until the block ends",
        "meeting": "Show In a meeting in Slack until it ends",
        "quiet": "Turn on Do Not Disturb in Slack for your quiet hours",
        "none": "Clear the Slack status and Do Not Disturb Themi set",
    }
    return words[state.kind]
