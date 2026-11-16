"""BD4c: the chameleon sent with each step picture, drawn from the session page's SVG."""

from __future__ import annotations

import struct

import pytest

from themi_home import step_images
from themi_home.step_images import chameleon_reference, reference_svg


def size(png: bytes) -> tuple[int, int]:
    width, height = struct.unpack(">II", png[16:24])  # the IHDR chunk
    return width, height


def test_the_chameleon_is_a_png_under_cloudflares_512px() -> None:
    chameleon_reference.cache_clear()
    reference = chameleon_reference()
    assert reference is not None
    assert reference.data.startswith(b"\x89PNG") and reference.mime_type == "image/png"
    width, height = size(reference.data)
    assert 256 <= width < 512 and 128 <= height < 512


def test_drawn_in_the_light_colours_on_white_with_the_props_hidden() -> None:
    svg = reference_svg()
    assert "#3d6f6a" in svg and 'fill="#ffffff"' in svg  # the light theme's accent, on white
    assert ".prop, .cham-zz { display: none; }" in svg
    assert "var(--" not in svg  # resvg has no site stylesheet to resolve tokens from


def test_without_a_drawing_the_pictures_go_without_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(svg: str, width: int | None = None) -> bytes:
        raise RuntimeError("no resvg")

    monkeypatch.setattr("themi.drawing.render.to_png", broken)
    chameleon_reference.cache_clear()
    try:
        assert chameleon_reference() is None
    finally:
        chameleon_reference.cache_clear()
    assert step_images.CHAMELEON.exists()
