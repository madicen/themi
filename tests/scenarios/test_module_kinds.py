"""CR19: module kinds; AI providers and capabilities as modules; setup asks by kind."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi.ai.adapters import AdapterConfig
from themi.ai.errors import PermanentError
from themi.ai.router import module_factory
from themi.app import family_modules
from themi.config import available_modules, parse_config, resolve_modules
from themi.core.agent import PICTURES_OFF_TEXT, VOICE_OFF_TEXT
from themi.modules import KINDS
from themi.settings import Settings, SettingsError
from themi.setup_wizard import run_setup
from themi.storage.secrets import Secret, generate_key

PICTURE_TOOLS = {"send_step_picture", "redo_step_picture"}


def test_every_module_has_a_kind() -> None:
    known = available_modules()
    assert {cls.kind for cls in known.values()} <= set(KINDS)
    of = {kind: {n for n, cls in known.items() if cls.kind == kind} for kind in KINDS}
    assert of["ai"] == {"claude", "gemini", "openai_compatible", "cloudflare"}
    assert of["capability"] == {"voice_notes", "pictures", "image_generation"}
    assert {"google", "gmail", "calendar", "spotify", "thinq", "cozyla_todos"} <= of["connector"]
    assert {"tasks", "reminders", "noise_digest"} <= of["feature"]


def without(
    family: SeededFamily, telegram: FakeTelegram, *left_out: str, **fakes: object
) -> Scenario:
    """The family's app with some modules left out, and what needs them."""
    modules = family_modules(**connector_options(**fakes))  # type: ignore[arg-type]
    gone = set(left_out)
    while needing := [m for m in modules if m.name not in gone and gone & set(m.requires)]:
        gone |= {m.name for m in needing}
    return Scenario(family, telegram, modules=[m for m in modules if m.name not in gone], **fakes)  # type: ignore[arg-type]


def test_the_family_offers_the_picture_tools(scenario: Scenario) -> None:
    tools = {spec.name for spec in scenario.app.services.tools.specs()}
    assert tools >= PICTURE_TOOLS and "recipe_from_picture" in tools


def test_without_image_generation_no_picture_tools_or_step_pictures(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    scenario = without(family, fake_telegram, "image_generation")
    tools = {spec.name for spec in scenario.app.services.tools.specs()}
    assert not tools & PICTURE_TOOLS
    assert "step_pictures" not in {m.name for m in scenario.app.modules}
    assert "body_double" in {m.name for m in scenario.app.modules}  # the rest stays


def test_the_work_template_offers_no_picture_tools(tmp_path: Path) -> None:
    (tmp_path / "themi.toml").write_text('template = "work"\n')
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": generate_key()})
    names = {m.name for m in resolve_modules(parse_config({"template": "work"}), settings)}
    assert "image_generation" not in names and "step_pictures" not in names


async def test_without_voice_notes_or_pictures_themi_says_so(
    family: SeededFamily, fake_telegram: FakeTelegram
) -> None:
    scenario = without(family, fake_telegram, "voice_notes", "pictures")
    tools = {spec.name for spec in scenario.app.services.tools.specs()}
    assert "recipe_from_picture" not in tools
    await scenario.start()
    try:
        assert await scenario.voice("Erin") == [VOICE_OFF_TEXT]
        assert await scenario.picture("Erin") == [PICTURES_OFF_TEXT]
    finally:
        await scenario.stop()


def test_a_themi_needs_an_ai_provider() -> None:
    settings = Settings.from_mapping({"THEMI_SECRET_KEY": generate_key()})
    config = parse_config({"template": "empty", "modules": ["-gemini", "+tasks"]})
    with pytest.raises(SettingsError, match="at least one AI provider"):
        resolve_modules(config, settings)
    assert {m.name for m in resolve_modules(parse_config({"template": "empty"}), settings)} == {
        "gemini"
    }


def test_only_the_loaded_providers_build_backends() -> None:
    factory = module_factory({})
    with pytest.raises(PermanentError, match="isn't one of this Themi's AI providers"):
        factory(AdapterConfig("anthropic", api_key=Secret("k")))


def test_setup_asks_by_kind_in_order(tmp_path: Path) -> None:
    asked: list[str] = []
    told: list[str] = []

    def ask(question: str, default: str | None = None) -> str:
        asked.append(question)
        return "family" if "Which template" in question else ""

    def skip(coro):
        coro.close()

    run_setup(ask, lambda _q: "", told.append, tmp_path, run=skip)
    steps = [q for q in asked if q.startswith(("Leave", "Which other", "Add any"))]
    assert [s.split(" (")[0] for s in steps] == [
        "Leave out any AI providers",
        "Which other AI providers",
        "Leave out any capabilities",
        "Which other capabilities",
        "Leave any out",
        "Add any",
    ]  # no channel modules yet: Telegram is the core's (CR20b makes it one)
    headings = [t.split(".")[0] for t in told if " template has: " in t]
    assert headings == [
        "AI providers",
        "What Themi can do with voice notes and pictures, and make",
        "Services and features",
    ]


def test_leaving_out_every_ai_provider_keeps_gemini(tmp_path: Path) -> None:
    told: list[str] = []

    def ask(question: str, default: str | None = None) -> str:
        if "Which template" in question:
            return "empty"
        return "gemini" if "Leave out any AI providers" in question else ""

    def skip(coro):
        coro.close()

    run_setup(ask, lambda _q: "", told.append, tmp_path, run=skip)
    assert "A Themi needs at least one AI provider, so it keeps gemini." in told
    assert "gemini" not in (tmp_path / "themi.toml").read_text()  # the template's, kept
