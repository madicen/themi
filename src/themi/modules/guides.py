"""SP3a: a module's setup guide: `setup/<name>.md` beside the module's code, shipped as
package data. Themi's own words, so the Modules page renders it as trusted text (with the
site's small Markdown renderer, which still allows no raw HTML)."""

from __future__ import annotations

from importlib import resources

from themi.modules.base import Module


def guide_package(cls: type[Module]) -> str:
    """The package whose `setup` folder holds the module's guide: the one its class is in
    (`themi.standard`, `themi_home`)."""
    return cls.__module__.rpartition(".")[0] or cls.__module__


def guide(cls: type[Module]) -> str | None:
    """The module's guide, or None when it has none."""
    try:
        found = resources.files(guide_package(cls)).joinpath("setup", f"{cls.name}.md")
        return found.read_text() if found.is_file() else None
    except (ModuleNotFoundError, FileNotFoundError, NotADirectoryError):
        return None
