"""What the trust tiers run for email actions (staged by triage, prompt 23).

Payloads name the email by its row in `emails` ({"email_id": ...}), so an
action can only touch mail Themi has seen in one of the member's accounts.

- `gmail.mark_read`: remove UNREAD.
- `gmail.archive`: remove INBOX (the mail stays in All Mail; nothing is deleted).
- `gmail.label`: add a label by name, creating it if needed.
- `gmail.send_reply`: reply in the thread to the sender. A retry never sends
  twice: each action's idempotency key is recorded with the sent message.

Label changes are idempotent by nature, so a retry is harmless.
"""

from __future__ import annotations

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
