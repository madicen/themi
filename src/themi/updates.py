"""Updating and restarting Themi's server from the website (D3a).

Themi runs in a container, so it can't update itself, and it never gets the Docker socket:
that would be root on the host, and Themi reads emails and web pages. So it only asks. A
request goes through the trust tiers (category `server_control`) and is written as
`request.json` in a folder shared with the host (`THEMI_CONTROL_DIR`). The host's runner
(`deploy/control.sh`, D3b) moves it aside, runs `update.sh`, and writes `result.json`;
it keeps `runner.json` to say it's installed and which release is the newest.

    request.json  {"id", "action": "update" | "restart", "version": "newest" | "current",
                   "asked_by", "asked_at"}
    result.json   {"id", "state": "running" | "done" | "failed" | "refused",
                   "from", "to", "detail", "finished_at"}
    runner.json   {"installed_at", "newest", "checked_at"}

Files the runner writes are data: only known fields are read, versions must look like
versions, and what people are told is Themi's own words.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from themi import __version__, clock
from themi.accounts import Member, NotFound
from themi.autonomy import ExecutionContext
from themi.channels.outbox import Priority
from themi.core.services import Services
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

CATEGORY = "server_control"
EXECUTOR = "server.request"
ACTIONS = ("update", "restart")
SUMMARIES = {"update": "Update Themi to the newest release", "restart": "Restart Themi"}
# A request nothing picked up in this long lapses, so another can be asked for.
PICK_UP_WITHIN = timedelta(minutes=15)
# A run that hasn't finished in this long is taken as lost (update.sh waits 3 minutes).
FINISH_WITHIN = timedelta(minutes=30)
RECENT = 5
DETAIL_CHARS = 2000
VERSION = re.compile(r"^(latest|dev|\d+\.\d+(\.\d+)?)$")
OPEN_STATES = ("waiting", "running")
FINISHED_STATES = ("done", "failed", "refused")

TEXT = {
    "updated": "Themi is now on {to} (was {frm}).",
    "newest": "Themi is already on {to}, the newest release, so nothing changed.",
    "restarted": "Themi restarted on {to}.",
    "updated_to": "Themi is now on {to}.",
    "still_on": "The update to {to} didn't work, so Themi is still on {frm}. The "
    "Development page has the end of the log.",
    "failed": "The {action} didn't work. The Development page has the end of the log.",
    "refused": "The server's runner turned down the {action}. The Development page says why.",
    "lapsed": "Nothing on the server picked up the {action}, so it was dropped. Is the "
    "runner installed? (docs/DEPLOY.md, section 9)",
}


class ControlError(Exception):
    """Why a request can't be made now, in words for the page."""


@dataclass(frozen=True)
class ServerRequest:
    id: int
    action: str
    member_id: int | None
    state: str
    from_version: str | None
    to_version: str | None
    detail: str | None
    asked_at: datetime
    finished_at: datetime | None

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES


@dataclass(frozen=True)
class ServerState:
    configured: bool
    running_version: str
    runner_installed: bool
    newest: str | None
    newest_checked_at: datetime | None
    in_progress: ServerRequest | None
    recent: list[ServerRequest]


