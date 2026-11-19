"""CK15a: a mix is music as settings. `check()` keeps every value soft and slow, and
make_loops.py renders rain and noise from those same settings. F48a: lofi and soft piano are
composed instead (tools/compose_loops.py, tested in test_compose_loops.py)."""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from themi_home.body_double_music import LOOPS
from themi_home.music_mix import (
    BUILT_IN,
    CHORDS,
    COMPOSED,
    MUSICAL,
    Mix,
    MixRefused,
    Noise,
    from_data,
)

TOOLS = Path(__file__).parents[2] / "tools"
LOFI = Mix("Mushroom simmer", "lofi", bpm=74, chords=("Dm9", "G13", "Cmaj9", "Am9"),
           strikes=2, decay=1.4, level=0.045, tone=2600, beat=True,
           noise=Noise("white", 0.012, highpass=3000))  # fmt: skip


def test_a_soft_mix_passes() -> None:
    assert LOFI.check() is LOFI


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"bpm": 140}, "140 BPM"),
        ({"bpm": 40}, "40 BPM"),
        ({"chords": ("Dm9", "C#dim13")}, "C#dim13"),
        ({"chords": ("Dm9",)}, "two to eight chords"),
        ({"level": 0.9}, "level 0.9"),
        ({"beats": 7}, "7 beats"),
        ({"strikes": 5}, "5 strikes"),
        ({"echoes": ((900, 0.9),)}, "echo 900"),
        ({"kind": "death_metal"}, "kind"),
        ({"noise": Noise("white", 0.6)}, "a crackle, not a wash"),
        ({"bars": 18}, "whole rounds"),
        ({"name": ""}, "a name"),
    ],
)
def test_anything_out_of_range_is_refused(change: dict, said: str) -> None:
    with pytest.raises(MixRefused, match=said):
        replace(LOFI, **change).check()


def test_from_data_round_trips_and_refuses_unknown_settings() -> None:
    assert from_data(LOFI.to_data()) == LOFI
    with pytest.raises(MixRefused, match="unknown settings"):
        from_data({**LOFI.to_data(), "distortion": 11})
    with pytest.raises(MixRefused):
        from_data({**LOFI.to_data(), "bpm": "fast"})


def test_the_page_gets_the_chords_as_notes() -> None:
    page = LOFI.for_page()
    assert page["chords"][0] == list(CHORDS["Dm9"])
    assert page["noise"]["highpass"] == 3000 and page["bpm"] == 74


def test_every_built_in_track_is_a_mix_that_passes_or_is_composed() -> None:
    mixes, composed = dict(BUILT_IN), dict(COMPOSED)
    assert not set(mixes) & set(composed)
    files = {t.file for loop in LOOPS.values() for t in loop.tracks}
    assert files == set(mixes) | set(composed)
    for loop in LOOPS.values():
        for track in loop.tracks:
            if track.file in composed:  # F48a: lofi and soft piano, written from a seed
                made = composed[track.file]
                assert track.mix is None and made.name == track.name
                assert made.kind == loop.key and made.kind in MUSICAL
            else:
                assert track.mix is not None and track.mix == mixes[track.file]
                assert track.mix.check().kind == loop.key and track.mix.name == track.name


def test_make_loops_renders_the_same_settings() -> None:
    spec = importlib.util.spec_from_file_location("make_loops", TOOLS / "make_loops.py")
    assert spec and spec.loader
    make_loops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_loops)
    assert set(make_loops.TRACKS) == {file.removesuffix(".m4a") for file, _ in BUILT_IN}
    roof = " ".join(make_loops.TRACKS["rain-roof"])
    assert "color=pink" in roof and "highpass=f=200,lowpass=f=2400" in roof
    assert "tremolo=f=0.1:d=0.45" in roof and "volume=1.8" in roof
    # a musical mix (a recipe's, like LOFI) still renders its chords, length and tone
    rendered = " ".join(make_loops.args(LOFI))
    for note in CHORDS[LOFI.chords[0]]:
        assert f"{make_loops.note(note):.3f}" in rendered
    assert f"d={LOFI.bar_seconds * LOFI.bars:.4f}" in rendered and "lowpass=f=2600" in rendered
