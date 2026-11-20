"""F51a (#235): no website route is taken by an earlier route with a parameter in its path.

Google's `POST /accounts/{account_id}/unlink` (an int) was included before Spotify's
`POST /accounts/spotify/unlink`, so the Unlink Spotify button got a 422 ("spotify" isn't a
number). Integer path parameters now say so in the path (`{account_id:int}`), so a word can't
match them, whatever order the modules' pages are included in."""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest
from starlette.convertors import IntegerConvertor
from starlette.routing import Route

from tests.scenarios.harness import Scenario
from tests.scenarios.test_golden import CONNECTORS
from themi import clock
from themi.web import HealthSources, create_app
from themi.web.kit import SiteContext


def routes_in_order(scenario: Scenario) -> list[Route]:
    web = create_app(
        HealthSources(scenario.app.db, None, clock.now()),
        SiteContext(scenario.app, base_url="http://themi.test", secure_cookies=False),
    )
    out: list[Route] = []

    def walk(routes: list[Any]) -> None:
        for route in routes:
            included = getattr(route, "original_router", None)
            if included is not None:  # FastAPI 0.16x keeps an included router whole
                walk(list(included.routes))
            elif isinstance(route, Route):
                out.append(route)

    walk(list(web.routes))
    return out


@pytest.mark.usefixtures(*CONNECTORS)
async def test_integer_path_parameters_say_so_in_the_path(scenario: Scenario) -> None:
    loose = []
    for route in routes_in_order(scenario):
        params = inspect.signature(route.endpoint).parameters
        for name, convertor in route.param_convertors.items():
            typed = name in params and params[name].annotation in (int, "int")
            if typed and not isinstance(convertor, IntegerConvertor):
                loose.append(f"{route.path}: write {{{name}:int}}")
    assert not loose, loose


@pytest.mark.usefixtures(*CONNECTORS)
async def test_no_fixed_path_is_taken_by_an_earlier_route(scenario: Scenario) -> None:
    routes = routes_in_order(scenario)
    shadowed = []
    for i, fixed in enumerate(routes):
        if fixed.param_convertors:
            continue
        for earlier in routes[:i]:
            same = (fixed.methods or set()) & (earlier.methods or set())
            if same and earlier.param_convertors and re.match(earlier.path_regex, fixed.path):
                shadowed.append(
                    f"{sorted(same)} {fixed.path} is taken by {earlier.path}: type its "
                    "parameter (e.g. {id:int}) or include the fixed route first"
                )
    assert not shadowed, shadowed
