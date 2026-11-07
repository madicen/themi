"""CR2c: the Google modules. Each brings a connector with the features built on it.

- `google`: linking Google accounts (OAuth), which Gmail, Calendar, Tasks and the
  cookbook all go through.
- `gmail`: reading mail, with triage, forwarding, urgent-sender suggestions, expected
  emails and the noise digest.
- `calendar`: calendars read and written, busy times, events, twins, copies and blocks.
"""

from __future__ import annotations

from datetime import timedelta

from themi.connectors.gcal import CalendarSync
from themi.connectors.gcal.busy import CalendarBusy
from themi.connectors.gcal.preferences import CalendarPreferences
from themi.connectors.gmail import GmailSync, install_executors
from themi.connectors.google import GoogleAccounts, GoogleConfig, GoogleOAuth
from themi.core import email_forward, groups
from themi.core.approvals import ApprovalsUI
from themi.core.calendar import TaskCalendar
from themi.core.calendar_copies import CalendarCopies
from themi.core.calendar_twins import CalendarTwins
from themi.core.connector_settings import GoogleSettings
from themi.core.events import Events
from themi.core.expected import ExpectedEmails
from themi.core.noise_digest import NoiseDigest, NoisePreferences
from themi.core.senders import SenderSuggestions
from themi.core.task_blocks import TaskBlocks
from themi.core.tasks import TaskBoard
from themi.core.triage import EmailTriage
from themi.energy import EnergyModel
from themi.modules import Module, ModuleContext, ModuleSetup, as_job
from themi.modules.prompt import PromptFragment


class GoogleModule(Module):
    """Linking Google accounts, for the Google modules that read and write through them."""

    name = "google"
    website = "Each person links their Google account on Accounts (/accounts)."
    settings = GoogleSettings

    def __init__(self, config: GoogleConfig) -> None:
        self.config = config

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        google = setup.read(GoogleSettings).config()
        return cls(google) if google else None

    def install(self, ctx: ModuleContext) -> None:
        store = ctx.services.store
        google = GoogleAccounts(store, GoogleOAuth(store.db, store.cipher, self.config))
        ctx.provide(google)
        ctx.periodic(
            "google.forget_states", timedelta(days=1), as_job(google.oauth.forget_expired_states)
        )


class GmailModule(Module):
    """Gmail: mail read every minute, triaged, and the features that follow from it."""

    name = "gmail"
    tool_groups = (groups.EMAIL,)
    preferences = NoisePreferences
    requires = ("google",)

    def install(self, ctx: ModuleContext) -> None:
        ctx.settings_section("settings/email.html", 70)
        s = ctx.services
        gmail = GmailSync(s.store, ctx.get(GoogleAccounts), s.outbox)
        ctx.provide(gmail)
        install_executors(s.autonomy.executors, gmail)
        triage = ctx.provide(EmailTriage(s, gmail))
        triage.install()
        email_forward.install(s)  # F31d
        senders = ctx.provide(SenderSuggestions(s))
        senders.install()
        expected = ctx.provide(ExpectedEmails(s, gmail))
        expected.install()
        noise = ctx.provide(NoiseDigest(s, ctx.get(ApprovalsUI), gmail))
        noise.install()
        from themi.web import email_pages

        ctx.web(email_pages.routes)  # the noise digest's page
        ctx.periodic("gmail.poll", timedelta(minutes=1), gmail.poll_all)
        ctx.periodic("email.triage", timedelta(minutes=1), triage.run)
        ctx.periodic("email.senders", timedelta(hours=6), senders.offer)
        ctx.periodic("email.noise", timedelta(minutes=5), noise.run)
        ctx.periodic("email.expected", timedelta(hours=1), expected.check_overdue)


# CR8a: the system prompt's rules about this module's feature.
CALENDAR_PROMPT_RULES = (
    PromptFragment(
        "calendar.an-appointment-or-event",
        "act",
        120,
        """\
- An appointment or event at a set time ("the dentist Tuesday at 3") goes on a calendar
  (add_calendar_event, theirs or the family's); something they have to do is a task.""",
    ),
)


class CalendarModule(Module):
    """Google Calendar: each person's calendars, events made from chat, and busy times that
    hold Themi's own messages."""

    name = "calendar"
    tool_groups = (groups.CALENDAR,)
    preferences = CalendarPreferences
    requires = ("google", "tasks")

    def install(self, ctx: ModuleContext) -> None:
        ctx.prompt(*CALENDAR_PROMPT_RULES)
        s = ctx.services
        sync = CalendarSync(s.store, ctx.get(GoogleAccounts))
        ctx.provide(sync)
        tasks = ctx.get(TaskBoard)
        ctx.provide(TaskCalendar(s, tasks, sync, ctx.scheduler)).install()
        busy = CalendarBusy(s.store, sync)
        ctx.provide(busy)
        s.calendar_source = busy.context
        s.outbox.calendar_blocks = busy.blocks
        ctx.get(EnergyModel).calendar_blocks = busy.blocks
        events = ctx.provide(Events(s))
        events.install()
        ctx.provide(CalendarTwins(s, events)).install()  # F34e: the same event twice
        ctx.provide(CalendarCopies(s)).install()  # F34f: a calendar on the family calendar
        blocks = ctx.provide(TaskBlocks(s, tasks))
        blocks.install()
        ctx.periodic("calendar.busy", timedelta(minutes=15), busy.refresh)
        ctx.periodic("blocks.tick", timedelta(minutes=5), blocks.tick)
