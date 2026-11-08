"""Every file the app reads at run time is in the installed package (bug 2026-11-07: the
session page failed on the Pi because `web/static/*` left out `chameleon/` and `audio/`;
tests run from the source tree, so nothing else noticed). CR17b: each pack's too."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("package", ["themi", "themi_google", "themi_home"])
def test_every_web_and_schema_file_is_package_data(package: str) -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"][package]
    folder_of = ROOT / "src" / package
    covered = {p for pattern in patterns for p in folder_of.glob(pattern) if p.is_file()}
    needed = {
        p
        for folder in ("web/static", "web/templates", "storage/schema")
        for p in (folder_of / folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert sorted(str(p.relative_to(folder_of)) for p in needed - covered) == []


def test_no_pack_template_hides_another() -> None:
    """The site's loader takes the first template of a name, the core's first: a pack's of
    the same name would never be seen."""
    seen: dict[str, str] = {}
    for package in ("themi", "themi_google", "themi_home"):
        folder = ROOT / "src" / package / "web" / "templates"
        for path in folder.rglob("*.html"):
            name = str(path.relative_to(folder))
            assert name not in seen, f"{name} is in {seen.get(name)} and {package}"
            seen[name] = package
