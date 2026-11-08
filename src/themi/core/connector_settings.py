"""CR5b: each connector module's settings, read from today's environment variables.
CR10b1: the core's (web search) and the shared checks; the Google pack's are in
`google_settings.py`, the home pack's in `home_settings.py`.

They were fields of the core `Settings` before; the variable names, defaults and
messages are the same.
"""

from __future__ import annotations

from themi.modules.settings import ModuleSettings, env_field
from themi.storage.secrets import Secret


def _https(name: str, url: str) -> None:
    if url and not url.startswith(("https://", "http://127.0.0.1")):
        raise ValueError(f"{name} must be an https:// address, not {url}")


def _together(first: str, second: str, a: object, b: object) -> None:
    if bool(a) != bool(b):
        raise ValueError(f"{first} and {second} go together; set both or neither")


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
