"""Every file the app reads at run time is in the installed package (bug 2026-11-07: the
session page failed on the Pi because `web/static/*` left out `chameleon/` and `audio/`;
tests run from the source tree, so nothing else noticed)."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGE = ROOT / "src" / "themi"


def test_every_web_and_schema_file_is_package_data() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["themi"]
    covered = {p for pattern in patterns for p in PACKAGE.glob(pattern) if p.is_file()}
    needed = {
        p
        for folder in ("web/static", "web/templates", "storage/schema")
        for p in (PACKAGE / folder).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert sorted(str(p.relative_to(PACKAGE)) for p in needed - covered) == []
