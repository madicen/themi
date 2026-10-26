"""The private "how Themi sees my week" page (S3): words only, your own week only, and
gentle corrections."""

import re
from datetime import time

import httpx

from tests.fixtures.web import sign_in
from tests.scenarios.harness import Scenario
from themi.accounts import SYSTEM, BusyTime
from themi.energy.week import WEEK_WORDS


async def test_my_week_in_words(scenario: Scenario, site: httpx.AsyncClient) -> None:
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/week")).text
    assert "How Themi sees your week" in page
    assert "Wednesday 21 Oct" in page and "Tuesday 27 Oct" in page  # seven days from today
    for part in ("Morning", "Afternoon", "Evening"):
        assert part in page
    assert any(words in page for _, words in WEEK_WORDS)
    assert "Good moments Themi would pick in the next day" in page
    assert not re.search(r"\d+\s*(%|points|/\s*100)", page)  # never a score


async def test_busy_and_quiet_parts_say_so(scenario: Scenario, site: httpx.AsyncClient) -> None:
    scenario.app.store.update_settings(
        SYSTEM, scenario.member("Erin").id,
        busy_times=[BusyTime((0, 1, 2, 3, 4), time(8), time(17))],
    )  # fmt: skip
    await sign_in(scenario, site, "Erin")
    page = (await site.get("/week")).text
    assert "busy (your busy times)" in page


async def test_what_it_learned_from_is_your_own(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    energy = scenario.app.services.energy
    energy.record(scenario.member("Erin"), "text_note", -2, "wiped")
    energy.record(scenario.member("Erin"), "day_level", 0, "medium day")
    await sign_in(scenario, site, "Erin")
    assert "2 things you mentioned about your energy" in (await site.get("/week")).text

    async with httpx.AsyncClient(transport=site._transport, base_url=str(site.base_url)) as other:
        await sign_in(scenario, other, "Husband")
        his = (await other.get(f"/week?member_id={scenario.member('Erin').id}")).text
    assert "things you mentioned about your energy" not in his  # his own, and nothing yet
    assert "still learning" in his


async def test_a_gentle_correction(scenario: Scenario, site: httpx.AsyncClient) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    erin = scenario.member("Erin")
    energy = scenario.app.services.energy
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tuesday_evening = datetime(2026, 10, 27, 19, tzinfo=ZoneInfo("America/Los_Angeles"))
    before = energy.baseline(erin, tuesday_evening)  # type: ignore[attr-defined]
    response = await site.post(
        "/week/correct", data={"csrf": csrf, "weekday": "1", "part": "evening", "way": "better"}
    )
    assert response.status_code == 303
    after = energy.baseline(erin, tuesday_evening)  # type: ignore[attr-defined]
    assert after > before and after - before < 15  # gentle
    flash_page = (await site.get("/week")).text
    assert "Tuesday evenings will lean a bit better from now on" in flash_page

    bad = await site.post(
        "/week/correct", data={"csrf": csrf, "weekday": "9", "part": "midnight", "way": "up"}
    )
    assert bad.status_code == 303  # ignored, with a message


async def test_parts_still_on_the_starting_guess_say_so(
    scenario: Scenario, site: httpx.AsyncClient
) -> None:
    csrf = await sign_in(scenario, site, "Erin")
    page = (await site.get("/week")).text
    assert "(a first guess)" in page
    await site.post(
        "/week/correct", data={"csrf": csrf, "weekday": "1", "part": "evening", "way": "better"}
    )
    page = (await site.get("/week")).text
    tuesday = page[page.index("Tuesday 27 Oct") :]  # the last day shown
    evening = tuesday[tuesday.index("Evening") :]
    assert "(a first guess)" not in evening[: evening.index("</span>")]
