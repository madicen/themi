"""Write the drawings' fallback font for fractions (F54): `ThemiFractions-{Regular,Bold}.ttf`.

Atkinson Hyperlegible has ¼ ½ ¾ but none of Number Forms (⅓ ⅔ ⅛ ⅜ ⅝ ⅞ …) nor the thin
space, and resvg is given only the bundled fonts, so a ⅓ drew as an empty box. This takes
just those characters from Noto Sans (OFL), at the regular and bold weights, scales them so
a ⅓ stands as tall as Atkinson's ½, and names the result "Themi Fractions". resvg falls
back to it per character; templates never name it.

Run at dev time only (the app never downloads): give it Noto Sans' variable font, or let
it fetch it from the google/fonts repository.

Usage: python -m tools.dev.fraction_font [path/to/NotoSans[wdth,wght].ttf]
       (needs fontTools: pip install -e '.[dev]'), then python -m tools.dev.font_widths
"""

from __future__ import annotations

import sys
import tempfile
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ASSETS = Path(__file__).resolve().parents[2] / "src" / "themi" / "drawing" / "assets"
FONTS = ASSETS / "fonts"
SOURCE_URL = "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf"
FAMILY = "Themi Fractions"
# Number Forms' fractions, and the thin space.
CHARS = [*range(0x2150, 0x215F), 0x2009]
WEIGHTS = {  # the file's style -> (Noto's weight, the Atkinson file it sits beside)
    "Regular": (400, "AtkinsonHyperlegible-Regular.ttf"),
    "Bold": (700, "AtkinsonHyperlegible-Bold.ttf"),
}
HALF = ord("½")  # what a ⅓ is measured against


def _height(font: TTFont, point: int) -> int:
    glyph = font["glyf"][font.getBestCmap()[point]]  # type: ignore[index]
    glyph.recalcBounds(font["glyf"])  # type: ignore[arg-type]
    return int(glyph.yMax - glyph.yMin)


def _scale(font: TTFont, factor: float) -> None:
    """Every glyph and advance times `factor` (the em stays the same)."""
    glyf, hmtx = font["glyf"], font["hmtx"]
    glyphs = font.getGlyphSet()
    for name in font.getGlyphOrder():
        pen = TTGlyphPen(glyphs)  # type: ignore[arg-type]
        glyphs[name].draw(TransformPen(pen, (factor, 0, 0, factor, 0, 0)))
        glyf[name] = pen.glyph()  # type: ignore[index]
        advance, _ = hmtx[name]  # type: ignore[index]
        glyf[name].recalcBounds(glyf)  # type: ignore[index]
        hmtx[name] = (round(advance * factor), getattr(glyf[name], "xMin", 0))  # type: ignore[index]


def _rename(font: TTFont, style: str, weight: int) -> None:
    names = font["name"]
    names.names = []  # type: ignore[attr-defined]
    for ident, value in (
        (0, "Copyright 2022 The Noto Project Authors (subset and scaled for Themi)"),
        (1, FAMILY),
        (2, style),
        (3, f"{FAMILY.replace(' ', '')}-{style}"),
        (4, f"{FAMILY} {style}"),
        (5, "Version 1.000"),
        (6, f"{FAMILY.replace(' ', '')}-{style}"),
        (13, "This Font Software is licensed under the SIL Open Font License, Version 1.1."),
        (14, "https://openfontlicense.org"),
    ):
        names.setName(value, ident, 3, 1, 0x409)  # type: ignore[attr-defined]
    font["OS/2"].usWeightClass = weight  # type: ignore[attr-defined]
    font["OS/2"].fsSelection = 0x20 if style == "Bold" else 0x40  # type: ignore[attr-defined]
    font["head"].macStyle = 1 if style == "Bold" else 0  # type: ignore[attr-defined]


def make(source: Path, style: str, weight: int, beside: str) -> Path:
    font = instancer.instantiateVariableFont(TTFont(source), {"wght": weight, "wdth": 100})
    factor = _height(TTFont(FONTS / beside), HALF) / _height(font, HALF)
    options = subset.Options()
    options.layout_features = []
    options.hinting = False
    options.name_IDs = ["*"]  # type: ignore[list-item]
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=CHARS)
    sub.subset(font)
    _scale(font, factor)
    _rename(font, style, weight)
    out = FONTS / f"ThemiFractions-{style}.ttf"
    font.save(out)
    print(f"Wrote {out} (Noto Sans {weight}, scaled {factor:.3f})")
    return out


def main() -> None:
    if len(sys.argv) > 1:
        source = Path(sys.argv[1])
    else:
        source = Path(tempfile.mkdtemp()) / "NotoSans.ttf"
        urllib.request.urlretrieve(SOURCE_URL, source)
    for style, (weight, beside) in WEIGHTS.items():
        make(source, style, weight, beside)


if __name__ == "__main__":
    main()
