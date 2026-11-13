"""CR1: golden files for what the core refactor must not change by accident.

The family app is built with every connector's fake, as the scenario harness builds it,
and four things are compared with the files in `tests/golden/`:

- `tools.json`: each tool's group, and a short hash of its spec (name, description, schema)
- `jobs.json`: each periodic job's interval in seconds
- `routes.json`: each website route, method and path
- `handlers.json`: the command menu in order, button prefixes, and each list of hooks in
  the order they run
- `system_prompt.txt`: the family's system prompt with no rules or facts yet

`make golden` writes them again (THEMI_WRITE_GOLDEN=1). A refactor prompt changes one only
where its own text says what changes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.scenarios.harness import Scenario
from themi import clock
from themi.app import App
from themi.web import HealthSources, create_app
from themi.web.kit import SiteContext

CONNECTORS = (
    "fake_google",
    "fake_gmail",
    "fake_gcal",
    "fake_gtasks",
    "fake_gdocs",
    "fake_ourgroceries",
    "fake_cozyla",
    "fake_travel",
    "fake_weather",  # WX1
    "fake_search",
    "fake_home_connect",
    "fake_spotify",
    "fake_thinq",
    "fake_roborock",
    "fake_tuya",
    "fake_catgenie",
    "fake_keep",
    "fake_runner",
)
GOLDEN = Path(__file__).resolve().parents[1] / "golden"
WRITE = os.environ.get("THEMI_WRITE_GOLDEN") == "1"


def tools_of(app: App) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for spec in app.services.tools.specs():
        body = json.dumps(
            {"name": spec.name, "description": spec.description, "schema": spec.input_schema},
            sort_keys=True,
        )
        out[spec.name] = {
            "group": app.services.tools.group_of(spec.name),  # CR8b: as the modules registered
            "spec": hashlib.sha256(body.encode()).hexdigest()[:12],
        }
    return out


def jobs_of(app: App) -> dict[str, int]:
    names = [p.name for p in app.periodic]
    assert len(names) == len(set(names)), f"two periodic jobs share a name: {sorted(names)}"
    return {
        p.name: int(p.every.total_seconds()) for p in sorted(app.periodic, key=lambda p: p.name)
    }


def routes_of(scenario: Scenario) -> list[str]:
    web = create_app(
        HealthSources(scenario.app.db, None, clock.now()),
        SiteContext(scenario.app, base_url="http://themi.test", secure_cookies=False),
    )
    out: set[str] = set()

    def walk(routes: list[Any], prefix: str) -> None:
        for route in routes:
            included = getattr(route, "original_router", None)
            if included is not None:  # FastAPI 0.16x keeps an included router whole
                walk(list(included.routes), prefix + route.include_context.prefix)
                continue
            path = prefix + getattr(route, "path", "")
            inner = getattr(route, "routes", None)
            if inner:  # a mounted app or router: its routes, under its path
                walk(list(inner), path)
                continue
            for method in sorted(getattr(route, "methods", None) or {"*"}):
                out.add(f"{method} {path}")

    walk(list(web.routes), "")
    return sorted(out)


def _named(hooks: list[Any]) -> list[str]:
    """Hooks in the order they run, by name: their order changes what people see."""
    return [getattr(h, "__qualname__", type(h).__qualname__) for h in hooks]


def handlers_of(app: App) -> dict[str, Any]:
    s = app.services
    return {
        "command_menu": [name for name, _ in s.command_menu()],  # Telegram's menu, in order
        "commands": sorted(s.commands),
        "event_commands": sorted(s.event_commands),
        "buttons": sorted(s.button_handlers),
        "reaction_handlers": _named(s.reaction_handlers),
        "text_handlers": _named(s.text_handlers),
        "awaiting_sources": _named(s.awaiting_sources),
        "open_item_sources": _named(s.open_item_sources),
        "executors": s.autonomy.executors.names(),
    }


def check(name: str, value: Any) -> None:
    path = GOLDEN / name
    text = value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True) + "\n"
    if WRITE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(text)
        return
    assert path.exists(), f"{path} is missing: run `make golden`"
    assert text == path.read_text(), (
        f"{name} changed. If the prompt says it should, run `make golden` and say why in the "
        "commit; otherwise something was dropped or renamed."
    )


@pytest.mark.usefixtures(*CONNECTORS)
async def test_the_family_app_matches_its_golden_files(scenario: Scenario) -> None:
    app = scenario.app
    check("tools.json", tools_of(app))
    check("jobs.json", jobs_of(app))
    check("handlers.json", handlers_of(app))
    check("routes.json", routes_of(scenario))
    check("system_prompt.txt", app.services.system_text())  # CR8a: composed from parts


@pytest.mark.usefixtures(*CONNECTORS)
async def test_every_key_finds_its_object_in_the_full_family_app(scenario: Scenario) -> None:
    from themi.core import keys
    from themi.modules.registry import Key

    services = scenario.app.services
    missing = [
        name
        for name, key in vars(keys).items()
        if isinstance(key, Key) and services.maybe(key) is None
    ]
    assert missing == [], f"keys with nothing behind them in the full family app: {missing}"
