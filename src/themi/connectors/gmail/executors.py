"""What the trust tiers run for email actions (staged by triage, prompt 23).

Payloads name the email by its row in `emails` ({"email_id": ...}), so an
action can only touch mail Themi has seen in one of the member's accounts.

- `gmail.mark_read`: remove UNREAD.
- `gmail.archive`: remove INBOX (the mail stays in All Mail; nothing is deleted).
- `gmail.unarchive`: add INBOX back (bug #53: an email that shouldn't have gone).
- `gmail.label`: add a label by name, creating it if needed.
- `gmail.send_reply`: reply in the thread to the sender. A retry never sends
  twice: each action's idempotency key is recorded with the sent message.
- `gmail.forward` (F31d, idea #168): the email, forwarded from the account it came to, as
  Gmail forwards (their note, the "Forwarded message" block, the original's text and
  attachments). The same idempotency as replies.

Label changes are idempotent by nature, so a retry is harmless.
"""

from __future__ import annotations

import html
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any

from themi import clock
from themi.autonomy import ExecutionContext, ExecutorRegistry
from themi.connectors.gmail.sync import GmailSync
from themi.localtime import to_utc_iso


class EmailNotFound(Exception):
    pass


def install_executors(executors: ExecutorRegistry, sync: GmailSync) -> None:
    def email_for(payload: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
        row = sync.email(int(payload["email_id"]))
        if row is None:
            raise EmailNotFound(f"email {payload['email_id']} is gone (account unlinked?)")
        account = sync.store.get_linked_account(row["account_id"])
        if account.member_id != ctx.member.id:
            raise PermissionError("that email belongs to someone else's account")
        return row

    @executors.register("gmail.mark_read")
    async def mark_read(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        row = email_for(payload, ctx)
        await sync.client(row["account_id"]).modify(row["gmail_id"], remove=["UNREAD"])
        return f"Marked read: {row['subject'] or 'an email'}"

    @executors.register("gmail.archive")
    async def archive(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        row = email_for(payload, ctx)
        await sync.client(row["account_id"]).modify(row["gmail_id"], remove=["INBOX"])
        return f"Archived: {row['subject'] or 'an email'}"

    @executors.register("gmail.unarchive")
    async def unarchive(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        row = email_for(payload, ctx)
        await sync.client(row["account_id"]).modify(row["gmail_id"], add=["INBOX"])
        return f"Back in the inbox: {row['subject'] or 'an email'}"

    @executors.register("gmail.label")
    async def label(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        row = email_for(payload, ctx)
        name = str(payload["label"]).strip()
        client = sync.client(row["account_id"])
        existing = {item["name"].lower(): item["id"] for item in await client.labels()}
        label_id = existing.get(name.lower()) or (await client.create_label(name))["id"]
        await client.modify(row["gmail_id"], add=[label_id])
        return f"Labelled {name}: {row['subject'] or 'an email'}"

    @executors.register("gmail.send_reply")
    async def send_reply(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        row = email_for(payload, ctx)
        already = sync.db.one(
            "SELECT gmail_id FROM email_sends WHERE idempotency_key = ?", (ctx.idempotency_key,)
        )
        if already:
            return f"Reply already sent to {row['from_address']}"
        account = sync.store.get_linked_account(row["account_id"])
        message = reply_message(row, account.address, str(payload["body"]))
        sent = await sync.client(row["account_id"]).send(bytes(message), row["thread_id"])
        sync.db.execute(
            "INSERT INTO email_sends (idempotency_key, account_id, gmail_id, sent_at) "
            "VALUES (?, ?, ?, ?)",
            (ctx.idempotency_key, account.id, sent.get("id", ""), to_utc_iso(clock.now())),
        )
        return f"Reply sent to {row['from_address']}"

    @executors.register("gmail.forward")
    async def forward(payload: dict[str, Any], ctx: ExecutionContext) -> str:
        row = email_for(payload, ctx)
        subject = row["subject"] or "an email"
        who = str(payload.get("to_name") or payload["to"])
        already = sync.db.one(
            "SELECT gmail_id FROM email_sends WHERE idempotency_key = ?", (ctx.idempotency_key,)
        )
        if already:
            return f"Forwarded to {who}: {subject}."
        client = sync.client(row["account_id"])
        raw = await client.get_raw(row["gmail_id"])
        if raw is None:
            raise EmailNotFound("that email isn't in Gmail any more")
        account = sync.store.get_linked_account(row["account_id"])
        message, left_out = forward_message(
            raw, account.address, str(payload["to"]), str(payload.get("note") or "")
        )
        sent = await client.send(bytes(message))
        sync.db.execute(
            "INSERT INTO email_sends (idempotency_key, account_id, gmail_id, sent_at) "
            "VALUES (?, ?, ?, ?)",
            (ctx.idempotency_key, account.id, sent.get("id", ""), to_utc_iso(clock.now())),
        )
        dropped = f" Left out, too big to send: {', '.join(left_out)}." if left_out else ""
        return f"Forwarded to {who}: {subject}.{dropped}"


MAX_ATTACHMENTS = 24 * 1024 * 1024  # under Gmail's 25 MB for the whole message
FORWARDED = "---------- Forwarded message ---------"


def forward_message(
    raw: bytes, from_address: str, to: str, note: str
) -> tuple[EmailMessage, list[str]]:
    """The forward of an original (as Gmail's `format=raw` gives it), and the names of any
    attachments left out for size."""
    original = message_from_bytes(raw, policy=policy.default)
    assert isinstance(original, EmailMessage)
    subject = str(original.get("Subject") or "")
    header = [FORWARDED]
    for name in ("From", "Date", "Subject", "To", "Cc"):
        if original.get(name):
            header.append(f"{name}: {original[name]}")
    plain = original.get_body(preferencelist=("plain",))
    rich = original.get_body(preferencelist=("html",))
    text = plain.get_content() if plain is not None else ""
    lead = f"{note.strip()}\n\n" if note.strip() else ""
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = to
    message["Subject"] = subject if subject.lower().startswith("fwd:") else f"Fwd: {subject}"
    message["Message-ID"] = make_msgid(domain=from_address.split("@")[-1])
    message.set_content(lead + "\n".join(header) + "\n\n" + text)
    if rich is not None:
        top = (html.escape(note.strip()) + "<br><br>") if note.strip() else ""
        block = "<br>".join(html.escape(line) for line in header)
        message.add_alternative(
            f"<div>{top}{block}<br><br></div>{rich.get_content()}", subtype="html"
        )
    left_out: list[str] = []
    total = 0
    for part in original.iter_attachments():
        data = part.get_payload(decode=True)
        name = part.get_filename() or "attachment"
        if not isinstance(data, bytes):
            continue
        if total + len(data) > MAX_ATTACHMENTS:
            left_out.append(name)
            continue
        total += len(data)
        main, sub = part.get_content_type().split("/", 1)
        message.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return message, left_out


def reply_message(row: dict[str, Any], from_address: str, body: str) -> EmailMessage:
    subject = row["subject"] or ""
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = formataddr((row["from_name"], row["from_address"]))
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    message["Message-ID"] = make_msgid(domain=from_address.split("@")[-1])
    if row["message_id_header"]:
        message["In-Reply-To"] = row["message_id_header"]
        message["References"] = row["message_id_header"]
    message.set_content(body)
    return message
