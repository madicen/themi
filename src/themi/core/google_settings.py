"""CR10b1: the Google pack's settings (Google sign-in, the map service for travel).

They were fields of the core `Settings` before; the variable names, defaults and
messages are the same.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from themi.connectors.google.oauth import GoogleConfig
from themi.core.connector_settings import _https, _together  # noqa: F401
from themi.modules.settings import ModuleSettings, env_field
from themi.storage.secrets import Secret


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


class TravelSettings(ModuleSettings):
    # K4: TomTom's routing with live traffic; without it, a free geocoder and an estimate.
    tomtom_api_key: Secret | None = env_field(
        "TOMTOM_API_KEY",
        secret=True,
        ask="TomTom API key, for live traffic (blank: estimates)",
        help="developer.tomtom.com, free plan",
    )
