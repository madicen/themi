"""F48a: the built-in lofi and soft piano, composed from a seed on real instruments.

The samples aren't here (they're fetched into a cache when the tool runs), so these play
the tracks on fake instruments: decaying sines for the keys, short noise for the drums.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from themi_home.music_mix import COMPOSED, MUSICAL, Composed
from tools import compose_loops as cl


@pytest.fixture
def fake_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cl, "SR", 16000)  # a third of the work; every filter is below 8 kHz

    def instrument(name: str) -> cl.Sampler:
        s = cl.Sampler(name)
        t = np.arange(int(1.5 * cl.SR)) / cl.SR
        for layer in (2, 4):
            for midi in range(36, 97, 6):
                f = 440 * 2 ** ((midi - 69) / 12)
                s.add(layer, float(midi), np.sin(2 * np.pi * f * t) * np.exp(-t * 3))
        return s

    def hits(pattern: str) -> list[np.ndarray]:
        rng = np.random.default_rng(len(pattern))
        t = np.arange(int(0.2 * cl.SR)) / cl.SR
        return [rng.normal(0, 0.3, len(t)) * np.exp(-t * 30) for _ in range(2)]

    monkeypatch.setattr(cl, "instrument", instrument)
    monkeypatch.setattr(cl, "hits", hits)


def test_chords_are_read_from_numerals_in_a_key() -> None:
    assert cl.chord("ii9", 0) == cl.Chord(2, (0, 3, 7, 10, 14), 2)
    assert cl.chord("bVImaj7", 9) == cl.Chord(5, (0, 4, 7, 11), 5)  # F in A minor
    assert cl.chord("I/iii", 7).bass == 11  # G over B
    with pytest.raises(ValueError):
        cl.chord("VIII", 0)


def test_voicings_stay_in_range_and_move_little() -> None:
    prev = None
    for tok in ["Imaj7", "vi7", "ii7", "V7sus", "Imaj7"]:
        notes = cl.voice(cl.chord(tok, 0), prev, 55, 76, drop_root=False)
        assert all(55 <= n <= 76 for n in notes) and notes[-1] - notes[0] <= 15
        if prev:
            assert all(min(abs(n - p) for p in prev) <= 4 for n in notes)
        prev = notes


def test_lofi_chords_are_wide_with_the_root_low() -> None:
    """Like the lofi MIDI: a left-hand root and seventh, colour notes above (about 22 apart)."""
    for tok in ["i9", "bVImaj7", "iv7", "bIIImaj7"]:
        ch = cl.chord(tok, 4)
        lh, rh = cl.lofi_voice(ch, None)
        assert 43 <= lh[0] <= 54 and lh[0] % 12 == ch.bass
        assert all(58 <= n <= 74 for n in rh) and rh[-1] - lh[0] >= 15


def test_the_lofi_chords_keep_away_from_tension() -> None:
    """No flat nines or other altered tones, the clash that made the first lofi harsh."""
    for prog in cl.LOFI_MAJOR + cl.LOFI_MINOR:
        for tok in prog:
            assert 1 not in {t % 12 for t in cl.chord(tok, 0).tones}, tok


def test_a_hook_note_a_half_step_off_the_chord_moves_onto_it() -> None:
    c_major = cl.chord("I", 0)
    assert cl.fit(61, c_major) == 60  # C sharp over C: onto C
    assert cl.fit(62, c_major) == 62  # D is a step from both: it stays
    assert cl.fit(64, c_major) == 64


def test_the_tail_folds_onto_the_start_so_the_loop_has_no_seam() -> None:
    loop_len = 2.0
    x = np.zeros(int(3 * cl.SR))
    t = np.arange(int(0.5 * cl.SR)) / cl.SR
    note = np.sin(2 * np.pi * 220 * t) * np.exp(-t * 4)
    x[int(1.9 * cl.SR) : int(1.9 * cl.SR) + len(note)] = note  # rings past the loop's end
    y = cl.finish(x, loop_len, -20)
    assert len(y) == int(loop_len * cl.SR)
    assert np.max(np.abs(y[: int(0.3 * cl.SR)])) > 0.05  # what rang on is at the start
    assert abs(y[0] - y[-1]) <= np.max(np.abs(np.diff(y)))  # no bigger than any other step


@pytest.mark.parametrize("kind", sorted(MUSICAL))
def test_each_style_renders_a_whole_loop_the_same_each_time(fake_kit: None, kind: str) -> None:
    track = Composed("Test", kind, 1, minor=True)
    mix, info = cl.STYLES[kind](track)
    again, _ = cl.STYLES[kind](track)
    assert np.array_equal(mix, again)  # the seed is the track
    assert 60 * cl.SR < len(mix) < 130 * cl.SR and np.all(np.isfinite(mix))
    target = -21 if kind == "lofi" else -24
    assert abs(20 * np.log10(np.sqrt(np.mean(mix**2))) - target) < 2
    assert np.max(np.abs(mix)) < 1 / 1.4  # the peaks are rounded off below full scale
    assert abs(mix[0] - mix[-1]) <= np.max(np.abs(np.diff(mix)))
    if kind == "lofi":
        assert "minor" in info


def test_every_composed_track_has_a_style_and_its_own_seed() -> None:
    assert set(cl.TRACKS) == {file.removesuffix(".m4a") for file, _ in COMPOSED}
    for kind in MUSICAL:
        seeds = [c.seed for _, c in COMPOSED if c.kind == kind]
        assert kind in cl.STYLES and len(seeds) == len(set(seeds)) >= 2


def test_the_samples_come_from_pinned_commits() -> None:
    """The same files every time, so a seed keeps making the same track."""
    for src in cl.SOURCES:
        assert re.fullmatch(r"[0-9a-f]{40}", src.commit), src.repo
