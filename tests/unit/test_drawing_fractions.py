"""F54: fractions Atkinson lacks (⅓ ⅔ ⅛ …) draw from the bundled "Themi Fractions", in the
text's own weight, and are measured from it (bug #238: a drawn ⅓ was an empty box)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from themi.drawing import ASSETS, FALLBACK_CHARS, FALLBACK_FAMILY, FONT_FAMILY
from themi.drawing.render import FONT_FILES, to_png, with_fallback
from themi.drawing.text import _table, text_width
from themi_home.quantities import FRACTIONS
from tools.dev.font_widths import EXTRA

FONTS = ASSETS / "fonts"
WEIGHTS = {
    "regular": ("AtkinsonHyperlegible-Regular.ttf", "ThemiFractions-Regular.ttf"),
    "bold": ("AtkinsonHyperlegible-Bold.ttf", "ThemiFractions-Bold.ttf"),
}
# In the width table but in no bundled font (nor Noto Sans): no drawing writes it yet (F54).
NO_GLYPH = {"→"}
TOFU = "ก"  # ก: Thai, in none of the bundled fonts, so drawn as an empty box


def cmap(name: str) -> set[int]:
    return set((TTFont(FONTS / name).getBestCmap() or {}).keys())


def one_line(text: str, family: str = FONT_FAMILY, weight: str = "normal") -> bytes:
    return to_png(
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40">'
        '<rect width="80" height="40" fill="white"/>'
        f'<text x="10" y="30" font-family="{family}" font-weight="{weight}" font-size="28">'
        f"{text}</text></svg>"
    )


@pytest.mark.parametrize("weight", WEIGHTS)
def test_every_fraction_a_recipe_writes_has_a_glyph_in_each_weight(weight: str) -> None:
    atkinson, fallback = (cmap(name) for name in WEIGHTS[weight])
    for ch in {*FRACTIONS, *EXTRA, *FALLBACK_CHARS} - NO_GLYPH:
        assert ord(ch) in atkinson | fallback, f"{ch!r} has no {weight} glyph"
    for ch in FALLBACK_CHARS:
        assert ord(ch) not in atkinson and ord(ch) in fallback  # the fallback is only the gap


def test_the_fallback_fonts_are_bundled_and_named() -> None:
    names = {Path(f).name for f in FONT_FILES}
    assert {"ThemiFractions-Regular.ttf", "ThemiFractions-Bold.ttf"} <= names
    for _, file in WEIGHTS.values():
        assert TTFont(FONTS / file)["name"].getDebugName(1) == FALLBACK_FAMILY
    assert (FONTS / "OFL-noto-sans.txt").exists()


@pytest.mark.parametrize(("weight", "bold"), [("regular", False), ("bold", True)])
def test_a_fraction_is_measured_from_the_fallback(weight: str, bold: bool) -> None:
    font = TTFont(FONTS / WEIGHTS[weight][1])
    advance = font["hmtx"][(font.getBestCmap() or {})[ord("⅓")]][0]
    units = font["head"].unitsPerEm  # type: ignore[attr-defined]
    assert text_width("⅓", 20, bold=bold) == pytest.approx(advance / units * 20)
    table = _table()[weight]
    assert text_width("⅓", 20, bold=bold) != table["fallback"] / table["units"] * 20


def test_only_the_words_get_the_fallback_named() -> None:
    svg = '<svg><text aria-label="⅓">⅓ Cup <tspan font-weight="700">⅔</tspan></text></svg>'
    span = f'<tspan font-family="{FALLBACK_FAMILY}">'
    assert with_fallback(svg) == (
        f'<svg><text aria-label="⅓">{span}⅓</tspan> Cup '
        f'<tspan font-weight="700">{span}⅔</tspan></tspan></text></svg>'
    )
    plain = '<svg><text x="1">½ Cup</text></svg>'
    assert with_fallback(plain) is plain


def test_a_third_draws_a_glyph_not_an_empty_box() -> None:
    assert one_line("⅓") != one_line(TOFU)
    assert one_line("⅓", weight="bold") != one_line(TOFU, weight="bold")


@pytest.mark.parametrize("weight", ["normal", "bold"])
def test_a_third_keeps_the_texts_weight(weight: str) -> None:
    """resvg's own fallback drew the bold ⅓ in regular text; named, it matches."""
    assert one_line("⅓", weight=weight) == one_line("⅓", FALLBACK_FAMILY, weight)
    assert one_line("⅓", weight="normal") != one_line("⅓", weight="bold")
