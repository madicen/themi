"""MP7: a module's page, quicker to use: where it sits, a setup checklist, Test only with a
check, Works with with switches; links from "isn't set up" messages; a template switch by
group."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.config import parse_config
from themi.core import keys
from themi.modules.store import ConfigAudit


@asynccontextmanager
async def admin(scenario: Scenario) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    async with web_client(scenario) as client:
        csrf = await sign_in(scenario, client, "Erin")
        yield client, csrf


async def test_breadcrumb_and_the_groups_others(scenario: Scenario) -> None:
    async with admin(scenario) as (site, _):
        page = (await site.get("/modules/cooking_timers")).text
    crumb = page.split('class="breadcrumb"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/modules#group-cooking">Cooking</a>' in crumb and "Cooking timers" in crumb
    others = page.split('class="module-neighbours card"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/modules/recipes"' in others and 'aria-current="page">Cooking timers' in others
    assert 'data-depth="3"' in others


async def test_the_checklist_ticks_from_state(scenario: Scenario) -> None:
    scenario.app.services.instance_config = parse_config({"template": "empty"})
    async with admin(scenario) as (site, csrf):
        off = (await site.get("/modules/web_search")).text
        assert "Setting it up" not in off  # not on: nothing to check off yet
        await site.post("/modules/web_search/switch", data={"csrf": csrf, "to": "on"})
        page = (await site.get("/modules/web_search")).text
    steps = page.split('class="card setup-steps"', 1)[1].split("</section>", 1)[0]
    assert '<li class="done"><span aria-label="done">✓</span> Turned on' in steps
    assert '<li class="todo"><span aria-label="to do">○</span> Tested' in steps
    assert "Running (restarted since the last change)" in steps


async def test_no_test_button_without_a_check(scenario: Scenario) -> None:
    async with admin(scenario) as (site, _):
        breaks = (await site.get("/modules/breaks")).text
        search = (await site.get("/modules/web_search")).text
    assert 'action="/modules/breaks/test"' not in breaks
    assert 'action="/modules/web_search/test"' in search


async def test_the_last_test_result_is_shown(scenario: Scenario) -> None:
    ConfigAudit(scenario.app.db).note(None, "tested Web search: Web search worked.")
    async with admin(scenario) as (site, _):
        page = (await site.get("/modules/web_search")).text
    assert "Last test" in page and "Web search worked." in page


async def test_an_off_requirement_can_be_turned_on_from_works_with(scenario: Scenario) -> None:
    scenario.app.services.instance_config = parse_config({"template": "empty"})
    async with admin(scenario) as (site, csrf):
        page = (await site.get("/modules/cooking")).text
        needs = page.split("It needs", 1)[1].split("</ul>", 1)[0]
        assert 'aria-label="Turn on Family cookbook"' in needs
        sheet = await site.post(
            "/modules/recipes/switch", data={"csrf": csrf, "to": "on", "back": "cooking"}
        )
        assert '<input type="hidden" name="back" value="cooking">' in sheet.text  # add-ons
        done = await site.post(
            "/modules/recipes/switch",
            data={"csrf": csrf, "to": "on", "back": "cooking", "confirmed": "1"},
        )
    assert done.headers["location"] == "/modules/cooking#works-with"


async def test_not_set_up_links_admins_to_the_module(scenario: Scenario) -> None:
    scenario.app.services.provide(keys.groceries, None)
    async with web_client(scenario) as site:
        csrf = await sign_in(scenario, site, "Erin")
        await site.post("/groceries/add", data={"csrf": csrf, "item": "milk"})
        page = (await site.get("/lists")).text
    assert "The grocery list isn&#39;t set up on this server." in page
    assert '<a href="/modules/groceries">Set it up</a>' in page
    async with web_client(scenario) as site:
        csrf = await sign_in(scenario, site, "Husband")
        await site.post("/groceries/add", data={"csrf": csrf, "item": "milk"})
        page = (await site.get("/lists")).text
    assert "The grocery list isn&#39;t set up on this server." in page
    assert "Set it up" not in page


async def test_a_template_switch_is_compared_group_by_group(scenario: Scenario) -> None:
    async with admin(scenario) as (site, csrf):
        page = (await site.post("/modules/template", data={"csrf": csrf, "template": "work"})).text
    table = page.split('class="template-compare"', 1)[1].split("</table>", 1)[0]
    cooking = table.split('<th scope="row">Cooking</th>', 1)[1].split("</tr>", 1)[0]
    assert "Family cookbook" in cooking
