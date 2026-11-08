"""CR2c: the Google modules. Each brings a connector with the features built on it.

- `google`: linking Google accounts (OAuth), which Gmail, Calendar, Tasks and the
  cookbook all go through.
- `gmail`: reading mail, and the email tools. CR18b: triage, forwarding, urgent senders,
  expected emails and the noise digest are modules on top of it.
- `calendar`: calendars read and written, events, and tasks on the family calendar.
  CR18b: busy times, task blocks, twins and copies are modules on top of it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from themi.accounts import Member
from themi.core import groups
from themi.core.approvals import ApprovalsUI
from themi.core.calendar_view import CalendarPreferences
from themi.energy import EnergyModel
from themi.modules import Module, ModuleContext, ModuleSetup, as_job
from themi.modules.prompt import PromptFragment
from themi.modules.web import WaitingLink
from themi.standard.tasks import TaskBoard
from themi_google import email_forward, google_groups
from themi_google.calendar import TaskCalendar
from themi_google.calendar_copies import CalendarCopies
from themi_google.calendar_twins import CalendarTwins
from themi_google.connectors.gcal import CalendarSync
from themi_google.connectors.gcal.busy import CalendarBusy
from themi_google.connectors.gmail import GmailSync, install_executors
from themi_google.connectors.google import (
    CALENDAR_SCOPES,
    GMAIL_SCOPE,
    GoogleAccounts,
    GoogleConfig,
    GoogleOAuth,
    ScopeNeed,
)
from themi_google.events import Events
from themi_google.expected import ExpectedEmails
from themi_google.google_settings import GoogleSettings
from themi_google.noise_digest import NoiseDigest, NoisePreferences
from themi_google.senders import SenderSuggestions
from themi_google.task_blocks import TaskBlocks
from themi_google.triage import EmailTriage


def needs_of(modules: list[Module]) -> list[ScopeNeed]:
    """CR18a: what the loaded modules need from a Google account, each declaring it as
    `google_scopes` (a tuple of ScopeNeed); a module without it needs nothing."""
    return [need for m in modules for need in getattr(m, "google_scopes", ())]


class GoogleModule(Module):
    """Linking Google accounts, for the Google modules that read and write through them."""

    name = "google"
    kind = "connector"
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
        google.wants = lambda: needs_of(ctx.modules)  # CR18a: asked when linking
        ctx.provide(google)
        from themi_google.web import google_pages

        ctx.web(google_pages.routes)  # sign in with Google, and linking accounts
        ctx.accounts_section(  # CR17a: first on Accounts
            "accounts/google.html", 10, values=google_pages.section_values(ctx.services)
        )
        ctx.periodic(
            "google.forget_states", timedelta(days=1), as_job(google.oauth.forget_expired_states)
        )


class GmailModule(Module):
    """Gmail: mail read every minute, and the email tools. CR18b: what follows from the
    mail (triage, forwarding, urgent senders, expected emails, the noise digest) is in
    modules of its own that require this one."""

    name = "gmail"
    kind = "connector"
    google_scopes = (ScopeNeed("Gmail", (GMAIL_SCOPE,)),)
    tool_groups = (google_groups.EMAIL,)
    requires = ("google",)

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        gmail = GmailSync(s.store, ctx.get(GoogleAccounts), s.outbox)
        ctx.provide(gmail)
        install_executors(s.autonomy.executors, gmail)
        ctx.periodic("gmail.poll", timedelta(minutes=1), gmail.poll_all)


class EmailTriageModule(Module):
    """New mail sorted: what needs them now, what can wait, what's noise (CR18b)."""

    name = "email_triage"
    requires = ("gmail",)

    def install(self, ctx: ModuleContext) -> None:
        triage = ctx.provide(EmailTriage(ctx.services, ctx.get(GmailSync)))
        triage.install()
        ctx.periodic("email.triage", timedelta(minutes=1), triage.run)


class EmailForwardingModule(Module):
    """F31d: forwarding an email to someone, from chat (CR18b)."""

    name = "email_forwarding"
    requires = ("gmail",)

    def install(self, ctx: ModuleContext) -> None:
        email_forward.install(ctx.services)


class UrgentSendersModule(Module):
    """Senders who always count as time-sensitive, and suggestions of new ones (CR18b)."""

    name = "urgent_senders"
    requires = ("gmail",)

    def install(self, ctx: ModuleContext) -> None:
        senders = ctx.provide(SenderSuggestions(ctx.services))
        senders.install()
        ctx.periodic("email.senders", timedelta(hours=6), senders.offer)


