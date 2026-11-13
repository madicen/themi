"""DC8: /weather sends today and tomorrow as a picture; without the weather module, it says
how to turn it on."""

from __future__ import annotations

from tests.fakes.weather import FakeWeather
from tests.scenarios.harness import Scenario
from tests.scenarios.test_morning_message import at, to
from tests.scenarios.test_morning_weather import rain, weather
from themi.core import keys
from themi.standard.weather_card import CAPTION, OFF_TEXT

__all__ = ["weather"]


async def test_weather_sends_today_and_tomorrow(scenario: Scenario, weather: FakeWeather) -> None:
    to(at(9))
    rain(weather)
    weather.day(1, high=64, low=50)
    await scenario.run_periodic("weather.refresh")
    assert await scenario.say("Erin", "/weather") == [CAPTION]
    assert len(scenario.pictures("Erin")) == 1
    data = scenario.app.services.get(keys.drawings).weather_card.data()
    assert data is not None
    today, tomorrow = data.days
    assert today.line == "Rain likely from about 2 pm, high 58°F."
    assert (tomorrow.name, tomorrow.high, tomorrow.low) == ("Tomorrow", 64, 50)


async def test_without_the_weather_module_it_says_how_to_turn_it_on(scenario: Scenario) -> None:
    assert await scenario.say("Erin", "/weather") == [OFF_TEXT]
    assert scenario.pictures("Erin") == []


async def test_without_pictures_the_weather_goes_in_words(
    scenario: Scenario, weather: FakeWeather
) -> None:
    def broken(svg: str, width: int | None) -> bytes:
        raise ValueError("no fonts here")

    scenario.app.services.get(keys.drawings).renderer.convert = broken
    to(at(9))
    rain(weather)
    await scenario.run_periodic("weather.refresh")
    (reply,) = await scenario.say("Erin", "/weather")
    assert reply.startswith("Today: 58° / 47°. Rain likely from about 2 pm")
