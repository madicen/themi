"""F49f (bug #223): Themi's icons, drawn from the chameleon the pages show (BD3c).

The home-screen icon, the installed app's icons, and the artwork iOS shows for Themi's
music on the lock screen were still the drawing from before BD3c. This writes them from
`chameleon.svg`'s own parts, in the light theme's --cham colours, head and shoulders on a
dark green square:

    .venv/bin/python tools/draw_icons.py

It writes `icons/icon.svg` and, through resvg (as the day card is drawn), `icon-512.png`,
`icon-192.png` and `apple-touch-icon.png` (180). The same chameleon gives the same files.

SW1: it also draws the Safeway helper's toolbar icons (`extension/safeway/icons/`), the same
chameleon on a rounded square with a cart in the corner, so Chrome shows Themi, not a "T".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "themi_home" / "web" / "static"
CHAMELEON = STATIC / "chameleon" / "chameleon.svg"
ICONS = STATIC / "icons"
SIZES = {"icon-512.png": 512, "icon-192.png": 192, "apple-touch-icon.png": 180}
EXTENSION_ICONS = Path(__file__).resolve().parent.parent / "extension" / "safeway" / "icons"
EXTENSION_SIZES = {f"icon-{n}.png": n for n in (16, 32, 48, 128)}

BACKGROUND = "#16302d"  # a deep green, darker than the chameleon's teal
HALO = "#21433f"  # a soft disc behind the head, inside the maskable safe zone
# themi.css's light --cham tokens (BD3c), as plain colours: an icon has no stylesheet
SKIN, BELLY, STRIPE, LINE, EYE = "#3aa79b", "#b4ead6", "#23857a", "#1b4b46", "#ffffff"
STYLE = f"""
.cham-skin {{ fill: {SKIN}; stroke: {LINE}; stroke-width: 1.8; }}
.cham-belly {{ fill: {BELLY}; }}
.cham-stripe {{ fill: none; stroke: {STRIPE}; stroke-width: 4; opacity: .5; }}
.cham-outline {{ fill: none; stroke: {LINE}; stroke-width: 9.6; stroke-linecap: round; }}
.cham-limb {{ fill: none; stroke: {SKIN}; stroke-width: 6; stroke-linecap: round; }}
.cham-tail .cham-outline {{ stroke-width: 11.6; }}
.cham-tail .cham-limb {{ stroke-width: 8; }}
.cham-tail .cham-stripe {{ stroke-width: 8; stroke-dasharray: 3 6; opacity: .55; }}
.cham-mouth, .cham-crease {{ fill: none; stroke: {LINE}; stroke-width: 1.6;
  stroke-linecap: round; }}
.cham-crease {{ opacity: .5; }}
.cham-eyeball {{ fill: {EYE}; stroke: {LINE}; stroke-width: 1.6; }}
.cham-pupil {{ fill: {LINE}; }}
.cham-glint {{ fill: {EYE}; }}
"""
# what the pages show only now and then: the props, the closed lids, the "zz" of a doze
HIDDEN = re.compile(r'\s*<g class="(?:prop [^"]*|cham-zz|cham-lid)">.*?</g>', re.DOTALL)


def parts() -> str:
    """The chameleon's drawing, without its own <svg> wrapper, props or lids."""
    text = CHAMELEON.read_text(encoding="utf-8")
    inner = text[text.index(">", text.index("<svg")) + 1 : text.rindex("</svg>")]
    inner = re.sub(r"\s*<!--.*?-->", "", inner, flags=re.DOTALL)
    return HIDDEN.sub("", inner).strip("\n")


def icon_svg() -> str:
    """The icon: the head and shoulders, cut at the bottom edge like a portrait."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <!-- F49f: drawn by tools/draw_icons.py from chameleon.svg (BD3c); edit that, not this. -->
  <style>{STYLE}</style>
  <rect width="512" height="512" fill="{BACKGROUND}"/>
  <circle cx="256" cy="226" r="196" fill="{HALO}"/>
  <svg x="0" y="0" width="512" height="512" viewBox="-2 -14 124 124" overflow="hidden">
{parts()}
  </svg>
</svg>
"""


BADGE = "#e8613c"  # a warm orange: the cart stands out from the greens
CART = "M3 4h3l2 11h11l2-8H7M10 20h.01M17 20h.01"  # themi.web.icons.SAFEWAY


def extension_svg() -> str:
    """The Safeway helper's icon: the chameleon on a rounded square, a cart badge in the
    bottom right corner."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <!-- SW1: drawn by tools/draw_icons.py from chameleon.svg; edit that, not this. -->
  <style>{STYLE}</style>
  <clipPath id="square"><rect width="512" height="512" rx="112"/></clipPath>
  <g clip-path="url(#square)">
  <rect width="512" height="512" fill="{BACKGROUND}"/>
  <circle cx="230" cy="236" r="190" fill="{HALO}"/>
  <svg x="-30" y="10" width="512" height="512" viewBox="-2 -14 124 124" overflow="hidden">
{parts()}
  </svg>
  </g>
  <circle cx="392" cy="392" r="120" fill="{BADGE}" stroke="{BACKGROUND}" stroke-width="20"/>
  <g transform="translate(392 396) scale(8.4) translate(-12 -12)" fill="none" stroke="#ffffff"
     stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
    <path d="{CART}"/>
  </g>
</svg>
"""


def main() -> int:
    import resvg_py

    for folder, svg, sizes in (
        (ICONS, icon_svg(), SIZES),
        (EXTENSION_ICONS, extension_svg(), EXTENSION_SIZES),
    ):
        folder.mkdir(exist_ok=True)
        (folder / "icon.svg").write_text(svg, encoding="utf-8")
        for name, size in sizes.items():
            png = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=size, skip_system_fonts=True))
            (folder / name).write_bytes(png)
            print(f"wrote {folder.name}/{name} ({size} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
