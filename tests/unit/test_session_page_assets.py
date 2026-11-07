"""BD3b: the session page's art: every animation flag has a CSS state, the character is
drawn as named parts, and the built-in pictures carry no styles of their own (the CSP)."""

from __future__ import annotations

import re
from pathlib import Path

from themi.core.body_double_scene import FLAGS

STATIC = Path(__file__).parents[2] / "src" / "themi" / "web" / "static"
CSS = (STATIC / "themi.css").read_text()
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
    reduced = CSS.split("@media (prefers-reduced-motion: reduce)")[-1]
    assert ".session-scene *" in reduced and "animation: none" in reduced
