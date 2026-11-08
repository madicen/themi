"""CR21c: the Cozyla wall is its own pack. The family runs with it and without it."""

from __future__ import annotations

from tests.fakes.cozyla import FakeCozyla
from tests.fakes.telegram_api import FakeTelegram
from tests.fakes.wiring import connector_options
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi.app import build_app, family_modules
from themi.channels.telegram import TelegramChannel
from themi.config import available_modules, load_template
from themi.storage.secrets import Secret

WALL_MODULES = {"cozyla_todos", "cozyla_chores"}


def test_the_wall_modules_come_from_its_own_pack() -> None:
    known = available_modules()
    assert {known[n].__module__ for n in WALL_MODULES} == {"themi_cozyla.cozyla_modules"}
    assert set(load_template("family").modules) >= WALL_MODULES


def test_the_family_with_and_without_the_wall(
    family: SeededFamily, fake_telegram: FakeTelegram, fake_cozyla: FakeCozyla
) -> None:
    without = Scenario(family, fake_telegram)
    names = {m.name for m in without.app.modules}
    assert not names & WALL_MODULES and "chore_chart" in names
    assert without.app.services.mirrors.mirrors == {}
    with_wall = build_app(  # the same family, the wall's modules on
        family.db,
        family.store.cipher,
        lambda store: TelegramChannel.from_token(Secret("1:x"), store, None),
        modules=family_modules(**connector_options(cozyla=fake_cozyla)),
    )
    assert {m.name for m in with_wall.modules} >= WALL_MODULES
    assert set(with_wall.services.mirrors.mirrors) == {"cozyla"}
