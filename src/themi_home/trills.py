"""Themi's trills (WA4): the five short chameleon chirps the wall's alerts play.

Each is a few notes: a sine whose pitch sweeps from `f0` to `f1` with a fast vibrato
(`rate` times a second, `depth` Hz either way) and a little second harmonic, fading out
over its length. `tools/make_trills.py` renders them with ffmpeg into
`static/audio/trills/<name>.m4a`; the mockup's last frame plays the same notes in a browser.
Original sounds, made from code: CC0 (static/audio/LICENCES.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    at: float  # seconds into the trill
    dur: float
    f0: float  # Hz at the start
    f1: float  # Hz at the end
    rate: float  # vibrato, per second
    depth: float  # vibrato, Hz


TRILLS: dict[str, tuple[Note, ...]] = {
    # a leave card appears: two soft rising chirps
    "ready": (Note(0, 0.16, 950, 1350, 22, 50), Note(0.24, 0.26, 1150, 1700, 26, 80)),
    # five minutes to go: three climbing chirps
    "five": (
        Note(0, 0.14, 1000, 1300, 24, 60),
        Note(0.19, 0.14, 1150, 1500, 24, 70),
        Note(0.38, 0.24, 1300, 1950, 28, 100),
    ),
    # leave-by: a full trill twice, then a hop up
    "go": (
        Note(0, 0.45, 900, 1900, 30, 140),
        Note(0.6, 0.45, 900, 1900, 30, 140),
        Note(1.18, 0.12, 1900, 2500, 20, 40),
    ),
    # a timer is up: three bubbly falling trills and a pop
    "kitchen": (
        Note(0, 0.22, 1800, 1150, 34, 110),
        Note(0.28, 0.22, 1750, 1100, 34, 110),
        Note(0.56, 0.22, 1700, 1050, 34, 110),
        Note(0.86, 0.08, 2100, 2600, 10, 20),
    ),
    # someone taps We're off or Got it on a card: one tiny chirp
    "got-it": (Note(0, 0.12, 1400, 2100, 18, 40),),
}


def length(name: str) -> float:
    return max(n.at + n.dur for n in TRILLS[name])
