"""F52b: the wall's dark look. Every colour in wall.css is a token; every light token has a
dark one; and the pairs the wall draws keep their contrast (text 4.5:1, rings 3:1)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from themi_home.wall_columns import TONES
from themi_home.wall_view import THEME_COLOR

CSS = (Path(__file__).parents[2] / "src/themi_home/web/static/wall.css").read_text()
SCRIPT = (Path(__file__).parents[2] / "src/themi_home/web/static/wall.js").read_text()
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
PEOPLE = tuple(TONES)  # F53: every colour Wall frames offers


def blocks() -> list[tuple[str, str]]:
    """Each rule as (selector, body), comments dropped."""
    text = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return [(m[1].strip(), m[2]) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", text)]


def tokens(selector: str, holding: str = "--bg") -> dict[str, str]:
    """The custom properties of the one `selector` rule that sets `holding`."""
    [body] = [b for s, b in blocks() if s == selector and holding in b]
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))


LIGHT = tokens(":root")
DARK = tokens("html.dark, body.night")


def test_no_rule_names_a_colour_outside_the_token_blocks() -> None:
    named = [
        s for s, b in blocks() if COLOUR.search(b) and not s.startswith((":root", "html.dark"))
    ]
    assert named == []


def test_every_light_token_has_a_dark_one() -> None:
    assert set(LIGHT) == set(DARK)
    assert DARK["--bg"] == THEME_COLOR["dark"] and LIGHT["--bg"] == THEME_COLOR["light"]
    assert (
        f'dark: "{THEME_COLOR["dark"]}"' in SCRIPT and f'light: "{THEME_COLOR["light"]}"' in SCRIPT
    )


def lum(colour: str) -> float:
    r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    high, low = sorted((lum(a), lum(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def text_pairs(t: dict[str, str]) -> list[tuple[str, str, str]]:
    pairs = [
        (what, t[fg], t[bg])
        for what, fg, bg in [
            ("text on a card", "--fg", "--card"),
            ("text on the screen", "--fg", "--bg"),
            ("muted on a card", "--muted", "--card"),
            ("muted on the screen", "--muted", "--bg"),
            ("muted on soft", "--muted", "--soft"),
            ("a neutral view's Back button", "--on-fg", "--fg"),
            ("sub on a card", "--sub", "--card"),
            ("sub on soft", "--sub", "--soft"),
            ("faint on a card", "--faint", "--card"),
            ("quiet on a card", "--quiet", "--card"),
            ("on a dark button", "--on-fg", "--fg"),
            ("the now line's time", "--on-now", "--now"),
            ("the stale line", "--stale", "--stale-bg"),
        ]
    ]
    for p in PEOPLE:
        pairs += [
            (f"{p}'s name on its header", t[f"--{p}"], t[f"--{p}-tint"]),
            (f"{p}'s summary on its header", t["--quiet"], t[f"--{p}-tint"]),
            (f"{p}'s name on a card", t[f"--{p}"], t["--card"]),
            (f"{p}'s blocks", t["--on-tone"], t[f"--{p}"]),
            (f"{p}'s items", t["--fg"], t[f"--{p}-bg"]),
            # WL9a: a view's kicker and foot line on its card, and its filled Back button
            (f"{p}'s view kicker", t[f"--{p}"], t["--card"]),
            (f"{p}'s Back button", t["--on-tone"], t[f"--{p}"]),
        ]
    return pairs


@pytest.mark.parametrize("look", ["light", "dark"])
def test_text_keeps_its_contrast(look: str) -> None:
    t = LIGHT if look == "light" else DARK
    weak = [(w, round(contrast(a, b), 2)) for w, a, b in text_pairs(t) if contrast(a, b) < 4.5]
    assert weak == []


def test_dark_rings_keep_three_to_one() -> None:
    """The light look's rings (about 2:1) are left as the family knows them (F52b Notes)."""
    weak = [
        p
        for p in PEOPLE
        if contrast(DARK[f"--{p}-ring"], DARK[f"--{p}-bg"]) < 3
        or contrast(DARK[f"--{p}-ring"], DARK["--ring-fill"]) < 3
    ]
    assert weak == []


def test_the_people_keep_their_hues() -> None:
    def hue(colour: str) -> float:
        import colorsys

        r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return colorsys.rgb_to_hls(r, g, b)[0] * 360

    for p in PEOPLE:
        apart = abs(hue(LIGHT[f"--{p}"]) - hue(DARK[f"--{p}"])) % 360
        assert min(apart, 360 - apart) < 25, p


def test_the_night_keeps_its_own_colours() -> None:
    assert tokens(":root", "--night-bg")["--night-bg"] == "#14161b"
    assert "body.night:not(.awake) { background: var(--night-bg); }" in CSS


def test_every_colour_on_offer_has_a_tone_rule() -> None:
    """F53: a colour chosen on Wall frames draws something."""
    for tone in TONES:
        assert f".tone-{tone} {{ --tone: var(--{tone});" in CSS, tone
