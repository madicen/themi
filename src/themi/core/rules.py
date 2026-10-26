"""Rules: brainstorm as drafts, lock in with an explicit yes.

- The model captures ideas with the `propose_rule` tool. That creates (or
  updates) a draft and sends: "Proposed Rule: … A YES locks this in, or we
  keep brainstorming." with a [Lock it in] button.
- Only the person the rule affects can lock it: their YES (when it's the only
  thing waiting on them) or their tap. The model has no way to lock a rule,
  so a partner's "yes" or a misread conversation can't make one stick.
- Locking an `autonomy_grant` rule makes its category automatic, which
  needs an admin and never works for capped categories. Both are checked
  when the idea is proposed, so nobody is asked to lock something that
  can't happen.
- Drafts lapse quietly after 14 days without changes.
- A rule is for the household (the default) or personal. Locked household
  rules go into the system prompt of every AI request; a personal rule only
  into its owner's (the person it affects). Autonomy grants change what
  Themi does for everyone, so they're always household rules.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from themi import clock
from themi.accounts import Member, NotFound, PermissionDenied
from themi.accounts.store import Actor, SystemActor
from themi.autonomy import Autonomy, CappedCategory
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Outbox, Priority
from themi.core.services import AwaitingItem, Decision, Services
from themi.core.tools import Tool, ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso

log = logging.getLogger(__name__)

DRAFT_TTL = timedelta(days=14)
RuleKind = Literal["policy", "autonomy_grant", "standing_reminder"]
RuleStatus = Literal["draft", "locked", "expired", "discarded", "unlocked"]
RuleScope = Literal["household", "personal"]

PROPOSAL_TEXT = "Proposed Rule: {summary}. A YES locks this in, or we keep brainstorming."
PERSONAL_PROPOSAL_TEXT = (
    "Proposed Rule (just for you): {summary}. A YES locks this in, or we keep brainstorming."
)
LOCKED_TEXT = "Locked in: {summary}."
LOCKED_REPLY = "Locked in. I'll follow that from now on."
SUPERSEDED_TEXT = "Earlier version: {summary}. (Updated below.)"
DISCARDED_TEXT = "Set aside: {summary}."
LAPSED_TEXT = "This idea lapsed: {summary}. Happy to pick it up again any time."
STILL_DRAFT_REPLY = "It's still a draft. We can come back to it whenever."
NOT_YOURS_REPLY = "That one is for the person it affects to lock in."
GRANTS_ARE_HOUSEHOLD = (
    "A rule that makes something automatic changes what Themi does for everyone, so it has "
    "to be a household rule."
)
NEEDS_ADMIN = (
    "Making that automatic changes what Themi does for the household, so it takes an admin "
    "to lock in."
)


class RuleError(Exception):
    """Raised for proposals that can't become rules; the message is safe to show."""


@dataclass(frozen=True)
class Rule:
    id: int
    summary: str
    text: str
    kind: RuleKind
    category: str | None
    status: RuleStatus
    proposed_by: int | None
    affects: int | None
    updated_at: datetime
    scope: RuleScope = "household"


