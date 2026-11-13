"""DC1: the drawings' renderer: words fitted to their space, SVG that only ever holds words
from data, and the same PNG every time."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

import pytest

from themi.drawing.render import Renderer, to_png
from themi.drawing.svg import icon, n, write_svg, xml_safe
from themi.drawing.text import ELLIPSIS, fit, text_width, wrap
from themi.standard.drawings import DrawingsModule

CARD = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60" viewBox="0 0 200 60">'
    '<rect width="200" height="60" fill="#ffffff"/>'
    '<text x="10" y="30" font-family="{{ font }}" font-size="14">{{ title }}</text>'
    '<image href="{{ icon("rain") }}" x="160" y="10" width="32" height="32"/>'
    "</svg>"
)


@pytest.fixture
def templates(tmp_path: Path) -> Path:
    (tmp_path / "card.svg").write_text(CARD)
    return tmp_path


def size_of(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


# ----- words ----------------------------------------------------------------------------


def test_widths_come_from_the_font() -> None:
    assert text_width("", 14) == 0
    assert text_width("iiii", 14) < text_width("MMMM", 14)
    assert text_width("Dentist", 14, bold=True) > text_width("Dentist", 14)
    assert text_width("Dentist", 28) == pytest.approx(2 * text_width("Dentist", 14))
    assert text_width("☃", 14) > 0  # a character the table doesn't have: about a letter


def test_words_that_fit_are_kept_whole() -> None:
    assert fit("Dentist", 14, 200) == "Dentist"
    assert fit("  Dentist \n at  noon ", 14, 200) == "Dentist at noon"


def test_long_words_are_cut_at_a_word_with_an_ellipsis() -> None:
    title = "Parent-teacher conference with Ms Alvarez about the spring term"
    cut = fit(title, 14, 150)
    assert cut.endswith(ELLIPSIS)
    assert text_width(cut, 14) <= 150
    assert title.startswith(cut.removesuffix(ELLIPSIS))
    assert not cut.removesuffix(ELLIPSIS).endswith(" ")


def test_nothing_fits_in_no_room() -> None:
    assert fit("Dentist", 14, 3) == ""


def test_wrapping_breaks_at_words_and_cuts_the_last_line() -> None:
    lines = wrap("Two cups of flour, sifted, then the butter cut in small pieces", 14, 120, 2)
    assert len(lines) == 2
    assert all(text_width(line, 14) <= 120 for line in lines)
    assert lines[-1].endswith(ELLIPSIS)
    assert wrap("Short", 14, 120, 3) == ["Short"]
    assert wrap("", 14, 120, 3) == []


# ----- SVG ------------------------------------------------------------------------------


def test_numbers_print_the_same_everywhere() -> None:
    assert n(12.0) == "12"
    assert n(12.345) == "12.35"
    assert n(-0.001) == "0"
    assert n(0.5) == "0.5"


def test_words_from_data_stay_words(templates: Path) -> None:
    title = '<script>alert(1)</script><image href="file:///etc/passwd"/> Tom & Jerry \U0001f382'
    svg = write_svg("card.svg", [templates], title=title)
    assert "<script>" not in svg
    assert '<image href="file:' not in svg
    assert "&lt;script&gt;" in svg
    assert "Tom &amp; Jerry" in svg
    assert svg.count("<image ") == 1  # the icon alone


def test_characters_xml_cant_hold_are_taken_out(templates: Path) -> None:
    assert xml_safe("Bill\x00 due\x1b￾") == "Bill due"
    svg = write_svg("card.svg", [templates], title="Bill\x0b due")
    assert "Bill due" in svg


def test_an_icon_is_a_data_uri_and_only_by_name() -> None:
    assert icon("rain").startswith("data:image/svg+xml;base64,")
    with pytest.raises(ValueError):
        icon("../fonts/OFL")


def test_a_missing_value_is_an_error_not_a_blank(templates: Path) -> None:
    with pytest.raises(Exception, match="title"):
        write_svg("card.svg", [templates])


# ----- PNG ------------------------------------------------------------------------------


async def test_the_same_svg_gives_the_same_png(templates: Path) -> None:
    svg = write_svg("card.svg", [templates], title="Dentist at 3 · 58°")
    first = await Renderer().png(svg)
    second = await Renderer().png(svg)
    assert first is not None
    assert first == second
    assert size_of(first) == (200, 60)


async def test_a_width_scales_the_picture(templates: Path) -> None:
    png = await Renderer().png(write_svg("card.svg", [templates], title="x"), 400)
    assert png is not None
    assert size_of(png) == (400, 120)


async def test_a_broken_svg_gives_none_and_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    renderer = Renderer()
    assert await renderer.png("<svg") is None
    assert await renderer.png("not svg at all") is None
    assert len([r for r in caplog.records if "couldn't be made" in r.message]) == 1


async def test_a_slow_renderer_gives_none() -> None:
    def slow(svg: str, width: int | None) -> bytes:
        import threading

        threading.Event().wait(0.5)  # in the worker thread; the test's clock isn't involved
        return b"late"

    assert await Renderer(slow, timeout=0.05).png("<svg/>") is None


async def test_an_empty_picture_gives_none() -> None:
    assert await Renderer(lambda svg, width: b"").png("<svg/>") is None


def test_the_bundled_fonts_are_the_only_fonts() -> None:
    """A system font (DejaVu, on most Linux machines) draws nothing; sans-serif is ours."""
    page = '<rect width="80" height="20" fill="white"/>'
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="20">{page}'
        '<text x="0" y="15" font-family="FAMILY">Aa</text></svg>'
    )
    blank = to_png(f'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="20">{page}</svg>')
    ours = to_png(svg.replace("FAMILY", "Atkinson Hyperlegible"))
    assert ours != blank
    assert to_png(svg.replace("FAMILY", "sans-serif")) == ours
    assert to_png(svg.replace("FAMILY", "DejaVu Sans")) == blank


async def test_the_modules_test_draws_a_picture() -> None:
    assert await DrawingsModule().check() is None


def test_rendering_runs_off_the_event_loop() -> None:
    seen: list[bool] = []

    def convert(svg: str, width: int | None) -> bytes:
        try:
            asyncio.get_running_loop()
            seen.append(True)
        except RuntimeError:
            seen.append(False)
        return b"png"

    assert asyncio.run(Renderer(convert).png("<svg/>")) == b"png"
    assert seen == [False]
