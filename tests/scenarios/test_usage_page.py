"""UC5: the Usage page: the card, each meter's month, and the household's own limits."""

from __future__ import annotations

from datetime import date

import httpx

from tests.fixtures.web import flash, sign_in
from tests.scenarios.harness import Scenario
from themi.standard.usage_card import collect
from themi.web.usage_pages import stale

KEY = "gemini.requests"


def gemini_bar(scenario: Scenario) -> float:
    (ai,) = [g for g in collect(scenario.app.services.usage).groups if g.name == "AI"]
    (row,) = [r for r in ai.rows if r.label.startswith("Gemini")]
    assert row.share is not None
    return row.share


async def test_the_page_is_for_admins(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Husband")
    response = await site.get("/admin/usage")
    assert response.status_code != 200
    assert "Each service" not in response.text


async def test_an_admin_lowers_the_gemini_limit_and_sees_the_bar_move(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    scenario.app.services.usage.count(KEY, 80)
    csrf = await sign_in(scenario, site, "Erin")
    page = await site.get("/admin/usage")
    assert page.status_code == 200
    assert "<svg" in page.text and "Gemini" in page.text
    assert "500 a day" in page.text and "From the module" in page.text
    assert gemini_bar(scenario) == 80 / 500

    saved = await site.post(f"/admin/usage/{KEY}/limit", data={"csrf": csrf, "per_day": "100"})
    assert saved.status_code == 303
    text = await flash(site, "/admin/usage")
    assert "the household&#39;s limit is saved" in text or "the household's limit is saved" in text
    assert "Set by Erin" in text and "100 a day" in text
    assert gemini_bar(scenario) == 80 / 100

    back = await site.post(f"/admin/usage/{KEY}/limit", data={"csrf": csrf, "clear": "1"})
    assert back.status_code == 303
    assert gemini_bar(scenario) == 80 / 500


async def test_a_limit_must_be_a_whole_number(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    await site.post(f"/admin/usage/{KEY}/limit", data={"csrf": csrf, "per_day": "lots"})
    assert "whole number" in await flash(site, "/admin/usage")
    limit = scenario.app.services.usage.limit_for(KEY)
    assert limit is not None and not limit.overridden


async def test_a_module_with_meters_links_to_its_rows(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    await sign_in(scenario, site, "Erin")
    page = await site.get("/modules/gemini")
    assert "/admin/usage#module-gemini" in page.text


def test_a_limit_checked_over_six_months_ago_is_marked() -> None:
    today = date(2026, 11, 18)
    assert not stale("2026-11", today)
    assert not stale("2026-05", today)
    assert stale("2026-04", today)
    assert not stale("", today)
