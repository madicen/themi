"""BD3b: the session page's art: every animation flag has a CSS state, the character is
drawn as named parts, and the built-in pictures carry no styles of their own (the CSP)."""

from __future__ import annotations

import re
from pathlib import Path

from themi_home.body_double_scene import FLAGS

SRC = Path(__file__).parents[2] / "src"
STATIC = SRC / "themi_home" / "web" / "static"  # CR17b: the home pack's
CSS = (SRC / "themi" / "web" / "static" / "themi.css").read_text()
CHAMELEON = (STATIC / "chameleon" / "chameleon.svg").read_text()
SCENES = (STATIC / "chameleon" / "scenes.svg").read_text()


def test_every_flag_has_a_css_state() -> None:
    for flag in FLAGS:
        assert f'.session-scene[data-state="{flag}"]' in CSS, flag


def test_the_chameleon_is_drawn_as_named_parts() -> None:
    for part in ("cham-body", "cham-eye", "cham-tail", "cham-hand", "cham-head"):
        assert f'class="{part}' in CHAMELEON or f"{part} " in CHAMELEON, part
    for prop in ("book", "mug", "broom", "easel", "pencil", "blanket"):
        assert f'class="prop prop-{prop}"' in CHAMELEON, prop


def test_a_scene_for_each_mode() -> None:
    for mode in ("silent", "sprint", "guided"):
        assert f'class="scene scene-{mode}"' in SCENES
        assert f'.session-scene[data-mode="{mode}"] .scene-{mode}' in CSS


def test_no_inline_styles_or_scripts_in_the_art() -> None:
    for svg in (CHAMELEON, SCENES):
        assert not re.search(r"\sstyle=|<style|<script|\son\w+=", svg)


def test_still_scenes_for_reduced_motion() -> None:
    blocks = CSS.split("@media (prefers-reduced-motion: reduce)")[1:]
    assert any(".session-scene *" in b.split("}\n")[0] + b for b in blocks)
    scene = next(b for b in blocks if b.lstrip(" {\n").startswith(".session-scene *"))
    assert "animation: none" in scene.split("\n}")[0]


# ----- BD5a: the built-in loops --------------------------------------------------------------

AUDIO = STATIC / "audio"


def test_every_loop_exists_small_and_licensed() -> None:
    from themi_home.body_double_music import LOOPS

    licences = (AUDIO / "LICENCES.md").read_text()
    for track in (t for loop in LOOPS.values() for t in loop.tracks):
        path = AUDIO / track.file
        assert path.is_file(), track.file
        assert 10_000 < path.stat().st_size < 5_000_000, track.file
        line = next((x for x in licences.splitlines() if x.startswith(f"| {track.file} ")), "")
        assert "CC0" in line, track.file


def test_each_kind_of_sound_has_more_than_one_track() -> None:
    """CK14: Next on the cook screen plays another track of the same kind, so there's one."""
    from themi_home.body_double_music import LOOPS

    for loop in LOOPS.values():
        files = [t.file for t in loop.tracks]
        assert len(files) >= 2 and len(set(files)) == len(files), loop.key
        assert loop.file == files[0]  # the one it always played is still the first


def test_the_loops_are_named_in_chat_words() -> None:
    from themi_home.body_double_music import loop_for

    assert loop_for("rain").key == "rain"  # type: ignore[union-attr]
    assert loop_for("the soft piano").key == "soft_piano"  # type: ignore[union-attr]
    assert loop_for("Lo-Fi").key == "lofi"  # type: ignore[union-attr]
    assert loop_for("death metal") is None


def test_the_page_never_reads_a_forms_action_property() -> None:
    """Bug (2026-11-07, the Pi's log from an iPhone): each tap's form has a hidden input named
    "action", and a named input shadows `form.action`, so the page posted every tap to
    "[object HTMLInputElement]". The script reads and sets the attribute instead."""
    script = (STATIC / "session.js").read_text()
    template = (STATIC.parent / "templates" / "session.html").read_text()
    assert 'name="action"' in template  # the input that shadows the property
    assert not re.search(r"\bform\.action\b", script)
    assert 'getAttribute("action")' in script


# ----- BD3c: the chameleon redrawn as the chosen Themi -------------------------------------

CHAM_TOKENS = ("--cham", "--cham-belly", "--cham-stripe", "--cham-line", "--cham-eye")


def test_every_chameleon_class_the_css_moves_is_drawn() -> None:
    """The redraw keeps every named part: each `cham-*` class the stylesheet styles or
    animates is in the SVG, so no state quietly stops working."""
    styled = set(re.findall(r"\.(cham-[a-z-]+)", CSS))
    drawn = set(re.findall(r'class="[^"]*?\b(cham-[a-z-]+)', CHAMELEON))
    drawn |= {c for cls in re.findall(r'class="([^"]+)"', CHAMELEON) for c in cls.split()}
    assert styled <= drawn, styled - drawn


def test_the_chameleon_has_its_own_colours_in_both_themes() -> None:
    """BD3c: Themi is teal with a mint belly (BD4d's look) whatever the site's accent is,
    with its colours as tokens set for light and for dark."""
    light = CSS.split("@media (prefers-color-scheme: dark)")[0]
    dark = CSS.split("@media (prefers-color-scheme: dark)")[1].split("\n}\n")[0]
    for token in CHAM_TOKENS:
        assert f"{token}:" in light, token
        assert f"{token}:" in dark, token
    rules = CSS[CSS.index(".cham {") : CSS.index(".prop, .cham-zz")]
    assert "var(--accent)" not in rules
    assert "var(--cham)" in rules


def test_the_cook_pages_dark_theme_dresses_the_chameleon_dark() -> None:
    cook = (STATIC / "cook.css").read_text()
    dark = cook.split('body.cook-page[data-theme="dark"] {')[-1].split("}")[0]  # the last wins
    for token in CHAM_TOKENS:
        assert f"{token}:" in dark, token
