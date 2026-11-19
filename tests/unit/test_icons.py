"""F49f (bug #223): Themi's icons are drawn from the chameleon the pages show (BD3c), by
tools/draw_icons.py, so iOS's lock screen and home screen show Themi as it looks now."""

from __future__ import annotations

import hashlib
import struct

import pytest

from tools.draw_icons import ICONS, SIZES, icon_svg, parts

# the icons drawn before BD3c (the pale chameleon on green), no longer used
OLD = {
    "379f436d896dc76821854f348ba7b4d895d29e741fe7fd011eb545d535410d30",
    "9a55967c90937e6fde9fb908a2301a3c736ff83c3491ee86c50358f5f3d45394",
    "51292de43c53395f85f959ec6af49c1e3c57785bb46e6bf0fdd28a4dad7bdd4e",
}


def test_the_committed_icon_is_the_scripts() -> None:
    assert (ICONS / "icon.svg").read_text(encoding="utf-8") == icon_svg()


def test_the_icon_is_the_chameleon_without_its_props() -> None:
    drawn = parts()
    assert 'class="cham-head"' in drawn and 'class="cham-body"' in drawn
    assert "prop" not in drawn and "cham-zz" not in drawn and "cham-lid" not in drawn


@pytest.mark.parametrize(("name", "size"), list(SIZES.items()))
def test_each_png_is_new_and_its_size(name: str, size: int) -> None:
    data = (ICONS / name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (size, size)
    assert hashlib.sha256(data).hexdigest() not in OLD
