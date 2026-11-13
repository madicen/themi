"""The fakes as `build_app`'s connectors, one way for the scenario harness and `make dev` (D5a).

    build_app(db, cipher, make_channel, **connector_options(gmail=fake_gmail, ...))

Pass the fakes a run has; each one given is wired in as the real connector would be, and
the rest are left out (None), as when a connector isn't set up.
"""

from __future__ import annotations

from typing import Any

from tests.fakes.catgenie import FakeCatGenie
from tests.fakes.cozyla import EMAIL as COZYLA_EMAIL
from tests.fakes.cozyla import PASSWORD as COZYLA_PASSWORD
from tests.fakes.cozyla import FakeCozyla
from tests.fakes.gcal_api import FakeGcal
from tests.fakes.gdocs_api import FakeGdocs
from tests.fakes.gmail_api import FakeGmail
from tests.fakes.google_oauth import FakeGoogle
from tests.fakes.gsheets_api import FakeGsheets
from tests.fakes.gtasks_api import FakeGtasks
from tests.fakes.home_connect import FakeHomeConnect
from tests.fakes.keep import FakeKeep
from tests.fakes.ourgroceries import FakeOurGroceries
from tests.fakes.roborock import FakeRoborock
from tests.fakes.search import FakeSearch
from tests.fakes.spotify import FakeSpotify
from tests.fakes.thinq import FakeThinq
from tests.fakes.travel import FakeTravel
from tests.fakes.tuya import FakeTuya
from tests.fakes.weather import FakeWeather
from themi.storage.secrets import Secret
from themi_cozyla.connector import CozylaClient, CozylaConfig
from themi_google.connectors.google import GoogleConfig

WALL_LIST = "Family"  # the Cozyla to-do list Themi syncs
WALL_MEMBERS = ("Erin", "Husband")


def connector_options(
    *,
    google: FakeGoogle | None = None,
    gmail: FakeGmail | None = None,
    gcal: FakeGcal | None = None,
    gtasks: FakeGtasks | None = None,
    gdocs: FakeGdocs | None = None,
    gsheets: FakeGsheets | None = None,
    ourgroceries: FakeOurGroceries | None = None,
    cozyla: FakeCozyla | None = None,
    travel: FakeTravel | None = None,
    search: FakeSearch | None = None,
    home_connect: FakeHomeConnect | None = None,
    spotify: FakeSpotify | None = None,
    thinq: FakeThinq | None = None,
    roborock: FakeRoborock | None = None,
    tuya: FakeTuya | None = None,
    catgenie: FakeCatGenie | None = None,
    keep: FakeKeep | None = None,
    weather: FakeWeather | None = None,
    timezone: str = "America/Los_Angeles",
) -> dict[str, Any]:
    return {
        "google": google_config(google, gmail, gcal, gtasks, gdocs, gsheets),
        "grocery_list": ourgroceries,
        "cozyla": cozyla_client(cozyla, timezone) if cozyla else None,
        "travel": travel.client() if travel else None,
        "search": search.client() if search else None,
        "home_connect": home_connect.client() if home_connect else None,
        "spotify": spotify.client() if spotify else None,  # BD5b
        "thinq": thinq.config() if thinq else None,
        "roborock": roborock,
        "tuya": tuya.config() if tuya else None,
        "catgenie": catgenie.config() if catgenie else None,
        "keep": keep.connect if keep else None,
        "weather": weather.client() if weather else None,  # WX1
    }


def google_config(
    google: FakeGoogle | None,
    gmail: FakeGmail | None,
    gcal: FakeGcal | None,
    gtasks: FakeGtasks | None = None,
    gdocs: FakeGdocs | None = None,
    gsheets: FakeGsheets | None = None,
) -> GoogleConfig | None:
    config = gmail.config() if gmail else google.config() if google else None
    config = gcal.config(config) if gcal else config
    config = gtasks.config(config) if gtasks else config
    config = gdocs.config(config) if gdocs else config
    return gsheets.config(config) if gsheets else config


def wall_list(fake: FakeCozyla) -> int:
    """The fake's "Family" list, made if it isn't there yet."""
    for list_id, todo_list in fake.lists.items():
        if todo_list["todoListTitle"] == WALL_LIST:
            return list_id
    return fake.add_list(WALL_LIST)


def cozyla_client(fake: FakeCozyla, timezone: str) -> CozylaClient:
    """A client for the fake wall, which gets the family's members if it hasn't them yet."""
    config = CozylaConfig(COZYLA_EMAIL, Secret(COZYLA_PASSWORD), todo_list=WALL_LIST, chores=True)
    for name in WALL_MEMBERS:
        if not any(m["memberName"] == name for m in fake.members):
            fake.add_member(name)
    return CozylaClient(
        config, timezone=timezone, password_key=fake.public_key, transport=fake.transport
    )
