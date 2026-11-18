"""BD4d: the chameleon sent with each step picture is Michael's pick (2026-11-17), shipped as
a PNG, so every picture shows the same Themi."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from themi_home import step_images
from themi_home.step_images import STYLE, chameleon_reference


def size(png: bytes) -> tuple[int, int]:
    width, height = struct.unpack(">II", png[16:24])  # the IHDR chunk
    return width, height


def test_the_reference_is_the_shipped_png_under_cloudflares_512px() -> None:
    chameleon_reference.cache_clear()
    reference = chameleon_reference()
    assert reference is not None
    assert reference.data == step_images.REFERENCE.read_bytes()
    assert reference.data.startswith(b"\x89PNG") and reference.mime_type == "image/png"
    assert reference.subject == "the chameleon"
    width, height = size(reference.data)
    assert 256 <= width < 512 and 256 <= height < 512


def test_without_the_file_the_pictures_go_without_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(step_images, "REFERENCE", tmp_path / "missing.png")
    chameleon_reference.cache_clear()
    try:
        assert chameleon_reference() is None
    finally:
        chameleon_reference.cache_clear()


def test_the_style_names_nothing_to_leave_out() -> None:
    """No text, and nothing named to leave out: "plain unlabelled bottles and boxes" put
    bottles and boxes in every picture (2026-11-17, on the Pi)."""
    assert "textless" in STYLE and "bottle" not in STYLE and "box" not in STYLE
