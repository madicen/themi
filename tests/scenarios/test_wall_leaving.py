"""WA2's scenario: Erin's dentist trip on the wall, from getting ready to We're off.

Wednesday 21 October 2026, Los Angeles. The dentist is at 3 pm, 35 minutes away: Telegram's
heads-up and the wall's card both come at 2:10, and the card counts to 2:25.
"""

from __future__ import annotations

import re

from tests.fakes.gcal_api import FakeGcal
from tests.fixtures.cookbook import load
from tests.fixtures.web import web_client
from tests.integration.test_wall_alerts import at, leaving, local, share
from tests.integration.test_wall_screen import frame, words
from tests.scenarios.harness import Scenario
from tests.scenarios.test_triage import ERIN
from tests.unit.test_cook_tablet import alfredo, to_steps
from themi.core import keys

__all__ = ["leaving"]  # the fixture


async def test_a_dentist_trip_on_the_wall(leaving: Scenario, fake_gcal: FakeGcal) -> None:
    share(leaving)
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    async with web_client(leaving) as wall:
        await frame(leaving, wall)
        await at(leaving, 14, 10)
        await leaving.app.outbox.flush()
        assert any(t.startswith("Dentist at 3 pm") for t in leaving.inbox("Erin"))
        page = (await wall.get("/wall")).text
        card = words(page[page.index('<section class="wall-alert ') :])
        assert card.startswith("Time to get ready Dentist at 3:00 15:00 until we leave at 2:25")
        assert "Erin · 35 min drive with traffic" in card

        await at(leaving, 14, 21)
        card = words((await wall.get("/wall/part/alerts")).text)
        assert card.startswith("Almost time to go Dentist at 3:00 4:00 out the door at 2:25")

        await at(leaving, 14, 25)
        part = (await wall.get("/wall/part/alerts")).text
        assert "Time to go" in part
        key = re.search(r'data-alert="([^"]+)"', part)
        csrf = re.search(r'"X-CSRF-Token": "([^"]+)"', page)
        assert key and csrf
        gone = await wall.post(
            "/wall/alert", data={"key": key.group(1), "answer": "off"},
            headers={"X-CSRF-Token": csrf.group(1)},
        )  # fmt: skip
        assert "wall-alert" not in gone.text
        await at(leaving, 14, 30)
        assert "wall-alert" not in (await wall.get("/wall/part/alerts")).text


async def test_a_timer_goes_off_while_getting_ready(leaving: Scenario, fake_gcal: FakeGcal) -> None:
    """WA3: leaving stays on top with the kitchen as a band under it, until a timer is up."""
    share(leaving)
    load(leaving.app.services)
    fake_gcal.add_event(ERIN, local(15), local(16), summary="Dentist", location="Smile Dental")
    await at(leaving, 14, 5)
    cooking = leaving.app.services.maybe(keys.cooking)
    assert cooking is not None and cooking.timers is not None
    session = cooking.get(await to_steps(leaving, cooking, {"jobs": []}))
    assert session is not None
    cooking.timers.start(leaving.member("Erin"), session, alfredo(cooking), "1", 10)
    async with web_client(leaving) as wall:
        await frame(leaving, wall)
        await at(leaving, 14, 10)
        part = (await wall.get("/wall/part/alerts")).text
        assert re.findall(r'class="wall-alert ([^"]+)"', part) == [
            "alert-leave alert-ready", "alert-kitchen alert-running alert-second",
        ]  # fmt: skip
        await at(leaving, 14, 15)
        await leaving.run_jobs()
        part = (await wall.get("/wall/part/alerts")).text
        assert re.findall(r'class="wall-alert ([^"]+)"', part) == [
            "alert-kitchen alert-up", "alert-leave alert-ready alert-second",
        ]  # fmt: skip
        assert "Kitchen time" in words(part)
