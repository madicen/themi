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
            # WA2: the alerts
            ("getting ready's label", "--alert-ready", "--card"),
            ("getting ready's button", "--on-alert", "--alert-ready"),
            ("the last minutes' words", "--on-go", "--alert-go"),
            ("the last minutes' button", "--alert-go-ink", "--on-go"),
            ("running behind's words", "--alert-behind", "--alert-behind-bg"),
            ("running behind's line", "--fg", "--alert-behind-bg"),
            ("running behind's button", "--alert-behind-bg", "--alert-behind"),
            ("the kitchen's label", "--alert-kitchen", "--card"),
            ("the kitchen's button", "--on-kitchen", "--alert-kitchen"),
            ("the kitchen's next line", "--fg", "--alert-kitchen-bg"),
            ("a timer that's up", "--on-kitchen", "--alert-kitchen"),
            ("a timer that's up, its next line", "--fg", "--alert-kitchen-tint"),
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
            # WL9b: a dish's number on its row, folded and unfolded
            (f"{p}'s dish number", t[f"--{p}"], t["--soft"]),
            (f"{p}'s open dish number", t[f"--{p}"], t[f"--{p}-bg"]),
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


# ----- F58c (bug #249): one screen tall, nothing past the frame's bottom ---------------------


def rule(selector: str) -> str:
    return " ".join(b for s, b in blocks() if s == selector)


def test_the_wall_and_its_night_screen_are_exactly_one_screen_tall() -> None:
    for selector in (".wall-screen", ".wall-night"):
        body = rule(selector)
        assert "height: 100dvh" in body and "overflow: hidden" in body, selector
        assert "min-height: 100vh" not in body, selector
    assert "min-height: 100vh" not in CSS
    assert "flex: 1 1 0" in rule(".wall-screen > .wall-columns")
    assert "min-height: 0" in rule(".wall-screen > .wall-columns")
    assert "overflow: hidden" in rule(".wall-col-body")


def test_the_wall_fits_its_columns_whenever_they_change() -> None:
    assert "themiWallFit.fitWall" in SCRIPT
    for when in ('"htmx:afterSwap"', '"resize"', '"DOMContentLoaded"'):
        assert when in SCRIPT


def test_a_months_event_is_filled_with_its_tone() -> None:
    """F64a (bug #273): `.cal-ev` is painted with the event's tone, as the week ahead's are."""
    [body] = [b for s, b in blocks() if s == ".cal-ev"]
    assert "background: var(--tone)" in body and "color: var(--on-tone)" in body


def test_the_alerts_tick_from_the_servers_now() -> None:
    """WA2: the countdowns tick from the part's data-now, never the frame's own clock."""
    assert 'list.getAttribute("data-now")' in SCRIPT
    assert "var at = Date.now() + alertSkew;" in SCRIPT
    assert 'body.alerting .wall-screen > :not(.wall-top)' in CSS