def _rule_from_row(row: dict[str, Any]) -> Rule:
    return Rule(
        id=row["id"],
        summary=row["summary"],
        text=row["text"],
        kind=row["kind"],
        category=row["category"],
        status=row["status"],
        proposed_by=row["proposed_by"],
        affects=row["affects"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
        scope=row["scope"],
    )


def _actor_label(actor: Actor) -> str:
    return "system" if isinstance(actor, SystemActor) else f"member:{actor.id}"


class Rulebook:
    def __init__(self, autonomy: Autonomy, outbox: Outbox) -> None:
        self.autonomy = autonomy
        self.outbox = outbox
        self.store = autonomy.store
        self.db = autonomy.db

    def install(self, services: Services) -> None:
        services.rulebook = self
        services.button_handlers["rule"] = self.on_button
        services.awaiting_sources.append(self.awaiting_items)
        services.add_command("/rules", self.on_rules_command, "See the rules and your drafts")
        services.tools.register(propose_rule_tool)
        services.tools.register(set_aside_draft_rule)

    # ----- reading ------------------------------------------------------------

    def get(self, rule_id: int) -> Rule:
        row = self.db.one("SELECT * FROM rules WHERE id = ?", (rule_id,))
        if row is None:
            raise NotFound(f"no rule with id {rule_id}")
        return _rule_from_row(row)

    def locked(self) -> list[Rule]:
        rows = self.db.query("SELECT * FROM rules WHERE status = 'locked' ORDER BY id")
        return [_rule_from_row(r) for r in rows]

    def household(self) -> list[Rule]:
        return [r for r in self.locked() if r.scope == "household"]

    def personal(self, member: Member) -> list[Rule]:
        """The member's own locked personal rules. Nobody else's are ever shown."""
        return [r for r in self.locked() if r.scope == "personal" and r.affects == member.id]

    def prompt_rules(self, member: Member) -> tuple[list[str], list[str]]:
        """(household rule texts, this member's personal rule texts) for their AI requests."""
        return [r.text for r in self.household()], [r.text for r in self.personal(member)]

    def drafts(self, member: Member) -> list[Rule]:
        rows = self.db.query(
            "SELECT * FROM rules WHERE status = 'draft' AND affects = ? ORDER BY id", (member.id,)
        )
        return [_rule_from_row(r) for r in rows]

    # ----- proposing ----------------------------------------------------------

    async def propose(
        self,
        member: Member,
        summary: str,
        text: str,
        kind: RuleKind = "policy",
        category: str | None = None,
        *,
        rule_id: int | None = None,
        priority: Priority = Priority.REPLY,
        scope: RuleScope = "household",
    ) -> Rule:
        summary, text = summary.strip().rstrip("."), text.strip()
        if not summary or not text:
            raise RuleError("A rule needs a short summary and the rule itself.")
        if kind == "standing_reminder":
            raise RuleError("Standing reminders come from context repair, not proposals.")
        if kind == "autonomy_grant":
            if scope == "personal":
                raise RuleError(GRANTS_ARE_HOUSEHOLD)
            self._check_grant_possible(member, category)
        else:
            category = None
        now = to_utc_iso(clock.now())
        if rule_id:
            existing = self.get(rule_id)
            if existing.status != "draft" or existing.affects != member.id:
                raise RuleError("That draft isn't open for changes any more.")
            self.db.execute(
                "UPDATE rules SET summary = ?, text = ?, kind = ?, category = ?, scope = ?, "
                "updated_at = ? WHERE id = ?",
                (summary, text, kind, category, scope, now, rule_id),
            )
            await self._retire_messages(rule_id, SUPERSEDED_TEXT.format(summary=existing.summary))
        else:
            rule_id = self.db.execute(
                "INSERT INTO rules (summary, text, kind, category, scope, proposed_by, affects, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (summary, text, kind, category, scope, member.id, member.id, now, now),
            )
        rule = self.get(rule_id)
        result = await self.outbox.send(
            member,
            (PERSONAL_PROPOSAL_TEXT if rule.scope == "personal" else PROPOSAL_TEXT).format(
                summary=rule.summary
            ),
            priority=priority,
            buttons=[Button("Lock it in", "rule", {"rule": rule.id})],
            kind="rule",
        )
        if result.outbox_id is not None:
            self.db.execute(
                "INSERT INTO rule_messages (rule_id, member_id, outbox_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (rule.id, member.id, result.outbox_id, now),
            )
        return rule

    def _check_grant_possible(self, member: Member, category: str | None) -> None:
        if not category:
            raise RuleError("An automatic-action rule needs to name what becomes automatic.")
        try:
            cat = self.autonomy.category(category)
        except NotFound as exc:
            raise RuleError(f"There's no kind of action called {category}.") from exc
        if cat.capped:
            raise RuleError(
                f"{cat.label} always needs a yes from someone, so it can't become automatic. "
                "Happy to keep asking each time instead."
            )
        if not self.store.get_member(member.id).is_admin:
            raise RuleError(NEEDS_ADMIN)

    # ----- locking and setting aside ------------------------------------------

    async def lock(self, rule_id: int, by: Actor) -> str:
        rule = self.get(rule_id)
        if rule.status != "draft":
            return "That one's already settled."
        if not isinstance(by, SystemActor) and by.id != rule.affects:
            return NOT_YOURS_REPLY
        if rule.kind == "autonomy_grant":
            assert rule.category is not None
            try:
                self.autonomy.grant_tier2(rule.category, via_rule_id=rule.id, by=by)
            except CappedCategory:
                return "That kind of action always needs a yes, so it stays a draft."
            except PermissionDenied:
                return NEEDS_ADMIN
        now = to_utc_iso(clock.now())
        self.db.execute(
            "UPDATE rules SET status = 'locked', locked_at = ?, locked_by = ?, updated_at = ? "
            "WHERE id = ?",
            (now, _actor_label(by), now, rule_id),
        )
        log.info("Rule %s locked by %s", rule_id, _actor_label(by))
        await self._retire_messages(rule_id, LOCKED_TEXT.format(summary=rule.summary))
        return LOCKED_REPLY

    async def discard(self, rule_id: int, by: Actor) -> str:
        rule = self.get(rule_id)
        if rule.status != "draft":
            return "That one's already settled."
        if not isinstance(by, SystemActor) and by.id != rule.affects:
            return NOT_YOURS_REPLY
        self._set_status(rule_id, "discarded")
        await self._retire_messages(rule_id, DISCARDED_TEXT.format(summary=rule.summary))
        return "Okay, setting that idea aside."

    def unlock(self, rule_id: int, by: Actor) -> Rule:
        """Retire a locked rule (from the website). Undoes an autonomy grant."""
        rule = self.get(rule_id)
        if rule.status != "locked":
            raise RuleError("Only locked rules can be unlocked.")
        if rule.kind == "autonomy_grant" and rule.category:
            self.autonomy.revoke_tier2(rule.category, by=by)
        elif not isinstance(by, SystemActor) and by.id != rule.affects and not by.is_admin:
            raise PermissionDenied("only the person it affects, or an admin, can unlock this")
        self._set_status(rule_id, "unlocked")
        return self.get(rule_id)

    def grant_automatic(self, admin: Member, category: str) -> Rule:
        """An admin turning on "automatic" on the website: a rule locked by that action.

        Ticking the switch is the explicit confirmation, so the rule is locked at once
        (and shows in /rules like any other).
        """
        self._check_grant_possible(admin, category)
        cat = self.autonomy.category(category)
        now = to_utc_iso(clock.now())
        label = cat.label[:1].lower() + cat.label[1:]
        rule_id = self.db.execute(
            "INSERT INTO rules (summary, text, kind, category, status, proposed_by, affects, "
            "created_at, updated_at, locked_at, locked_by) "
            "VALUES (?, ?, 'autonomy_grant', ?, 'locked', ?, ?, ?, ?, ?, ?)",
            (
                f"Automatic: {cat.label}",
                f"Themi may {label} without asking first.",
                category,
                admin.id,
                admin.id,
                now,
                now,
                now,
                f"member:{admin.id}",
            ),
        )
        self.autonomy.grant_tier2(category, via_rule_id=rule_id, by=admin)
        return self.get(rule_id)

    def revoke_automatic(self, admin: Member, category: str) -> None:
        """Turn "automatic" off: retire the rule that granted it (or just the grant)."""
        row = self.db.one(
            "SELECT id FROM rules WHERE kind = 'autonomy_grant' AND category = ? "
            "AND status = 'locked' ORDER BY id DESC LIMIT 1",
            (category,),
        )
        if row is not None:
            self.unlock(row["id"], admin)
        else:
            self.autonomy.revoke_tier2(category, by=admin)

    def add_standing_reminder(self, member: Member, summary: str, text: str) -> Rule:
        """Lock a reminder straight away. Used by context repair, which the person asked for."""
        now = to_utc_iso(clock.now())
        rule_id = self.db.execute(
            "INSERT INTO rules (summary, text, kind, status, proposed_by, affects, created_at, "
            "updated_at, locked_at, locked_by) VALUES (?, ?, 'standing_reminder', 'locked', ?, ?, "
            "?, ?, ?, ?)",
            (summary, text, member.id, member.id, now, now, now, f"member:{member.id}"),
        )
        return self.get(rule_id)

    def _set_status(self, rule_id: int, status: RuleStatus) -> None:
        self.db.execute(
            "UPDATE rules SET status = ?, updated_at = ? WHERE id = ?",
            (status, to_utc_iso(clock.now()), rule_id),
        )

    async def _retire_messages(self, rule_id: int, text: str) -> None:
        for row in self.db.query("SELECT * FROM rule_messages WHERE rule_id = ?", (rule_id,)):
            message_id = self.outbox.message_id(row["outbox_id"])
            if message_id is None:
                self.outbox.cancel(row["outbox_id"])
            else:
                await self.outbox.edit(self.store.get_member(row["member_id"]), message_id, text)
            self.db.execute("DELETE FROM rule_messages WHERE id = ?", (row["id"],))

    # ----- chat wiring ----------------------------------------------------------

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        reply = await self.lock(int(event.button.payload["rule"]), event.member)
        if reply != LOCKED_REPLY:  # success shows as the edited proposal
            await self.outbox.send(event.member, reply, priority=Priority.REPLY)

    def awaiting_items(self, member: Member) -> list[AwaitingItem]:
        def resolver(rule_id: int) -> Callable[[Decision], Awaitable[str]]:
            async def resolve(decision: Decision) -> str:
                if decision == "yes":
                    return await self.lock(rule_id, member)
                if decision == "no":
                    return await self.discard(rule_id, member)
                return STILL_DRAFT_REPLY

            return resolve

        return [
            AwaitingItem(
                f"rule:{r.id}",
                f"Proposed rule {r.id}: {r.summary}",
                resolver(r.id),
                self._asked_in(r.id, member.id),
            )
            for r in self.drafts(member)
        ]

    def _asked_in(self, rule_id: int, member_id: int) -> tuple[int, ...]:
        rows = self.db.query(
            "SELECT o.telegram_message_id FROM rule_messages m JOIN outbox o "
            "ON o.id = m.outbox_id WHERE m.rule_id = ? AND m.member_id = ? "
            "AND o.telegram_message_id IS NOT NULL",
            (rule_id, member_id),
        )
        return tuple(r["telegram_message_id"] for r in rows)

    async def on_rules_command(self, member: Member, argument: str) -> None:
        household, personal = self.household(), self.personal(member)
        drafts = self.drafts(member)
        if not household and not personal and not drafts:
            text = "No rules yet. Ideas can start as drafts whenever you like."
        else:
            parts = []
            if household:
                parts.append("Household rules:\n" + "\n".join(f"• {r.summary}" for r in household))
            if personal:
                parts.append("Just for you:\n" + "\n".join(f"• {r.summary}" for r in personal))
            if drafts:
                parts.append(
                    "Your drafts:\n"
                    + "\n".join(
                        f"• {r.summary}{' (just for you)' if r.scope == 'personal' else ''}"
                        for r in drafts
                    )
                )
            text = "\n\n".join(parts)
        await self.outbox.send(member, text, priority=Priority.REPLY)

    # ----- housekeeping ---------------------------------------------------------

    async def expire_drafts(self, older_than: timedelta = DRAFT_TTL) -> int:
        cutoff = to_utc_iso(clock.now() - older_than)
        rows = self.db.query(
            "SELECT * FROM rules WHERE status = 'draft' AND updated_at <= ?", (cutoff,)
        )
        for row in rows:
            self._set_status(row["id"], "expired")
            await self._retire_messages(row["id"], LAPSED_TEXT.format(summary=row["summary"]))
        return len(rows)


@tool(
    "propose_rule",
    "Capture a rule about how Themi itself behaves, as a draft for this person to lock in "
    "('always archive store promos', 'list steps as bullet points'). Chores, schedules and "
    "the steps of a job are tasks (create_task), never rules. It sends them the proposal; "
    "nothing takes "
    "effect until they lock it in. applies_to: household rules apply to everyone in the "
    "family; personal ones only shape your conversations with this person. Ask if it isn't "
    "clear which they mean. Rules can't change when Themi's own messages go out: that's "
    "quiet hours and the daily limit in their website settings, or /pause. To refine an "
    "earlier draft, pass its rule_id (else 0).",
    {
        "summary": {
            "type": "string",
            "description": "One short line, e.g. 'Archive store promos'.",
        },
        "text": {
            "type": "string",
            "description": "The rule as you'll follow it, in one or two sentences.",
        },
        "kind": {
            "type": "string",
            "enum": ["policy", "autonomy_grant"],
            "description": "autonomy_grant if the rule lets Themi do a kind of action without "
            "asking each time; otherwise policy.",
        },
        "category": {
            "type": "string",
            "description": "For autonomy_grant: the action category, e.g. 'email_archive_noise'. "
            "Empty string otherwise.",
        },
        "rule_id": {"type": "integer", "description": "An existing draft to update, or 0."},
        "applies_to": {
            "type": "string",
            "enum": ["household", "personal"],
            "description": "household for everyone; personal for this person only. "
            "Automatic-action rules are always household.",
        },
    },
)
async def propose_rule(ctx: ToolContext, args: dict[str, Any]) -> str:
    rulebook = ctx.services.rulebook
    assert rulebook is not None
    try:
        rule = await rulebook.propose(
            ctx.member,
            args["summary"],
            args["text"],
            args["kind"],
            args["category"] or None,
            rule_id=args["rule_id"] or None,
            scope=args["applies_to"],
        )
    except RuleError as exc:
        return f"Not proposed: {exc}"
    return (
        f"Draft rule {rule.id} sent to them for locking: {rule.summary}. It isn't in effect "
        "until they lock it in, so don't describe it as settled."
    )


propose_rule_tool: Tool = propose_rule


@tool(
    "set_aside_draft_rule",
    "Set aside one of this person's draft rules when they say they don't want it (a draft "
    "was never in effect). Draft numbers are in their open items. Never for locked rules.",
    {"rule_id": {"type": "integer"}},
)
async def set_aside_draft_rule(ctx: ToolContext, args: dict[str, Any]) -> str:
    rulebook = ctx.services.rulebook
    assert rulebook is not None
    try:
        rule = rulebook.get(args["rule_id"])
    except NotFound as exc:
        raise ToolFailed("There's no rule with that number.") from exc
    if rule.status != "draft" or rule.affects != ctx.member.id:
        raise ToolFailed("That isn't one of their open draft rules.")
    return await rulebook.discard(rule.id, ctx.member)
