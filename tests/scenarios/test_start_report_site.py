"""SP1: what didn't start is said on an admin's dashboard, and nobody else's."""

from __future__ import annotations

from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.fixtures.web import sign_in, web_client
from tests.scenarios.harness import Scenario
from themi.app import family_modules
from themi.modules import StartReport


async def test_an_admin_sees_that_themi_has_no_ai_provider(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    modules = [
        m
        for m in family_modules(**connector_options(timezone=family.family.timezone))
        if type(m).kind != "ai"
    ]
    scenario = Scenario(family, fake_telegram, modules=modules)
    await scenario.start()
    try:
        assert not scenario.app.services.start_report.has_ai()
        async with web_client(scenario) as admin:
            await sign_in(scenario, admin, "Erin")
            home = (await admin.get("/")).text
            assert "Themi has no AI provider yet, so it can&#39;t answer." in home
        async with web_client(scenario) as member:
            await sign_in(scenario, member, "Husband")
            assert "no AI provider" not in (await member.get("/")).text
    finally:
        await scenario.stop()


async def test_a_module_that_couldnt_start_is_on_the_admins_dashboard(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    scenario = Scenario(family, fake_telegram)
    report: StartReport = scenario.app.services.start_report
    report.note("travel", "failed", "connector", "TomTom turned the key down")
    await scenario.start()
    try:
        async with web_client(scenario) as admin:
            await sign_in(scenario, admin, "Erin")
            home = (await admin.get("/")).text
            assert "travel couldn&#39;t start: TomTom turned the key down" in home
            assert "no AI provider" not in home
    finally:
        await scenario.stop()
