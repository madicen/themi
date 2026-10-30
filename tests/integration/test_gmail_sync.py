"""Gmail polling and executors, over real HTTP against the fake Google and fake Gmail."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import REDIRECT_URI, FakeGoogle
from tests.fixtures.family import SeededFamily
from tests.unit.test_outbox import FakeSender
from themi import clock
from themi.accounts import LinkedAccount, Member
from themi.autonomy import ExecutionContext, ExecutorRegistry
from themi.channels.outbox import Outbox
from themi.channels.pda import PdaShield
from themi.connectors.gmail import EmailReceived, GmailSync, install_executors
from themi.connectors.gmail.sync import POLL_EVERY, RELINK_ALERT
from themi.connectors.google import GoogleAccounts, GoogleOAuth

WEDNESDAY_10AM = datetime(2026, 10, 21, 17, 0, tzinfo=UTC)  # 10:00 Pacific
BANK = "Bank <alerts@bank.example>"


class Rig:
    def __init__(self, family: SeededFamily, google: FakeGoogle, gmail: FakeGmail) -> None:
        self.family = family
        self.fake_google = google
        self.fake_gmail = gmail
        self.oauth = GoogleOAuth(family.db, family.store.cipher, gmail.config())
        self.accounts = GoogleAccounts(family.store, self.oauth)
        self.sender = FakeSender()
        self.outbox = Outbox(family.store, self.sender, PdaShield(None))
        self.sync = GmailSync(family.store, self.accounts, self.outbox)
        self.events: list[EmailReceived] = []
        self.sync.listeners.append(self._record)

    async def _record(self, event: EmailReceived) -> None:
        self.events.append(event)

    async def link(self, member: Member, address: str) -> LinkedAccount:
        url = self.oauth.authorization_url("link", REDIRECT_URI, member)
        callback = {
            k: v[0]
            for k, v in parse_qs(urlparse(self.fake_google.consent(url, address)).query).items()
        }
        grant = await self.oauth.complete(callback["state"], callback["code"], REDIRECT_URI)
        return await self.accounts.link(grant)

    def subjects(self) -> list[str]:
        return [e.message.subject for e in self.events]

    async def later(self, by: timedelta = POLL_EVERY) -> int:
        clock.advance(by)
        return await self.sync.poll_all()


@pytest.fixture
def rig(family: SeededFamily, fake_google: FakeGoogle, fake_gmail: FakeGmail) -> Rig:
    clock.freeze(WEDNESDAY_10AM)
    return Rig(family, fake_google, fake_gmail)


# ----- syncing ---------------------------------------------------------------


async def test_first_sync_takes_the_last_week_of_inbox(rig: Rig, fake_gmail: FakeGmail) -> None:
    account = await rig.link(rig.family.erin, "erin@gmail.com")
    fake_gmail.deliver(
        "erin@gmail.com", sender=BANK, subject="old", text="x", age=timedelta(days=9)
    )
    fake_gmail.deliver(
        "erin@gmail.com", sender=BANK, subject="Tuesday", text="x", age=timedelta(days=1)
    )
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="today", text="Statement ready")
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="sent", text="x", labels=("SENT",))

    assert await rig.sync.poll_all() == 2
    assert rig.subjects() == ["Tuesday", "today"]  # oldest first
    assert all(e.initial and e.member_id == rig.family.erin.id for e in rig.events)
    row = rig.sync.email(rig.events[-1].email_id)
    assert row is not None and row["body_text"] == "Statement ready"
    assert row["from_address"] == "alerts@bank.example" and row["account_id"] == account.id
    assert rig.family.db.scalar("SELECT history_id FROM linked_accounts") is not None


async def test_then_history_brings_only_new_mail(rig: Rig, fake_gmail: FakeGmail) -> None:
    await rig.link(rig.family.erin, "erin@gmail.com")
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="first", text="x")
    await rig.sync.poll_all()
    assert await rig.later(timedelta(minutes=1)) == 0  # not due yet: no calls at all
    assert fake_gmail.calls_to("history") == 0

    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="second", text="x")
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="archived", text="x", labels=())
    assert await rig.later() == 1
    assert rig.subjects() == ["first", "second"]
    assert not rig.events[-1].initial
    syncing = [q for q in fake_gmail.list_queries if "newer_than" in q]  # not tab checks
    assert syncing == ["newer_than:7d"]  # the first sync only


async def test_history_pages_are_all_read(rig: Rig, fake_gmail: FakeGmail) -> None:
    await rig.link(rig.family.erin, "erin@gmail.com")
    await rig.sync.poll_all()
    for n in range(130):
        fake_gmail.deliver("erin@gmail.com", sender=BANK, subject=f"n{n}", text="x")
    assert await rig.later() == 130
    assert rig.subjects() == [f"n{n}" for n in range(130)]


async def test_an_interrupted_sync_resumes_without_repeats(rig: Rig, fake_gmail: FakeGmail) -> None:
    await rig.link(rig.family.erin, "erin@gmail.com")
    await rig.sync.poll_all()
    for n in range(4):
        fake_gmail.deliver("erin@gmail.com", sender=BANK, subject=f"n{n}", text="x")
    fake_gmail.fail("get", 500)  # breaks partway through
    await rig.later()
    assert await rig.later(timedelta(minutes=10)) > 0
    assert sorted(rig.subjects()) == ["n0", "n1", "n2", "n3"]


async def test_expired_history_resyncs(rig: Rig, fake_gmail: FakeGmail) -> None:
    await rig.link(rig.family.erin, "erin@gmail.com")
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="before", text="x")
    await rig.sync.poll_all()
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="during the gap", text="x")
    fake_gmail.expire_history("erin@gmail.com")

    assert await rig.later() == 1
    assert rig.subjects() == ["before", "during the gap"]  # nothing announced twice
    assert rig.events[-1].initial
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="after", text="x")
    assert await rig.later() == 1  # back on history


async def test_several_accounts_per_member_are_polled_independently(
    rig: Rig, fake_gmail: FakeGmail
) -> None:
    first = await rig.link(rig.family.erin, "erin@gmail.com")
    second = await rig.link(rig.family.erin, "erin.rentals@gmail.com")
    his = await rig.link(rig.family.husband, "him@gmail.com")
    await rig.sync.poll_all()
    for address in ("erin@gmail.com", "erin.rentals@gmail.com", "him@gmail.com"):
        fake_gmail.deliver(address, sender=BANK, subject=f"to {address}", text="x")
    fake_gmail.fail("history", 500)  # the first account polled breaks

    assert await rig.later() == 2
    assert {e.account.id for e in rig.events} == {second.id, his.id}
    # The broken one backs off, then catches up; the others carry on.
    assert first not in rig.sync.due_accounts()
    await rig.later(timedelta(minutes=5))
    assert {e.message.subject for e in rig.events} == {
        "to erin@gmail.com",
        "to erin.rentals@gmail.com",
        "to him@gmail.com",
    }


async def test_rate_limits_are_honoured(rig: Rig, fake_gmail: FakeGmail) -> None:
    await rig.link(rig.family.erin, "erin@gmail.com")
    await rig.sync.poll_all()
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="hi", text="x")
    fake_gmail.fail("history", 429, retry_after=600)
    assert await rig.later() == 0
    assert await rig.later(timedelta(minutes=9)) == 0  # still waiting out Retry-After
    assert await rig.later(timedelta(minutes=2)) == 1


async def test_a_refused_access_token_is_refreshed_and_retried(
    rig: Rig, fake_google: FakeGoogle, fake_gmail: FakeGmail
) -> None:
    await rig.link(rig.family.erin, "erin@gmail.com")
    fake_google.state.access_tokens.clear()  # Google dropped the access token early
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="hi", text="x")
    assert await rig.sync.poll_all() == 1
    assert rig.sender.texts() == []  # no alarm for something a refresh fixes


async def test_a_revoked_token_alerts_its_owner_exactly_once(
    rig: Rig, fake_google: FakeGoogle, fake_gmail: FakeGmail
) -> None:
    account = await rig.link(rig.family.erin, "erin@gmail.com")
    await rig.link(rig.family.husband, "him@gmail.com")
    await rig.sync.poll_all()
    fake_google.revoke_everything_for("erin@gmail.com")
    fake_google.state.access_tokens.clear()

    for _ in range(5):
        await rig.later(timedelta(hours=1))
    assert rig.sender.texts() == [RELINK_ALERT.format(address="erin@gmail.com")]
    assert rig.sender.sent[0][0] == "Erin"
    assert not rig.family.store.get_linked_account(account.id).enabled

    # Linking again fixes it, and a later revocation alerts again (once).
    await rig.link(rig.family.erin, "erin@gmail.com")
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="back", text="x")
    await rig.later()
    assert rig.subjects()[-1] == "back"
    fake_google.revoke_everything_for("erin@gmail.com")
    fake_google.state.access_tokens.clear()
    for _ in range(3):
        await rig.later(timedelta(hours=1))
    assert len(rig.sender.texts()) == 2


async def test_unwatched_accounts_are_not_polled(rig: Rig, fake_gmail: FakeGmail) -> None:
    account = await rig.link(rig.family.erin, "erin@gmail.com")
    rig.family.db.execute("UPDATE linked_accounts SET watched = 0 WHERE id = ?", (account.id,))
    assert await rig.sync.poll_all() == 0
    assert fake_gmail.calls == []


async def test_unlinking_forgets_the_mail(rig: Rig, fake_gmail: FakeGmail) -> None:
    account = await rig.link(rig.family.erin, "erin@gmail.com")
    fake_gmail.deliver("erin@gmail.com", sender=BANK, subject="hi", text="x")
    await rig.sync.poll_all()
    await rig.accounts.unlink(rig.family.erin, account.id)
    assert rig.family.db.scalar("SELECT COUNT(*) FROM emails") == 0


# ----- executors -------------------------------------------------------------


@pytest.fixture
async def mail(rig: Rig, fake_gmail: FakeGmail) -> tuple[ExecutorRegistry, int, str]:
    await rig.link(rig.family.erin, "erin@gmail.com")
    gid = fake_gmail.deliver(
        "erin@gmail.com",
        sender="Dana Landlord <dana@rentals.example>",
        subject="Water heater",
        text="It's leaking.",
    )
    await rig.sync.poll_all()
    registry = ExecutorRegistry()
    install_executors(registry, rig.sync)
    return registry, rig.events[-1].email_id, gid


def ctx(member: Member, key: str = "themi-action-1") -> ExecutionContext:
    return ExecutionContext(1, member, key)


async def run(
    registry: ExecutorRegistry, name: str, payload: dict, context: ExecutionContext
) -> str:
    executor = registry.get(name)
    assert executor is not None
    return await executor(payload, context)


async def test_mark_read_and_archive(rig: Rig, fake_gmail: FakeGmail, mail) -> None:
    registry, email_id, gid = mail
    labels = fake_gmail.mailbox("erin@gmail.com").messages[gid].labels
    await run(registry, "gmail.mark_read", {"email_id": email_id}, ctx(rig.family.erin))
    assert "UNREAD" not in labels and "INBOX" in labels
    result = await run(registry, "gmail.archive", {"email_id": email_id}, ctx(rig.family.erin))
    assert "INBOX" not in labels and result == "Archived: Water heater"


async def test_label_creates_the_label_once(rig: Rig, fake_gmail: FakeGmail, mail) -> None:
    registry, email_id, gid = mail
    for _ in range(2):
        await run(
            registry,
            "gmail.label",
            {"email_id": email_id, "label": "Themi/Rentals"},
            ctx(rig.family.erin),
        )
    box = fake_gmail.mailbox("erin@gmail.com")
    assert box.labels == {"Label_1": "Themi/Rentals"}
    assert box.messages[gid].labels.count("Label_1") == 1


async def test_send_reply_threads_and_never_sends_twice(
    rig: Rig, fake_gmail: FakeGmail, mail
) -> None:
    registry, email_id, _ = mail
    payload = {"email_id": email_id, "body": "Thanks Dana, a plumber is booked for Thursday."}
    for _ in range(2):  # a retry of the same action
        await run(registry, "gmail.send_reply", payload, ctx(rig.family.erin, "themi-action-7"))
    (sent,) = fake_gmail.mailbox("erin@gmail.com").sent
    assert sent["headers"]["To"] == "Dana Landlord <dana@rentals.example>"
    assert sent["headers"]["From"] == "erin@gmail.com"
    assert sent["headers"]["Subject"] == "Re: Water heater"
    assert sent["headers"]["In-Reply-To"] == sent["headers"]["References"]
    assert sent["threadId"] is not None
    assert sent["body"] == "Thanks Dana, a plumber is booked for Thursday."


async def test_executors_only_touch_the_members_own_mail(
    rig: Rig, fake_gmail: FakeGmail, mail
) -> None:
    registry, email_id, gid = mail
    with pytest.raises(PermissionError):
        await run(registry, "gmail.archive", {"email_id": email_id}, ctx(rig.family.husband))
    assert "INBOX" in fake_gmail.mailbox("erin@gmail.com").messages[gid].labels
