"""CR10b1: the home pack's settings (OurGroceries, the Cozyla wall, Spotify, Home
Connect, ThinQ).

They were fields of the core `Settings` before; the variable names, defaults and
messages are the same.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from themi.core.connector_settings import _https, _together
from themi.modules.settings import ModuleSettings, env_field
from themi.storage.secrets import Secret
from themi_home.connectors.homeconnect.client import BASE_URL as HOME_CONNECT_URL
from themi_home.connectors.homeconnect.client import HomeConnectConfig
from themi_home.connectors.ourgroceries.client import OurGroceriesConfig
from themi_home.connectors.spotify import ACCOUNTS_URL as SPOTIFY_ACCOUNTS_URL
from themi_home.connectors.spotify import API_URL as SPOTIFY_API_URL
from themi_home.connectors.spotify import SpotifyConfig
from themi_home.connectors.thinq.client import ThinqConfig


class OurGroceriesSettings(ModuleSettings):
    username: str = env_field("OURGROCERIES_USERNAME", "", ask="OurGroceries email")
    password: Secret | None = env_field(
        "OURGROCERIES_PASSWORD", secret=True, ask="OurGroceries password"
    )
    list_name: str = env_field(
        "OURGROCERIES_LIST", "Groceries", ask="The OurGroceries list to keep in step"
    )

    @model_validator(mode="after")
    def _pair(self) -> Self:
        _together("OURGROCERIES_USERNAME", "OURGROCERIES_PASSWORD", self.username, self.password)
        return self

    def config(self) -> OurGroceriesConfig | None:
        """The OurGroceries mirror, if a login is set."""
        if not self.username or self.password is None:
            return None
        return OurGroceriesConfig(self.username, self.password, self.list_name)


class SpotifySettings(ModuleSettings):
    client_id: str = env_field(  # BD5b: a developer app (PKCE)
        "SPOTIFY_CLIENT_ID",
        "",
        ask="Spotify app client id",
        help="developer.spotify.com/dashboard",
    )
    accounts_url: str = SPOTIFY_ACCOUNTS_URL
    api_url: str = SPOTIFY_API_URL

    def config(self) -> SpotifyConfig | None:
        return (
            SpotifyConfig(self.client_id, self.accounts_url, self.api_url)
            if self.client_id
            else None
        )


class HomeConnectSettings(ModuleSettings):
    """H1: the dishwasher, through Home Connect's API (a developer app's id and secret)."""

    client_id: str = env_field("HOME_CONNECT_CLIENT_ID", "", ask="Home Connect client id")
    client_secret: Secret | None = env_field(
        "HOME_CONNECT_CLIENT_SECRET", secret=True, ask="Home Connect client secret"
    )
    url: str = env_field("HOME_CONNECT_URL", HOME_CONNECT_URL)

    @model_validator(mode="after")
    def _checks(self) -> Self:
        _together(
            "HOME_CONNECT_CLIENT_ID",
            "HOME_CONNECT_CLIENT_SECRET",
            self.client_id,
            self.client_secret,
        )
        _https("HOME_CONNECT_URL", self.url)
        return self

    def config(self) -> HomeConnectConfig | None:
        if not self.client_id or self.client_secret is None:
            return None
        return HomeConnectConfig(self.client_id, self.client_secret, self.url.rstrip("/"))


class ThinqSettings(ModuleSettings):
    # 30: LG ThinQ needs no settings (the token is added on the Accounts page); this only
    # points it at a fake instead of LG's regional servers.
    url: str = env_field("THINQ_URL", "")

    @model_validator(mode="after")
    def _checks(self) -> Self:
        _https("THINQ_URL", self.url)
        return self

    def config(self) -> ThinqConfig:
        return ThinqConfig(self.url.rstrip("/"))
