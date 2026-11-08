"""CR2c: the modules that come with one outside service each.

Each takes its connector's client or config in its constructor, and is in the module
list only when that service is set up. What the module's feature does lives in its own
file; this one only wires the connector to it.
"""

from __future__ import annotations

from datetime import timedelta

from themi.connectors.travel import TravelClient
from themi.core import groups
from themi.core.agent import Agent
from themi.modules import Module, ModuleContext, ModuleSetup
from themi.modules.prompt import PromptFragment
from themi.standard.tasks import TaskBoard
from themi_google import google_groups
from themi_google.connectors.google import TASKS_SCOPE, GoogleAccounts, ScopeNeed
from themi_google.email_audit import EmailAudit
from themi_google.google_settings import GoogleSettings, TravelSettings
from themi_google.google_tasks import GoogleTasksInbox
from themi_google.google_tasks_list import GoogleTaskList
from themi_google.travel import TravelHeadsUps, TravelPreferences


class EmailAuditModule(Module):
    """E2: the email audit, over Gmail."""

    name = "email_audit"
    tool_groups = (google_groups.EMAIL,)
    requires = ("tasks", "gmail")

    def install(self, ctx: ModuleContext) -> None:
        ctx.provide(EmailAudit(ctx.services, ctx.get(TaskBoard))).install()


class GoogleTasksModule(Module):
    """GT1: a Google Tasks list as an inbox, and Themi's tasks kept in step with it."""

    name = "google_tasks"
    requires = ("google", "tasks")
    google_scopes = (
        ScopeNeed(
            "Google Tasks",
            (TASKS_SCOPE,),
            "Google Tasks isn't allowed for this account yet. Linking it again lets Themi take "
            "what you add to Google Tasks by voice.",
        ),
    )

    def __init__(self, tasks_url: str) -> None:
        self.tasks_url = tasks_url

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        google = setup.read(GoogleSettings, "google").config()
        return cls(google.tasks_url) if google else None

    def install(self, ctx: ModuleContext) -> None:
        s = ctx.services
        inbox = ctx.provide(GoogleTasksInbox(s, ctx.get(GoogleAccounts), self.tasks_url))
        inbox.task_list = GoogleTaskList(s, ctx.get(TaskBoard))  # GT1b
        inbox.install(ctx.get(Agent))
        ctx.periodic("google_tasks.inbox", timedelta(minutes=1), inbox.run)


# CR8a: the system prompt's rules about this module's feature.
TRAVEL_PROMPT_RULES = (
    PromptFragment(
        "travel.for-an-event-with",
        "act",
        140,
        """\
- For an event with an address, a heads-up to get ready goes out at the leave time minus that
  person's "getting ready" minutes (My settings), to whoever's calendar it's on; drive_time
  says when. Never say there are no advance reminders. Extra reminders they ask for ("remind
  me at 2 and 3 about tutoring") are add_reminder, one each: a message, not a task.""",
    ),
)


class TravelModule(Module):
    """K4: travel times, and "time to get ready"."""

    name = "travel"
    tool_groups = (groups.CALENDAR,)
    preferences = TravelPreferences
    settings = TravelSettings

    def __init__(self, client: TravelClient) -> None:
        self.client = client

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        return cls(TravelClient(setup.read(TravelSettings).tomtom_api_key))

    async def check(self) -> str | None:
        try:
            found = await self.client.geocode("Pike Place Market, Seattle")
        except Exception as exc:  # whatever went wrong, said once, for the wizard
            return f"The map service didn't answer: {exc}"
        return None if found is not None else "The map service found nothing for a test address."

    def install(self, ctx: ModuleContext) -> None:
        ctx.prompt(*TRAVEL_PROMPT_RULES)
        heads_ups = ctx.provide(TravelHeadsUps(ctx.services, self.client))
        heads_ups.install()
        ctx.periodic("travel.heads_up", timedelta(minutes=5), heads_ups.heads_up)
