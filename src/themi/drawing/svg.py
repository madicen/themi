"""Drawings as SVG, from Jinja2 templates (DC1).

    svg = write_svg("day_card.svg", card=card)

Templates are autoescaped, and every value they print is cleaned of characters XML 1.0
can't hold (a stray control character in an email subject would otherwise make the whole
picture fail to parse). Numbers print through `n`, so the SVG is the same text on every
machine. `icon("rain")` is a bundled icon as a data URI, for `<image href=…>`: nested as an
image, each icon keeps its own ids, so two on one card don't clash.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from themi.drawing import ASSETS, FONT_FAMILY, TEMPLATES
from themi.drawing.text import fit, text_width, wrap

# What XML 1.0 allows in text: tab, newline, return, and everything from space up, less the
# surrogates and the two non-characters at the end of the first plane.
NOT_XML = re.compile("[^\t\n\r -퟿-�\U00010000-\U0010ffff]")


def xml_safe(value: Any) -> Any:
    """What a template prints, with characters XML can't hold taken out."""
    return NOT_XML.sub("", value) if isinstance(value, str) else value


def n(value: float) -> str:
    """A number for an SVG attribute: at most two decimals, no trailing zeros."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


@cache
def icon(name: str) -> str:
    """A bundled icon (`assets/icons/<name>.svg`) as a data URI. Only names from Themi's
    own code: a name with a path in it is refused."""
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise ValueError(f"not an icon name: {name!r}")
    data = (ASSETS / "icons" / f"{name}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")


@cache
def environment(extra: tuple[Path, ...] = ()) -> Environment:
    env = Environment(
        loader=FileSystemLoader([TEMPLATES, *extra]),
        autoescape=select_autoescape(["svg", "xml"], default=True),
        undefined=StrictUndefined,
        finalize=xml_safe,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["n"] = n
    env.globals.update(icon=icon, fit=fit, wrap=wrap, text_width=text_width, font=FONT_FAMILY)
    return env


def write_svg(template: str, extra: Sequence[Path] = (), **values: Any) -> str:
    """The template filled in. `extra`: a pack's own template folders, after Themi's."""
    return environment(tuple(extra)).get_template(template).render(**values)