class ExpectedEmailsModule(Module):
    """Recurring mail that should arrive, and a word when it doesn't (CR18b). It sees mail
    through triage."""

    name = "expected_emails"
    requires = ("gmail", "email_triage")

    def install(self, ctx: ModuleContext) -> None:
        expected = ctx.provide(ExpectedEmails(ctx.services, ctx.get(GmailSync)))
        expected.install()
        ctx.periodic("email.expected", timedelta(hours=1), expected.check_overdue)


class NoiseDigestModule(Module):
    """F16b: emails that look like noise, offered for archiving all together (CR18b). Triage
    finds them."""

    name = "noise_digest"
    preferences = NoisePreferences  # kept under "gmail", where they always were
    requires = ("gmail", "email_triage")

    def install(self, ctx: ModuleContext) -> None:
        ctx.settings_section("settings/email.html", 70)
        s = ctx.services
        noise = ctx.provide(NoiseDigest(s, ctx.get(ApprovalsUI), ctx.get(GmailSync)))
        noise.install()
        ctx.waiting_link(noise_link(noise))  # CR17a: one link on the dashboard, not a card each
        from themi_google.web import email_pages

        ctx.web(email_pages.routes)  # the noise digest's page
        ctx.periodic("email.noise", timedelta(minutes=5), noise.run)


def noise_link(noise: NoiseDigest) -> Callable[[Member], WaitingLink | None]:
    """F16b: the emails that look like noise, as one line in "Waiting on you"."""

    def link(member: Member) -> WaitingLink | None:
        waiting = noise.waiting(member)
        if not waiting:
            return None
        n = len(waiting)
        return WaitingLink(
            "/email/noise",
            f"{n} email{'' if n == 1 else 's'} that look like noise, to archive or keep",
            frozenset(a.id for a in waiting),
        )

    return link


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
    """Google Calendar: each person's calendars, events made from chat, and tasks with
    dates on the family calendar. CR18b: busy times, task blocks, twins and copies are in
    modules of their own that require this one."""

    name = "calendar"
    kind = "connector"
    google_scopes = (ScopeNeed("the calendar", CALENDAR_SCOPES),)
    tool_groups = (groups.CALENDAR,)
    preferences = CalendarPreferences
    requires = ("google", "tasks")

    def install(self, ctx: ModuleContext) -> None:
        ctx.prompt(*CALENDAR_PROMPT_RULES)
        s = ctx.services
        from themi_google.web import google_pages

        ctx.accounts_section(  # CR17a: the family calendar, under Household connections
            "accounts/family_calendar.html",
            60,
            values=google_pages.calendar_values(s),
            routes=google_pages.calendar_routes,
            household=True,
        )
        sync = CalendarSync(s.store, ctx.get(GoogleAccounts))
        ctx.provide(sync)
        ctx.provide(TaskCalendar(s, ctx.get(TaskBoard), sync, ctx.scheduler)).install()
        ctx.provide(Events(s)).install()


class CalendarBusyModule(Module):
    """Each person's calendars read every 15 minutes (CR18b): busy times hold Themi's own
    messages and count against the day's energy, and the agent sees what's on."""

    name = "calendar_busy"
    requires = ("calendar",)

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        busy = CalendarBusy(s.store, ctx.get(CalendarSync))
        ctx.provide(busy)
        s.calendar_source = busy.context
        s.outbox.calendar_blocks = busy.blocks
        ctx.get(EnergyModel).calendar_blocks = busy.blocks
        ctx.periodic("calendar.busy", timedelta(minutes=15), busy.refresh)


class CalendarTwinsModule(Module):
    """F34e: the same event on two calendars, asked about once (CR18b)."""

    name = "calendar_twins"
    requires = ("calendar", "calendar_busy")

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(CalendarTwins(ctx.services, ctx.get(Events))).install()


class CalendarCopiesModule(Module):
    """F34f: a calendar shown on the family calendar, as much of it as they choose (CR18b)."""

    name = "calendar_copies"
    requires = ("calendar", "calendar_busy")

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(CalendarCopies(ctx.services)).install()


class TaskBlocksModule(Module):
    """Time held on the calendar for a task (CR18b)."""

    name = "task_blocks"
    requires = ("calendar",)
    optional = ("calendar_busy",)  # windows outside busy times, when it's there

    def install(self, ctx: ModuleContext) -> None:
        blocks = ctx.provide(TaskBlocks(ctx.services, ctx.get(TaskBoard)))
        blocks.install()
        ctx.periodic("blocks.tick", timedelta(minutes=5), blocks.tick)
