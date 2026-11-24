"""F61c (bug #267): Michael's fallback model, retired, answered 404 on every call, and
nobody knew until the free tier ran out too. Now it's said once, to the backend's owner and
the admins, and the AI page marks it."""

from __future__ import annotations

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.ai import PermanentError
from themi.core.model_gone import GONE_TEXT

NOT_FOUND = PermanentError("gemini returned 404 NOT_FOUND: models/primary is not found", status=404)


async def test_a_model_not_found_is_said_once_and_marked(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    scenario.app.services.site_url = "https://themi.example"
    scenario.primary.queue_error(NOT_FOUND)
    scenario.fallback.queue_text("Morning!").queue_text("Still here.")
    said = GONE_TEXT.format(
        whose="Your", label="Primary", model=" primary", link="https://themi.example/ai"
    )
    assert await scenario.say("Husband", "good morning") == [said, "Morning!"]
    assert await scenario.say("Husband", "hello again") == ["Still here."]
    told = [t for t in scenario.inbox("Husband") if "isn't there any more" in t]
    assert told == [said]  # once, though it was skipped again
    admin = [t for t in scenario.inbox("Erin") if "isn't there any more" in t]
    assert admin == [said.replace("Your", "Husband's")]
    assert len(scenario.primary.requests) == 1
    await sign_in(scenario, site, "Husband")
    assert "Not found: primary" in (await site.get("/ai")).text
