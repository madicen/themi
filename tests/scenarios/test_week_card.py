"""DC6: the week ahead on request: /week sends a picture of the next seven days, with each
day's weather; without pictures, the week in words."""

from __future__ import annotations

from tests.fakes.gcal_api import FakeGcal
from tests.fakes.weather import FakeWeather
from tests.scenarios.harness import Scenario
from tests.scenarios.test_day_summary import linked
from tests.scenarios.test_morning_message import at, to
from tests.scenarios.test_morning_weather import weather
from tests.scenarios.test_triage import ERIN
from themi.core import keys

__all__ = ["linked", "weather"]


async def a_week(scenario: Scenario, fake: FakeGcal) -> None:
    to(at(9))  # Thursday 22 October
    fake.add_event(ERIN, at(10).isoformat(), at(11).isoformat(), summary="Dentist")
    fake.add_event(
        ERIN, at(18, day=24).isoformat(), at(19, day=24).isoformat(), summary="Book club"
    )
    fake.add_event(
        ERIN, at(9, day=30).isoformat(), at(10, day=30).isoformat(), summary="Next Friday's"
    )  # past the week: not on it
    await scenario.run_periodic("calendar.busy")


async def test_week_sends_a_picture_of_the_week_with_its_weather(
    scenario: Scenario, linked: FakeGcal, weather: FakeWeather
) -> None:
    await a_week(scenario, linked)
    weather.day(2, high=71, low=52, code=61)  # Saturday: rain
    await scenario.run_periodic("weather.refresh")
    replies = await scenario.say("Erin", "/week")
    assert replies == ["Your week ahead."]
    (picture,) = scenario.pictures("Erin")
    assert picture["caption"] == "Your week ahead."
    card = scenario.app.services.get(keys.drawings).week_card
    data = card.data(scenario.member("Erin"))
    assert [d.day.day for d in data.days] == [22, 23, 24, 25, 26, 27, 28]
    assert [e.title for d in data.days for e in d.events] == ["Dentist", "Book club"]
    saturday = data.days[2]
    assert (saturday.high, saturday.low, saturday.icon) == (71, 52, "rain")
    svg = card.svg(scenario.member("Erin"))
    assert "Book club" in svg and "Next Friday" not in svg


async def test_without_the_weather_module_the_week_has_no_forecast(
    scenario: Scenario, linked: FakeGcal
) -> None:
    await a_week(scenario, linked)
    data = scenario.app.services.get(keys.drawings).week_card.data(scenario.member("Erin"))
    assert all(d.high is None and d.icon is None for d in data.days)
    assert await scenario.say("Erin", "/week") == ["Your week ahead."]


async def test_a_week_that_cant_be_drawn_goes_in_words(
    scenario: Scenario, linked: FakeGcal
) -> None:
    def broken(svg: str, width: int | None) -> bytes:
        raise ValueError("no fonts here")

    scenario.app.services.get(keys.drawings).renderer.convert = broken
    await a_week(scenario, linked)
    replies = await scenario.say("Erin", "/week")
    assert replies == ["The week ahead:\n- Thu 22: 10 am Dentist\n- Sat 24: 6 pm Book club"]
    assert scenario.pictures("Erin") == []