def _request_from_row(row: dict[str, Any]) -> ServerRequest:
    return ServerRequest(
        id=row["id"],
        action=row["action"],
        member_id=row["member_id"],
        state=row["state"],
        from_version=row["from_version"],
        to_version=row["to_version"],
        detail=row["detail"],
        asked_at=datetime.fromisoformat(row["asked_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
    )


def _version(value: Any) -> str | None:
    return value if isinstance(value, str) and VERSION.match(value) else None


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else None


class ServerControl:
    def __init__(self, services: Services, folder: Path | None) -> None:
        """`folder` None: updates from the website aren't set up."""
        self.services = services
        self.db = services.store.db
        self.folder = folder

    def install(self) -> None:
        self.services.autonomy.executors.register(EXECUTOR)(self._write_request)

    # ----- asking -------------------------------------------------------------

    async def request(self, action: str, member: Member) -> str:
        """Ask the host for an update or a restart. Returns what to tell the person."""
        if action not in ACTIONS:
            raise ControlError(f"There's no {action!r} to ask for.")
        if self.folder is None:
            raise ControlError("Updates from the website aren't set up on this server.")
        if self._runner() is None:
            raise ControlError(
                "The server's runner isn't installed, so nothing would pick this up."
            )
        self._lapse_stale()
        if self._in_progress() is not None:
            raise ControlError("An update or restart is already under way.")
        outcome = await self.services.autonomy.stage(
            CATEGORY, member, SUMMARIES[action], {"action": action}, EXECUTOR, requested=True
        )
        return outcome.message

    async def _write_request(self, payload: dict[str, Any], context: ExecutionContext) -> str:
        assert self.folder is not None
        action = payload["action"]
        row = self.db.one(
            "SELECT id FROM server_requests WHERE action_id = ?", (context.action_id,)
        )
        if row is None:
            request_id = self.db.execute(
                "INSERT INTO server_requests (action, member_id, action_id, state, from_version,"
                " asked_at) VALUES (?, ?, ?, 'waiting', ?, ?)",
                (
                    action,
                    context.member.id,
                    context.action_id,
                    __version__,
                    to_utc_iso(clock.now()),
                ),
            )
        else:
            request_id = row["id"]  # a retry: the same request again
        self._write_json(
            "request.json",
            {
                "id": request_id,
                "action": action,
                "version": "newest" if action == "update" else "current",
                "asked_by": context.member.name,
                "asked_at": to_utc_iso(clock.now()),
            },
        )
        if action == "update":
            return "Asked the server to update to the newest release. I'll say when it's done."
        return "Asked the server to restart. I'll say when it's back."

    def _write_json(self, name: str, value: dict[str, Any]) -> None:
        """Written whole or not at all: a temp file, then a rename."""
        assert self.folder is not None
        target = self.folder / name
        temp = self.folder / f".{name}.tmp"
        temp.write_text(json.dumps(value) + "\n")
        os.replace(temp, target)

    # ----- what the page shows ----------------------------------------------------

    def state(self) -> ServerState:
        runner = self._runner()
        self._lapse_stale()
        rows = self.db.query("SELECT * FROM server_requests ORDER BY id DESC LIMIT ?", (RECENT,))
        return ServerState(
            configured=self.folder is not None,
            running_version=__version__,
            runner_installed=runner is not None,
            newest=_version(runner.get("newest")) if runner else None,
            newest_checked_at=_moment(runner.get("checked_at")) if runner else None,
            in_progress=self._in_progress(),
            recent=[_request_from_row(r) for r in rows],
        )

    def _runner(self) -> dict[str, Any] | None:
        return self._read_json("runner.json")

    def _read_json(self, name: str) -> dict[str, Any] | None:
        if self.folder is None:
            return None
        try:
            value = json.loads((self.folder / name).read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            log.warning("%s in the control folder couldn't be read", name)
            return None
        return value if isinstance(value, dict) else None

    def _in_progress(self) -> ServerRequest | None:
        row = self.db.one(
            "SELECT * FROM server_requests WHERE state IN ('waiting', 'running') "
            "ORDER BY id DESC LIMIT 1"
        )
        return _request_from_row(row) if row else None

    def _lapse_stale(self) -> None:
        """A request nothing picked up, or a run that never finished, stops blocking."""
        now = clock.now()
        for row in self.db.query(
            "SELECT * FROM server_requests WHERE state IN ('waiting', 'running')"
        ):
            limit = PICK_UP_WITHIN if row["state"] == "waiting" else FINISH_WITHIN
            if now - datetime.fromisoformat(row["asked_at"]) >= limit:
                self.db.execute(
                    "UPDATE server_requests SET state = 'lapsed', finished_at = ? WHERE id = ?",
                    (to_utc_iso(now), row["id"]),
                )

    # ----- results ----------------------------------------------------------------

    async def check(self) -> str:
        """Periodic job: take in the runner's result, and tell whoever asked, once."""
        await self._report_lapsed()
        result = self._read_json("result.json")
        if result is None:
            return "no result"
        request_id = result.get("id")
        state = result.get("state")
        if not isinstance(request_id, int) or state not in ("running", *FINISHED_STATES):
            return "result not understood"
        row = self.db.one("SELECT * FROM server_requests WHERE id = ?", (request_id,))
        if row is None or row["reported_at"] is not None or row["state"] == "lapsed":
            return "nothing new"
        if state == "running":
            self.db.execute(
                "UPDATE server_requests SET state = 'running' WHERE id = ? AND state = 'waiting'",
                (request_id,),
            )
            return "running"
        detail = result.get("detail")
        self.db.execute(
            "UPDATE server_requests SET state = ?, from_version = COALESCE(?, from_version),"
            " to_version = ?, detail = ?, finished_at = ? WHERE id = ?",
            (
                state,
                _version(result.get("from")),
                _version(result.get("to")),
                detail[-DETAIL_CHARS:] if isinstance(detail, str) else None,
                to_utc_iso(_moment(result.get("finished_at")) or clock.now()),
                request_id,
            ),
        )
        await self._report(request_id)
        return state

    async def _report_lapsed(self) -> None:
        self._lapse_stale()
        for row in self.db.query(
            "SELECT id FROM server_requests WHERE state = 'lapsed' AND reported_at IS NULL"
        ):
            await self._report(row["id"])

    async def _report(self, request_id: int) -> None:
        row = self.db.one("SELECT * FROM server_requests WHERE id = ?", (request_id,))
        assert row is not None
        self.db.execute(
            "UPDATE server_requests SET reported_at = ? WHERE id = ?",
            (to_utc_iso(clock.now()), request_id),
        )
        if row["member_id"] is None:
            return
        try:
            member = self.services.store.get_member(row["member_id"])
        except NotFound:
            return
        await self.services.outbox.send(
            member,
            self.words(_request_from_row(row)),
            priority=Priority.NORMAL,
            kind="system",
            dedupe_key=f"server-request:{request_id}",
        )

    @staticmethod
    def words(request: ServerRequest) -> str:
        """What a finished request comes to, in Themi's own words."""
        frm, to, action = request.from_version, request.to_version, request.action
        if request.state == "done" and to:
            if action == "restart":
                return TEXT["restarted"].format(to=to)
            if frm == to:
                return TEXT["newest"].format(to=to)
            return (
                TEXT["updated"].format(to=to, frm=frm) if frm else TEXT["updated_to"].format(to=to)
            )
        if request.state == "failed" and frm and to and frm != to:
            return TEXT["still_on"].format(to=to, frm=frm)
        key = request.state if request.state in ("refused", "lapsed") else "failed"
        return TEXT[key].format(action=action)
