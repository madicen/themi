"""CR11: each module's check tries its settings through its own client: here, the fakes."""

from __future__ import annotations

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fakes.search import FakeSearch
from tests.fakes.travel import FakeTravel
from tests.fakes.wiring import cozyla_client
from themi.standard.web_search import WebSearchModule
from themi_cozyla.cozyla_modules import CozylaTodosModule  # CR21c: the wall's pack
from themi_google.connector_modules import TravelModule
from themi_home.home_modules import OurGroceriesModule


async def test_ourgroceries_is_tried_and_a_failure_said(
    fake_ourgroceries: FakeOurGroceries,
) -> None:
    module = OurGroceriesModule(fake_ourgroceries)
    assert await module.check() is None
    fake_ourgroceries.fail("items")
    problem = await module.check()
    assert problem is not None and problem.startswith("OurGroceries didn't open the list")


async def test_the_wall_is_tried(fake_cozyla: FakeCozyla) -> None:
    module = CozylaTodosModule(cozyla_client(fake_cozyla, "America/Los_Angeles"))
    assert await module.check() is None


async def test_web_search_is_tried_when_there_is_a_key(fake_search: FakeSearch) -> None:
    assert await WebSearchModule(None).check() is None  # no key: nothing to try
    module = WebSearchModule(fake_search.client())
    assert await module.check() is None
    fake_search.fail("search", 401)
    problem = await module.check()
    assert problem is not None and problem.startswith("The web search didn't answer")


async def test_the_map_service_is_tried(fake_travel: FakeTravel) -> None:
    fake_travel.place("Pike Place Market, Seattle", 47.6, -122.3)
    module = TravelModule(fake_travel.client())
    assert await module.check() is None
    fake_travel.fail("geocode", 500, times=5)
    problem = await module.check()
    assert problem is not None
