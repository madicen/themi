"""CR2c: the family's module list, with every connector and with each one left out."""

from __future__ import annotations

from typing import Any

import pytest

from tests.fakes.telegram_api import BOT_TOKEN, FakeTelegram
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from themi.app import App, build_app, family_modules
from themi.channels.telegram import TelegramChannel
from themi.config import Template
from themi.modules import Module
from themi.storage.secrets import Secret

CONNECTOR_FIXTURES = (
    "fake_google",
    "fake_gmail",
    "fake_gcal",
    "fake_gtasks",
    "fake_gdocs",
    "fake_ourgroceries",
    "fake_cozyla",
    "fake_travel",
    "fake_search",
    "fake_home_connect",
    "fake_spotify",
    "fake_thinq",
    "fake_roborock",
    "fake_tuya",
    "fake_catgenie",
    "fake_keep",
)
# The modules that come with a connector, and the jobs each brings.
CONNECTOR_MODULES = {
    "google": {"google.forget_states"},
    "gmail": {"gmail.poll"},
    # CR18b: Gmail's and the calendar's features are modules of their own
    "email_triage": {"email.triage"},
    "email_forwarding": set(),
    "urgent_senders": {"email.senders"},
    "expected_emails": {"email.expected"},
    "noise_digest": {"email.noise"},
    "email_audit": set(),
    "calendar": set(),
    "calendar_busy": {"calendar.busy"},
    "calendar_twins": set(),
    "calendar_copies": set(),
    "task_blocks": {"blocks.tick"},
    "google_tasks": {"google_tasks.inbox"},
    "travel": {"travel.heads_up"},
    "spotify": set(),
    "ourgroceries": {"groceries.mirror"},
    "keep": {"groceries.keep"},
    "cozyla_todos": {"cozyla.sync"},
    "cozyla_chores": {"cozyla.chores", "cozyla.routines", "routines.wall"},
    "home_connect": {"devices.dishwasher", "devices.dishwasher_pace"},
    "thinq": {"devices.thinq", "devices.thinq_push", "laundry.fresh"},
    "roborock": {"devices.vacuum", "vacuum.wall"},
    "tuya": {"devices.feeders"},
    "catgenie": {"devices.litter_box"},
}
# Leaving one out leaves out what requires it.
GMAIL_FEATURES = {"email_triage", "email_forwarding", "urgent_senders", "expected_emails",
                  "noise_digest"}  # fmt: skip
CALENDAR_FEATURES = {"calendar_busy", "calendar_twins", "calendar_copies", "task_blocks"}
NEEDS = {
    "google": {"gmail", "email_audit", "calendar", "google_tasks"}
    | GMAIL_FEATURES
    | CALENDAR_FEATURES,
    "gmail": {"email_audit"} | GMAIL_FEATURES,
    "email_triage": {"expected_emails", "noise_digest"},
    "calendar": CALENDAR_FEATURES,
    "calendar_busy": {"calendar_twins", "calendar_copies"},
}


@pytest.fixture
def options(family: SeededFamily, request: pytest.FixtureRequest) -> dict[str, Any]:
    fakes = {name: request.getfixturevalue(name) for name in CONNECTOR_FIXTURES}
    return connector_options(
        **{name.removeprefix("fake_"): fake for name, fake in fakes.items()},
        timezone=family.family.timezone,
    )


def build(
    family: SeededFamily,
    telegram: FakeTelegram,
    modules: list[Module],
    template: Template | None = None,
) -> App:
    return build_app(
        family.db,
        family.store.cipher,
        lambda store: TelegramChannel.from_token(
            Secret(BOT_TOKEN), store, None, base_url=telegram.base_url, poll_timeout=0
        ),
        modules=modules,
        template=template,
    )


def test_every_connector_module_is_in_the_list_when_configured(options: dict[str, Any]) -> None:
    names = [m.name for m in family_modules(**options)]
    assert set(CONNECTOR_MODULES) <= set(names)
    assert len(names) == len(set(names))


def test_no_connector_leaves_only_the_modules_that_need_none() -> None:
    names = {m.name for m in family_modules()}
    assert not names & set(CONNECTOR_MODULES)
    assert {"tasks", "groceries", "recipes", "web_search", "appliances"} <= names


@pytest.mark.parametrize("left_out", sorted(CONNECTOR_MODULES))
def test_the_app_builds_with_a_connector_module_left_out(
    family: SeededFamily, fake_telegram: FakeTelegram, options: dict[str, Any], left_out: str
) -> None:
    gone = {left_out, *NEEDS.get(left_out, set())}
    modules = [m for m in family_modules(**options) if m.name not in gone]
    app = build(family, fake_telegram, modules)
    jobs = {job.name for job in app.periodic}
    for name in gone:
        assert not jobs & CONNECTOR_MODULES[name], f"{name}'s jobs are still there"
    assert {"tasks.resurface", "outbox.flush"} <= jobs


# ----- CR18b: Gmail and the calendar, a base and feature modules --------------------------

FEATURES = sorted(GMAIL_FEATURES | CALENDAR_FEATURES)


def requirements(name: str, modules: list[Module]) -> set[str]:
    by_name = {m.name: m for m in modules}
    out: set[str] = set()
    for need in by_name[name].requires:
        out |= {need, *requirements(need, modules)}
    return out


@pytest.mark.parametrize("feature", FEATURES)
def test_each_feature_module_installs_alone_on_its_base(
    family: SeededFamily, fake_telegram: FakeTelegram, options: dict[str, Any], feature: str
) -> None:
    every = family_modules(**options)
    others = set(FEATURES) - {feature} - requirements(feature, every)
    gone = others | {"email_audit"}  # the audit leans on triage's answers
    app = build(family, fake_telegram, [m for m in every if m.name not in gone])
    assert feature in [m.name for m in app.modules]
    assert not {m.name for m in app.modules} & others
    jobs = {job.name for job in app.periodic}
    assert CONNECTOR_MODULES[feature] <= jobs
    for name in others:
        assert not jobs & CONNECTOR_MODULES[name]


def test_the_bases_work_with_no_features(
    family: SeededFamily, fake_telegram: FakeTelegram, options: dict[str, Any]
) -> None:
    gone = set(FEATURES) | {"email_audit"}
    app = build(family, fake_telegram, [m for m in family_modules(**options) if m.name not in gone])
    names = {m.name for m in app.modules}
    assert {"gmail", "calendar"} <= names and not names & gone
    assert "gmail.poll" in {job.name for job in app.periodic}
    tools = {spec.name for spec in app.services.tools.specs()}
    assert "add_calendar_event" in tools  # the base's events
    assert "block_time_for_task" not in tools and "archive_noise_emails" not in tools
