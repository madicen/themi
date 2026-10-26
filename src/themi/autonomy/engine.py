"""Trust tiers: every action that touches the outside world goes through here.

- `stage()` runs an action at once if its category is Tier 2 (automatic) and
  not escalated; otherwise it becomes a pending action awaiting approval.
- `resolve()` approves, declines or snoozes a pending action. Approving runs
  its executor; a failed execution stays retryable (approve it again).
- `grant_tier2()` makes a category automatic, but only through a locked
  rule, and never for a capped category (sending as you, spending money,
  calling someone).
- `escalate()` is the Tier 3 anomaly override: the category behaves as
  Tier 1 until `resume()`.

Every step is written to the append-only `action_audit` table.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Literal

from themi import clock
from themi.accounts import AccountStore, Member, NotFound, PermissionDenied
from themi.accounts.store import Actor, SystemActor
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

DEFAULT_SNOOZE = timedelta(hours=3)


class Tier(IntEnum):
    SUPERVISED = 1
    AUTOMATIC = 2


class Decision(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"
    SNOOZE = "snooze"


ActionStatus = Literal["pending", "snoozed", "executing", "done", "declined", "failed", "expired"]
OPEN_STATUSES = ("pending", "snoozed", "failed")


class AutonomyError(Exception):
    pass


class CappedCategory(AutonomyError):
    """This category can never be automatic."""


class InvalidTransition(AutonomyError):
    """The action isn't in a state that allows this (already handled, already running...)."""


@dataclass(frozen=True)
class Category:
    name: str
    label: str
    scope: Literal["member", "family"]
    tier: Tier
    max_tier: Tier
    escalated: bool
    escalation_reason: str | None
    granted_by_rule: int | None

    @property
    def effective_tier(self) -> Tier:
        return Tier.SUPERVISED if self.escalated else self.tier

    @property
    def capped(self) -> bool:
        return self.max_tier is Tier.SUPERVISED


@dataclass(frozen=True)
class Action:
    id: int
    category: str
    member_id: int
    summary: str
    executor: str
    payload: dict[str, Any]
    status: ActionStatus
    automatic: bool
    snoozed_until: datetime | None
    attempts: int
    last_error: str | None
    result: str | None
    created_at: datetime


@dataclass(frozen=True)
class Outcome:
    """What happened: the action now, and a short line to tell the person."""

    action: Action
    message: str


@dataclass(frozen=True)
class ExecutionContext:
    action_id: int
    member: Member
    # Executors must be idempotent: running the same action twice (a retry after a
    # crash) must not do the thing twice. This key is stable per action.
    idempotency_key: str


Executor = Callable[[dict[str, Any], ExecutionContext], Awaitable[str]]
# Called when an action starts waiting on someone: (action, someone is in the chat now).
PendingListener = Callable[["Action", bool], Awaitable[None]]


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, Executor] = {}

    def register(self, name: str) -> Callable[[Executor], Executor]:
        def add(fn: Executor) -> Executor:
            if name in self._executors:
                raise ValueError(f"executor {name} is already registered")
            self._executors[name] = fn
            return fn

        return add

    def get(self, name: str) -> Executor | None:
        return self._executors.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._executors


def _actor_label(actor: Actor | str) -> str:
    if isinstance(actor, str):
        return actor
    if isinstance(actor, SystemActor):
        return "system"
    return f"member:{actor.id}"


def _category_from_row(row: dict[str, Any]) -> Category:
    return Category(
        name=row["name"],
        label=row["label"],
        scope=row["scope"],
        tier=Tier(row["tier"]),
        max_tier=Tier(row["max_tier"]),
        escalated=bool(row["escalated"]),
        escalation_reason=row["escalation_reason"],
        granted_by_rule=row["granted_by_rule"],
    )


