"""CR5b: each connector module's settings, read from today's environment variables.

They were fields of the core `Settings` before; the variable names, defaults and
messages are the same.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from themi.connectors.cozyla.client import CozylaConfig
from themi.connectors.google.oauth import GoogleConfig
from themi.connectors.homeconnect.client import BASE_URL as HOME_CONNECT_URL
from themi.connectors.homeconnect.client import HomeConnectConfig
from themi.connectors.ourgroceries.client import OurGroceriesConfig
from themi.connectors.spotify import ACCOUNTS_URL as SPOTIFY_ACCOUNTS_URL
from themi.connectors.spotify import API_URL as SPOTIFY_API_URL
from themi.connectors.spotify import SpotifyConfig
from themi.connectors.thinq.client import ThinqConfig
from themi.modules.settings import ModuleSettings, env_field
from themi.storage.secrets import Secret


def _https(name: str, url: str) -> None:
    if url and not url.startswith(("https://", "http://127.0.0.1")):
        raise ValueError(f"{name} must be an https:// address, not {url}")


def _together(first: str, second: str, a: object, b: object) -> None:
    if bool(a) != bool(b):
        raise ValueError(f"{first} and {second} go together; set both or neither")


class GoogleSettings(ModuleSettings):
    """Google sign-in and linking (the google module; gmail, calendar, Google Tasks and the
    cookbook build on it)."""

    client_id: str = env_field(
        "GOOGLE_CLIENT_ID",
        "",
        ask="Google OAuth client id",
        help="console.cloud.google.com, APIs & Services, Credentials (a Web application)",
    )
    client_secret: Secret | None = env_field(
        "GOOGLE_CLIENT_SECRET", secret=True, ask="Google OAuth client secret"
    )
    # Endpoint overrides, only for pointing Themi at a local fake Google.
    auth_url: str = env_field("GOOGLE_AUTH_URL", "")
    token_url: str = env_field("GOOGLE_TOKEN_URL", "")
    revoke_url: str = env_field("GOOGLE_REVOKE_URL", "")
    userinfo_url: str = env_field("GOOGLE_USERINFO_URL", "")
    gmail_url: str = env_field("GOOGLE_GMAIL_URL", "")
    calendar_url: str = env_field("GOOGLE_CALENDAR_URL", "")
    tasks_url: str = env_field("GOOGLE_TASKS_URL", "")
    docs_url: str = env_field("GOOGLE_DOCS_URL", "")
    drive_url: str = env_field("GOOGLE_DRIVE_URL", "")
    # RC1a: not endpoints, but strings for the same config: Google's file picker.
    picker_api_key: str = env_field("GOOGLE_PICKER_API_KEY", "")
    project_number: str = env_field("GOOGLE_PROJECT_NUMBER", "")

    @model_validator(mode="after")
    def _pair(self) -> Self:
        _together("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", self.client_id, self.client_secret)
        return self

    def config(self) -> GoogleConfig | None:
        """Google sign-in and linking, if a client id and secret are set."""
        if not self.client_id or self.client_secret is None:
            return None
        overrides = {
            name: value
            for name in (
                "auth_url",
                "token_url",
                "revoke_url",
                "userinfo_url",
                "gmail_url",
                "calendar_url",
                "tasks_url",
                "docs_url",
                "drive_url",
                "picker_api_key",
                "project_number",
            )
            if (value := getattr(self, name))
        }
        return GoogleConfig(self.client_id, self.client_secret, **overrides)


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


class CozylaSettings(ModuleSettings):
    """The Cozyla wall (unofficial API), for both wall modules."""

    email: str = env_field("COZYLA_EMAIL", "", ask="Cozyla account email")
    password: Secret | None = env_field("COZYLA_PASSWORD", secret=True, ask="Cozyla password")
    todo_list: str = env_field(
        "COZYLA_TODO_LIST", "", ask="The wall's to-do list to keep in step (blank: none)"
    )
    device_sn: str = env_field("COZYLA_DEVICE_SN", "themi")
    chores: bool = env_field(
        "COZYLA_CHORES", False, ask="Keep the wall's chore chart in step? (yes or no)"
    )

    @model_validator(mode="after")
    def _pair(self) -> Self:
        _together("COZYLA_EMAIL", "COZYLA_PASSWORD", self.email, self.password)
        return self

    def config(self) -> CozylaConfig | None:
        if not self.email or self.password is None:
            return None
        return CozylaConfig(
            self.email, self.password, self.todo_list, self.device_sn, chores=self.chores
        )


class TravelSettings(ModuleSettings):
    # K4: TomTom's routing with live traffic; without it, a free geocoder and an estimate.
    tomtom_api_key: Secret | None = env_field(
        "TOMTOM_API_KEY",
        secret=True,
        ask="TomTom API key, for live traffic (blank: estimates)",
        help="developer.tomtom.com, free plan",
    )


class SearchSettings(ModuleSettings):
    # F30d: web search for lookups. Tavily by default, or Firecrawl; free plans, no card.
    tavily_api_key: Secret | None = env_field(
        "TAVILY_API_KEY",
        secret=True,
        ask="Tavily API key, for web search (blank: none)",
        help="tavily.com, free plan",
    )
    firecrawl_api_key: Secret | None = env_field("FIRECRAWL_API_KEY", secret=True)
    backend: str = env_field("THEMI_SEARCH_BACKEND", "")  # "tavily", "firecrawl", or ""


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
