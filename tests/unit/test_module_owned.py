"""MP4: what each module added to the website, for its own page on the Modules page."""

from __future__ import annotations

from fastapi import APIRouter

from tests.fakes.modules import bare_services
from tests.fixtures.family import SeededFamily
from themi.modules import Module, ModuleContext
from themi.modules.web import MenuEntry


class Shelf(Module):
    name = "shelf"

    def install(self, ctx: ModuleContext) -> None:
        ctx.settings_section("shelf_settings.html", 50, values=lambda m: {"x": 1})
        ctx.accounts_section("shelf_accounts.html", 30, household=True)
        ctx.web(
            lambda kit: APIRouter(),
            MenuEntry("/shelf", "Shelf", "What's on it", "Household", 5),
        )


class Broken(Module):
    name = "broken"

    def install(self, ctx: ModuleContext) -> None:
        ctx.settings_section("broken.html", 60)
        raise RuntimeError("no")


def test_each_registration_carries_its_module(family: SeededFamily) -> None:
    services = bare_services(family.store)
    ModuleContext(services).load(Shelf())
    owned = services.owned_by("shelf")
    assert [s.template for s in owned.settings] == ["shelf_settings.html"]
    assert owned.settings[0].values is not None and owned.settings[0].order == 50
    assert [a.template for a in owned.accounts] == ["shelf_accounts.html"]
    assert owned.accounts[0].household
    assert [m.href for m in owned.menu] == ["/shelf"]


def test_a_module_thats_off_owns_nothing(family: SeededFamily) -> None:
    services = bare_services(family.store)
    ModuleContext(services).load(Shelf())
    owned = services.owned_by("lamp")
    assert owned.settings == owned.accounts == owned.menu == ()


def test_a_failed_install_leaves_nothing_owned(family: SeededFamily) -> None:
    services = bare_services(family.store)
    ctx = ModuleContext(services)
    ctx.load(Shelf(), Broken(), tolerant=True)
    assert "broken" in ctx.failed
    assert services.owned_by("broken").settings == ()
    assert services.owned_by("shelf").settings  # the one that started keeps its own