def _action_from_row(row: dict[str, Any]) -> Action:
    return Action(
        id=row["id"],
        category=row["category"],
        member_id=row["member_id"],
        summary=row["summary"],
        executor=row["executor"],
        payload=json.loads(row["payload"]),
        status=row["status"],
        automatic=bool(row["automatic"]),
        snoozed_until=datetime.fromisoformat(row["snoozed_until"])
        if row["snoozed_until"]
        else None,
        attempts=row["attempts"],
        last_error=row["last_error"],
        result=row["result"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class Autonomy:
    def __init__(self, store: AccountStore, executors: ExecutorRegistry) -> None:
        self.store = store
        self.db = store.db
        self.executors = executors
        self.pending_listeners: list[PendingListener] = []

    # ----- categories ---------------------------------------------------------

    def categories(self) -> list[Category]:
        return [
            _category_from_row(r)
            for r in self.db.query("SELECT * FROM action_categories ORDER BY rowid")
        ]

    def category(self, name: str) -> Category:
        row = self.db.one("SELECT * FROM action_categories WHERE name = ?", (name,))
        if row is None:
            raise NotFound(f"no action category {name!r}")
        return _category_from_row(row)

    def grant_tier2(self, name: str, *, via_rule_id: int, by: Actor) -> Category:
        """Make a category automatic. Only a locked rule does this."""
        category = self.category(name)
        if category.capped:
            raise CappedCategory(f"{category.label} always needs a yes, and can't become automatic")
        self._require_admin(by)
        self._set_category(name, tier=2, granted_by_rule=via_rule_id)
        self._audit(None, name, None, "granted_tier2", by, f"rule {via_rule_id}")
        return self.category(name)

    def revoke_tier2(self, name: str, *, by: Actor) -> Category:
        self._require_admin(by)
        self._set_category(name, tier=1, granted_by_rule=None)
        self._audit(None, name, None, "revoked_tier2", by, None)
        return self.category(name)

    def escalate(self, name: str, reason: str) -> Category:
        """Tier 3: something unexpected happened; ask again until someone resumes."""
        self.category(name)
        self._set_category(name, escalated=1, escalation_reason=reason)
        self._audit(None, name, None, "escalated", "system", reason)
        log.warning("Escalated %s to supervised: %s", name, reason)
        return self.category(name)

    def resume(self, name: str, *, by: Actor) -> Category:
        self._require_admin(by)
        self._set_category(name, escalated=0, escalation_reason=None)
        self._audit(None, name, None, "resumed", by, None)
        return self.category(name)

    def _set_category(self, name: str, **columns: Any) -> None:
        columns["updated_at"] = to_utc_iso(clock.now())
        assignments = ", ".join(f"{c} = :{c}" for c in columns)
        self.db.execute(
            f"UPDATE action_categories SET {assignments} WHERE name = :name",
            {**columns, "name": name},
        )

    # ----- staging and resolving ----------------------------------------------

    async def stage(
        self,
        category: str,
        member: Member,
        summary: str,
        payload: dict[str, Any],
        executor: str,
        *,
        interactive: bool = False,
        requested: bool = False,
    ) -> Outcome:
        """Run now (Tier 2) or wait for approval (Tier 1).

        `interactive` says the person is in the conversation right now (so an
        approval request can go out as a reply rather than wait for a good moment).
        `requested` says they asked for exactly this in their own words: that counts as
        their yes, but only for categories that may become automatic and aren't
        escalated. Capped categories always ask.
        """
        cat = self.category(category)
        if executor not in self.executors:
            raise AutonomyError(f"no executor called {executor!r}")
        automatic = cat.effective_tier is Tier.AUTOMATIC
        asked = requested and not automatic and not cat.capped and not cat.escalated
        now = to_utc_iso(clock.now())
        action_id = self.db.execute(
            "INSERT INTO pending_actions (category, member_id, summary, executor, payload, status,"
            " automatic, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                category,
                member.id,
                summary,
                executor,
                json.dumps(payload),
                "executing" if automatic or asked else "pending",
                int(automatic),
                now,
                now,
            ),
        )
        self._audit(action_id, category, member.id, "staged", member, summary)
        if asked:
            self._audit(action_id, category, member.id, "requested", member, "asked in chat")
            return await self._execute(action_id, member)
        if not automatic:
            pending = self.action(action_id)
            for listener in self.pending_listeners:
                try:
                    await listener(pending, interactive)
                except Exception:
                    log.exception("A pending-action listener failed for action %s", action_id)
            return Outcome(pending, f"Waiting on your yes: {summary}")
        self._audit(action_id, category, member.id, "auto_approved", "system", "Tier 2")
        return await self._execute(action_id, member)

    async def resolve(
        self,
        action_id: int,
        decision: Decision,
        *,
        by: Actor,
        snooze_for: timedelta = DEFAULT_SNOOZE,
    ) -> Outcome:
        action = self.action(action_id)
        self._require_can_resolve(action, by)
        decision = Decision(decision)
        now = clock.now()
        if decision is Decision.APPROVE:
            claimed = self.db.update(
                "UPDATE pending_actions SET status = 'executing', resolved_by = ?, resolved_at = ?,"
                " updated_at = ? WHERE id = ? AND status IN ('pending', 'snoozed', 'failed')",
                (_actor_label(by), to_utc_iso(now), to_utc_iso(now), action_id),
            )
            if not claimed:
                raise InvalidTransition(f"action {action_id} is already {action.status}")
            self._audit(action_id, action.category, action.member_id, "approved", by, None)
            return await self._execute(action_id, self.store.get_member(action.member_id))

        allowed = (
            ("pending", "snoozed", "failed")
            if decision is Decision.DECLINE
            else ("pending", "snoozed")
        )
        if action.status not in allowed:
            raise InvalidTransition(f"action {action_id} is already {action.status}")
        if decision is Decision.DECLINE:
            self.db.execute(
                "UPDATE pending_actions SET status = 'declined', resolved_by = ?, resolved_at = ?,"
                " updated_at = ? WHERE id = ?",
                (_actor_label(by), to_utc_iso(now), to_utc_iso(now), action_id),
            )
            self._audit(action_id, action.category, action.member_id, "declined", by, None)
            return Outcome(self.action(action_id), f"Okay, leaving it: {action.summary}")

        until = now + snooze_for
        self.db.execute(
            "UPDATE pending_actions SET status = 'snoozed', snoozed_until = ?, updated_at = ? "
            "WHERE id = ?",
            (to_utc_iso(until), to_utc_iso(now), action_id),
        )
        self._audit(action_id, action.category, action.member_id, "snoozed", by, to_utc_iso(until))
        return Outcome(
            self.action(action_id), f"No rush. I'll bring it back later: {action.summary}"
        )

    async def _execute(self, action_id: int, member: Member) -> Outcome:
        action = self.action(action_id)
        executor = self.executors.get(action.executor)
        assert executor is not None
        context = ExecutionContext(action_id, member, f"themi-action-{action_id}")
        try:
            result = await executor(action.payload, context)
        except Exception as exc:
            log.warning("Action %s (%s) failed: %s", action_id, action.executor, type(exc).__name__)
            self.db.execute(
                "UPDATE pending_actions SET status = 'failed', attempts = attempts + 1, "
                "last_error = ?, updated_at = ? WHERE id = ?",
                (type(exc).__name__, to_utc_iso(clock.now()), action_id),
            )
            self._audit(
                action_id,
                action.category,
                action.member_id,
                "execution_failed",
                "system",
                type(exc).__name__,
            )
            return Outcome(
                self.action(action_id),
                f"That didn't go through ({action.summary}). It's still here to try again.",
            )
        self.db.execute(
            "UPDATE pending_actions SET status = 'done', attempts = attempts + 1, result = ?, "
            "last_error = NULL, updated_at = ? WHERE id = ?",
            (result, to_utc_iso(clock.now()), action_id),
        )
        self._audit(action_id, action.category, action.member_id, "executed", "system", result)
        return Outcome(self.action(action_id), result or f"Done: {action.summary}")

    # ----- lookups ------------------------------------------------------------

    def action(self, action_id: int) -> Action:
        row = self.db.one("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
        if row is None:
            raise NotFound(f"no action with id {action_id}")
        return _action_from_row(row)

    def open_for(self, member: Member) -> list[Action]:
        """Actions this member could act on: their own, plus household ones if they're an admin."""
        rows = self.db.query(
            "SELECT a.* FROM pending_actions a JOIN action_categories c ON c.name = a.category "
            "WHERE a.status IN ('pending', 'snoozed', 'failed') "
            "AND (a.member_id = ? OR (c.scope = 'family' AND ?)) ORDER BY a.id",
            (member.id, int(self._is_admin(member))),
        )
        return [_action_from_row(r) for r in rows]

    def awaiting(self, member: Member) -> list[Action]:
        """Pending (not snoozed, not failed) actions waiting on this member's yes."""
        return [a for a in self.open_for(member) if a.status == "pending"]

    def resurface_snoozed(self) -> list[Action]:
        """Snoozed actions whose time has come go back to pending. Returns them."""
        now = to_utc_iso(clock.now())
        rows = self.db.query(
            "SELECT * FROM pending_actions WHERE status = 'snoozed' AND snoozed_until <= ?", (now,)
        )
        for row in rows:
            self.db.execute(
                "UPDATE pending_actions SET status = 'pending', snoozed_until = NULL, "
                "updated_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            self._audit(row["id"], row["category"], row["member_id"], "resurfaced", "system", None)
        return [self.action(r["id"]) for r in rows]

    def expire_stale(self, older_than: timedelta) -> list[Action]:
        """Pending or snoozed actions nobody answered in time lapse quietly."""
        now = clock.now()
        rows = self.db.query(
            "SELECT * FROM pending_actions WHERE status IN ('pending', 'snoozed') "
            "AND created_at <= ?",
            (to_utc_iso(now - older_than),),
        )
        for row in rows:
            self.db.execute(
                "UPDATE pending_actions SET status = 'expired', updated_at = ? WHERE id = ?",
                (to_utc_iso(now), row["id"]),
            )
            self._audit(row["id"], row["category"], row["member_id"], "expired", "system", None)
        return [self.action(r["id"]) for r in rows]

    def audit_trail(self, action_id: int | None = None, category: str | None = None) -> list[dict]:
        if action_id is not None:
            return self.db.query(
                "SELECT * FROM action_audit WHERE action_id = ? ORDER BY id", (action_id,)
            )
        if category is not None:
            return self.db.query(
                "SELECT * FROM action_audit WHERE category = ? ORDER BY id", (category,)
            )
        return self.db.query("SELECT * FROM action_audit ORDER BY id")

    # ----- permissions and audit ----------------------------------------------

    def _is_admin(self, actor: Actor) -> bool:
        if isinstance(actor, SystemActor):
            return True
        row = self.db.one("SELECT role FROM members WHERE id = ?", (actor.id,))
        return row is not None and row["role"] == "admin"

    def _require_admin(self, actor: Actor) -> None:
        if not self._is_admin(actor):
            raise PermissionDenied("only an admin can change how much Themi does on its own")

    def _require_can_resolve(self, action: Action, actor: Actor) -> None:
        if isinstance(actor, SystemActor) or actor.id == action.member_id:
            return
        if self.category(action.category).scope == "family" and self._is_admin(actor):
            return
        raise PermissionDenied("that one is for someone else to answer")

    def _audit(
        self,
        action_id: int | None,
        category: str,
        member_id: int | None,
        event: str,
        actor: Actor | str,
        detail: str | None,
    ) -> None:
        self.db.execute(
            "INSERT INTO action_audit (action_id, category, member_id, event, actor, detail, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                action_id,
                category,
                member_id,
                event,
                _actor_label(actor),
                detail,
                to_utc_iso(clock.now()),
            ),
        )
