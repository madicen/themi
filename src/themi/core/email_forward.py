"""Forwarding an email (F31d, idea #168: "allow email forwarding").

Michael had heard about an urgent email (the Sugarmill's roofing inspection) and asked
"Can you forward that email to Erin?"; Themi could only say it couldn't. `forward_email`
stages a card in `email_forward`, which always asks (it sends as the person), and
`gmail.forward` (`connectors/gmail/executors.py`) sends it from the account the email came
to.

- Which email: words from its sender or subject, or "that email": the newest one Themi told
  them about or offered a card for in the last two days.
- To whom: someone in the family (their sign-in address, or their one linked Gmail account;
  with several, the tool asks which), or an address they wrote in this message. No
  addresses from memory.
- The email itself stays data: what it says is never read as instructions.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import Member
from themi.core.tools import Proposal, ToolContext, ToolFailed, staged_tool
from themi.core.triage import _sender, find_email
from themi.localtime import to_utc_iso

if TYPE_CHECKING:
    from themi.core.services import Services

CATEGORY = "email_forward"
EXECUTOR = "gmail.forward"
TOLD_WITHIN = timedelta(days=2)  # how far back "that email" looks
EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
THAT = re.compile(r"^(?:(?:that|this|it|the|that one|last|latest)\s*)*(?:e-?mail|one|message)?$")
WHICH_TEXT = (
    "Not staged: it isn't clear which email. Ask them (its sender or subject), then call "
    "again with those words."
)


def install(services: Services) -> None:
    services.tools.register(forward_email)


def told_about(ctx: ToolContext) -> dict[str, Any] | None:
    """The newest email Themi told this person about (an urgent notice) or put on a card,
    in the last two days: what "that email" means."""
    db = ctx.services.store.db
    since = to_utc_iso(clock.now() - TOLD_WITHIN)
    found: list[tuple[str, int]] = []
    for row in db.query(
        "SELECT dedupe_key, COALESCE(sent_at, send_after) AS at FROM outbox WHERE member_id = ? "
        "AND kind = 'email' AND dedupe_key LIKE 'email-urgent:%' AND send_after >= ?",
        (ctx.member.id, since),
    ):
        found.append((str(row["at"]), int(str(row["dedupe_key"]).split(":", 1)[1])))
    for row in db.query(
        "SELECT payload, created_at FROM pending_actions WHERE member_id = ? "
        "AND payload LIKE '%\"email_id\"%' AND created_at >= ?",
        (ctx.member.id, since),
    ):
        email_id = json.loads(row["payload"]).get("email_id")
        if email_id:
            found.append((str(row["created_at"]), int(email_id)))
    accounts = {a.id for a in ctx.services.store.linked_accounts(ctx.member.id)}
    for _, email_id in sorted(found, reverse=True):
        row = db.one("SELECT * FROM emails WHERE id = ?", (email_id,))
        if row is not None and row["account_id"] in accounts:
            return row
    return None


def _address_of(ctx: ToolContext, member: Member) -> str:
    if member.email:
        return member.email
    gmail = [a.address for a in ctx.services.store.linked_accounts(member.id)]
    if len(gmail) == 1:
        return gmail[0]
    if not gmail:
        raise ToolFailed(
            f"Not staged: there's no email address for {member.name}. Ask them for one."
        )
    raise ToolFailed(
        f"Not staged: {member.name} has more than one address ({', '.join(gmail)}). Ask which, "
        "then call again with it as to."
    )


def recipient(ctx: ToolContext, said_to: str) -> tuple[str, str]:
    """(address, name to say) for `to`: a family member, or an address they wrote."""
    target = said_to.strip()
    members = ctx.services.store.list_members()
    others = [m for m in members if m.id != ctx.member.id]
    if EMAIL.fullmatch(target):
        family = {
            a.address.lower(): m.name
            for m in members
            for a in ctx.services.store.linked_accounts(m.id)
        } | {m.email.lower(): m.name for m in members if m.email}
        if target.lower() in family:
            return target, family[target.lower()]
        said = f"{ctx.request_text} {ctx.previous_text}".lower()
        if target.lower() not in said:
            raise ToolFailed(
                "Not staged: that address isn't in their message. Ask them for it, or use a "
                "name from the family."
            )
        return target, target
    lowered = target.lower()
    partner = ("partner", "her", "him", "them", "my partner", "my wife", "my husband")
    if lowered in partner and len(others) == 1:
        return _address_of(ctx, others[0]), others[0].name
    chosen = next((m for m in members if m.name.lower() == lowered), None)
    if chosen is None:
        names = ", ".join(m.name for m in members)
        raise ToolFailed(
            f"Not staged: there's nobody called {target} in the family ({names}). Ask them "
            "who it's for, or for an address."
        )
    return _address_of(ctx, chosen), chosen.name


@staged_tool(
    "forward_email",
    "Forward an email from their inbox ('forward that email to Erin', 'send this email to "
    "jenn@example.com'). email: words from its sender or subject, or '' for the one Themi "
    "just told them about. to: a family member's name, or an email address they wrote. "
    "note: their own words to put above it, or ''. It shows a card first; the card is the "
    "answer.",
    {
        "email": {"type": "string"},
        "to": {"type": "string"},
        "note": {"type": "string", "default": ""},
    },
)
async def forward_email(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    words = " ".join(str(args["email"]).split()).lower()
    row = told_about(ctx) if THAT.fullmatch(words) else find_email(ctx, words)
    if row is None:
        raise ToolFailed(WHICH_TEXT)
    address, name = recipient(ctx, str(args["to"]))
    subject = row["subject"] or "an email"
    note = " ".join(str(args.get("note") or "").split())[:1000]
    shown = name if name == address else f"{name} ({address})"
    return Proposal(
        CATEGORY,
        f'Forwarding to {shown}: "{subject}" from {_sender(row)}'
        + (f', with "{note}"' if note else ""),
        EXECUTOR,
        {"email_id": row["id"], "to": address, "to_name": name, "note": note},
        requested=True,
    )
