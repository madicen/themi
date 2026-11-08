"""CR7a: the settings page's form is the same for the family with every module loaded,
and a module's own section goes when the module isn't there."""

from __future__ import annotations

import re

import httpx
import pytest

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from tests.scenarios.test_golden import CONNECTORS

# Every field on the form before CR7a, with every connector set up.
BEFORE_CR7A = [
    "break_extend_minutes", "calendar_details", "calendar_twins", "chart_counts_shared",
    "chart_limit", "checkin_reviews", "csrf", "daily_limit", "day_budget", "day_ends",
    "done_praise", "focus_count", "getting_ready_minutes", "job_mode_admin", "job_mode_chores",
    "job_mode_deep_work", "job_mode_other", "job_mode_tidy", "leave_heads_up", "list_style",
    "listen_first", "morning_summary", "morning_summary_empty", "noise_emails", "pda_enabled",
    "pda_strength", "phrasing", "phrasing_notes", "quiet_end", "quiet_start", "setup_note",
    "sprint_break_minutes", "sprint_work_minutes", "track_calendar", "track_device_activity",
    "track_message_timing", "track_reactions", "track_text_notes",
]  # fmt: skip


async def form_fields(scenario: Scenario, site: httpx.AsyncClient) -> list[str]:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    form = page[page.index('<form method="post" action="/settings"') :]
    return sorted(set(re.findall(r'name="([^"]+)"', form[: form.index("</form>")])))


@pytest.mark.usefixtures(*CONNECTORS)
async def test_the_family_form_is_as_it_was(scenario: Scenario, site: httpx.AsyncClient) -> None:
    assert await form_fields(scenario, site) == BEFORE_CR7A


async def test_the_chart_section_comes_with_the_chore_chart_not_the_wall(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    """CR21a: the chart is its own module, so its section is there with no wall (the
    chore_chart module left out takes it: tests/scenarios/test_chore_chart_module.py)."""
    fields = await form_fields(scenario, site)  # no Cozyla here
    assert "chart_limit" in fields and "chart_counts_shared" in fields
    assert {"break_extend_minutes", "sprint_work_minutes"} <= set(fields)


@pytest.mark.usefixtures("fake_cozyla")
async def test_saving_the_form_saves_the_preferences(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    from themi.standard.breaks import BreaksPreferences
    from themi_home.body_double import BodyDoublePreferences

    csrf = await sign_in(scenario, site, "Erin")
    form = {
        "csrf": csrf,
        "break_extend_minutes": "20",
        "sprint_work_minutes": "45",
        "sprint_break_minutes": "10",
        "chart_limit": "2",
        "chart_counts_shared": "on",
    }
    assert (await site.post("/settings", data=form)).status_code == 303
    erin = scenario.member("Erin")
    store = scenario.app.store
    assert store.preferences(erin.id, BreaksPreferences).break_extend_minutes == 20
    bd = store.preferences(erin.id, BodyDoublePreferences)
    assert (bd.sprint_work_minutes, bd.sprint_break_minutes) == (45, 10)
    bad = await site.post("/settings", data={**form, "sprint_work_minutes": "200"})
    assert bad.status_code == 400 and "a sprint&#39;s work block is between" in bad.text


async def section_ids(scenario: Scenario, site: httpx.AsyncClient) -> list[str]:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/settings")).text
    form = page[page.index('<form method="post" action="/settings"') :]
    form = form[: form.index("</form>")]
    return re.findall(r'<details[^>]* id="([a-z-]+)"', form) or re.findall(
        r'class="row[^"]*" id="([a-z-]+)"', form
    )


# CR7d: the sections, in the order the page had before they came from modules.
SECTIONS = [
    "quiet", "limit", "breaks", "body-double", "chart", "calendars", "email", "phrasing",
    "pda", "tracking",
]  # fmt: skip


@pytest.mark.usefixtures(*CONNECTORS)
async def test_the_family_sections_keep_their_order(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    assert await section_ids(scenario, site) == SECTIONS


async def test_a_module_left_out_takes_its_section_with_it(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    found = await section_ids(scenario, site)  # no Gmail (CR21a: the chart needs no wall)
    assert found == [s for s in SECTIONS if s != "email"]
