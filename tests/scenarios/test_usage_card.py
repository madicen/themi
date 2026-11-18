"""UC4: an admin asks /usage and gets the usage card; anyone else is told it's for admins."""

from __future__ import annotations

from tests.scenarios.harness import Scenario


async def test_an_admin_gets_the_card_and_a_member_is_told_its_for_admins(
    scenario: Scenario,
) -> None:
    usage = scenario.app.services.usage
    usage.count("gemini.requests", 120, scope="1")
    usage.count("homeconnect.calls", 40)
    assert await scenario.say("Erin", "/usage") == ["How much Themi used today and this month."]
    (picture,) = scenario.pictures("Erin")
    assert picture["caption"] == "How much Themi used today and this month."
    assert await scenario.say("Husband", "/usage") == ["That's for the household's admins."]
    assert scenario.pictures("Husband") == []
