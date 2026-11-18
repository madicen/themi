"""A mix: music as settings, not a file (CK15a).

Every built-in track is one (`BUILT_IN`), and `tools/make_loops.py` renders those to the
`.m4a` files with ffmpeg. The cook screen's player (`static/home/mix.js`) plays a mix live
with Web Audio, so a mix made for a recipe (CK15b) needs no file. `check()` keeps every
value in a range that stays soft: slow (60-90 BPM), chords only from `CHORDS`, quiet levels.

Standard library only: `make_loops.py` imports it without the app's environment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Chords by name, low to high. A mix only uses these, so nothing harsh can be asked for.
# Some chords come in more than one voicing ("Cmaj7 low"): they're the ones the built-in
# tracks were written with.
CHORDS: dict[str, tuple[str, ...]] = {
    "Cmaj7": ("C3", "E4", "G4", "B4"),
    "Cmaj7 low": ("C2", "E3", "B3", "G4"),
    "Cmaj7 open": ("C3", "E4", "B4", "G4"),
    "Cmaj9": ("C3", "E4", "B4", "D5"),
    "C": ("C3", "E4", "G4", "C5"),
    "Cm7": ("C3", "D#4", "G4", "A#4"),
    "Dm7": ("D3", "F4", "A4", "C5"),
    "Dm7 low": ("D2", "F3", "C4", "A4"),
    "Dm9": ("D3", "F4", "A4", "E5"),
    "Dm9 open": ("D3", "F4", "C5", "E5"),
    "Dmaj7": ("D3", "F#4", "A4", "C#5"),
    "D/F#": ("F#2", "A3", "D4", "F#4"),
    "Ebmaj7": ("D#3", "G4", "A#4", "D5"),
    "Em7": ("E2", "G3", "D4", "B4"),
    "Em9": ("E3", "G4", "B4", "F#5"),
    "Fmaj7": ("F2", "A3", "C4", "E4"),
    "Fmaj7 open": ("F2", "A3", "E4", "C5"),
    "Fmaj7 high": ("F3", "A4", "C5", "E5"),
    "G": ("G2", "B3", "D4", "G4"),
    "G6": ("G2", "B3", "D4", "E4"),
    "G13": ("G2", "F4", "B4", "E5"),
    "Gmaj7": ("G2", "B3", "F#4", "D5"),
    "Gmaj7 close": ("G2", "B3", "D4", "F#4"),
    "Gm7": ("G3", "A#4", "D5", "F5"),
    "Abmaj7": ("G#2", "C4", "D#4", "G4"),
    "A": ("A2", "C#4", "E4", "A4"),
    "Am7": ("A2", "C4", "E4", "G4"),
    "Am9": ("A2", "G4", "C5", "B4"),
    "Am9 close": ("A2", "C4", "G4", "B4"),
    "Bb6": ("A#2", "D4", "F4", "G4"),
    "Bm7": ("B2", "D4", "F#4", "A4"),
}
KINDS = ("lofi", "soft_piano", "rain", "brown_noise")
MUSICAL = ("lofi", "soft_piano")  # the kinds with chords, the ones a recipe's mix can be
COLOURS = ("white", "pink", "brown")


class MixRefused(ValueError):
    """A mix with a value out of range: it isn't played."""


@dataclass(frozen=True)
class Noise:
    """Noise under (or instead of) the music: rain, a hum, a lofi crackle."""

    color: str
    amplitude: float
    highpass: int = 0  # Hz, 0 for none
    lowpass: int = 0
    swell_hz: float = 0.0  # a slow swell (tremolo), 0 for none
    swell_depth: float = 0.0
    gain: float = 1.0


@dataclass(frozen=True)
class Mix:
    name: str
    kind: str
    bpm: int = 70
    beats: int = 4  # per bar
    chords: tuple[str, ...] = ()  # names in CHORDS, one a bar
    strikes: int = 1  # times a bar each chord is struck
    decay: float = 1.0  # how fast a strike fades
    level: float = 0.1  # the keys' loudness
    tone: int = 3000  # the keys' low-pass, Hz
    echo_out: float = 0.6
    echoes: tuple[tuple[int, float], ...] = ()  # (delay in ms, how loud)
    beat: bool = False  # a soft kick and hat (lofi)
    bars: int = 16
    noise: Noise | None = None
    seconds: int = 60  # a noise-only mix's loop
    extra: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def bar_seconds(self) -> float:
        return self.beats * 60 / self.bpm

    def check(self) -> Mix:
        """This mix, if every value is in range; MixRefused if not."""
        problems = []

        def need(ok: bool, what: str) -> None:
            if not ok:
                problems.append(what)

        need(isinstance(self.name, str) and 0 < len(self.name.strip()) <= 40, "a name")
        need(self.kind in KINDS, f"kind {self.kind!r}")
        need(60 <= self.bpm <= 90, f"{self.bpm} BPM")
        need(self.beats in (3, 4), f"{self.beats} beats a bar")
        need(1 <= self.strikes <= self.beats, f"{self.strikes} strikes a bar")
        need(0.5 <= self.decay <= 2.0, f"decay {self.decay}")
        need(0.02 <= self.level <= 0.18, f"level {self.level}")
        need(1500 <= self.tone <= 4000, f"tone {self.tone}")
        need(0.3 <= self.echo_out <= 0.8, f"echo {self.echo_out}")
        need(len(self.echoes) <= 2, "at most two echoes")
        for delay, loud in self.echoes:
            need(60 <= delay <= 400 and 0.05 <= loud <= 0.35, f"echo {delay} ms at {loud}")
        need(8 <= self.bars <= 32, f"{self.bars} bars")
        unknown = [c for c in self.chords if c not in CHORDS]
        need(not unknown, f"chords {unknown}")
        if self.kind in MUSICAL:
            need(2 <= len(self.chords) <= 8, "two to eight chords")
            need(self.bars % len(self.chords or (1,)) == 0, "whole rounds of chords")
        else:
            need(not self.chords and not self.beat and self.noise is not None, "noise alone")
        need(not self.beat or self.kind == "lofi", "a beat only in lofi")
        n = self.noise
        if n is not None:
            need(n.color in COLOURS, f"noise {n.color!r}")
            need(0.005 <= n.amplitude <= 0.7, f"noise at {n.amplitude}")
            need(0 <= n.highpass <= 4000 and (n.lowpass == 0 or 300 <= n.lowpass <= 10000),
                 "the noise's filters")  # fmt: skip
            need(n.swell_hz == 0 or 0.1 <= n.swell_hz <= 1.0, f"swell {n.swell_hz} Hz")
            need(0 <= n.swell_depth <= 0.5 and 0.5 <= n.gain <= 2.0, "the noise's swell or gain")
            if self.kind in MUSICAL:
                need(n.amplitude <= 0.03, "a crackle, not a wash, under music")
        need(30 <= self.seconds <= 120, f"{self.seconds} seconds")
        if problems:
            raise MixRefused("; ".join(problems))
        return self

    def for_page(self) -> dict[str, Any]:
        """What the page's player needs: the chords as their notes."""
        out = asdict(self)
        out.pop("extra")
        out["chords"] = [list(CHORDS[c]) for c in self.chords]
        out["echoes"] = [list(e) for e in self.echoes]
        return out

    def to_data(self) -> dict[str, Any]:
        """For keeping (CK15b): the chords by name."""
        out = asdict(self)
        out.pop("extra")
        out["chords"] = list(self.chords)
        out["echoes"] = [list(e) for e in self.echoes]
        return out


def from_data(data: dict[str, Any]) -> Mix:
    """A mix from kept or model-made data, checked. MixRefused for anything off."""
    try:
        raw = dict(data)
        noise = raw.pop("noise", None)
        known = {f for f in Mix.__dataclass_fields__ if f != "extra"}
        unknown = set(raw) - known
        if unknown:
            raise MixRefused(f"unknown settings {sorted(unknown)}")
        raw["chords"] = tuple(str(c) for c in raw.get("chords", ()))
        raw["echoes"] = tuple((int(d), float(v)) for d, v in raw.get("echoes", ()))
        for name, kind in (("bpm", int), ("beats", int), ("strikes", int), ("tone", int),
                           ("bars", int), ("seconds", int), ("decay", float),
                           ("level", float), ("echo_out", float)):  # fmt: skip
            if name in raw:
                raw[name] = kind(raw[name])
        if "beat" in raw:
            raw["beat"] = bool(raw["beat"])
        mix = Mix(**raw, noise=Noise(**noise) if noise else None)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, MixRefused):
            raise
        raise MixRefused(str(exc)) from exc
    return mix.check()


def _crackle(amplitude: float = 0.012) -> Noise:
    return Noise("white", amplitude, highpass=3000)


def _lofi(name: str, bpm: int, chords: tuple[str, ...], strikes: int = 2,
          crackle: float = 0.012) -> Mix:  # fmt: skip
    return Mix(name, "lofi", bpm=bpm, chords=chords, strikes=strikes, decay=1.4, level=0.045,
               tone=2600, beat=True, noise=_crackle(crackle))  # fmt: skip


def _piano(name: str, bpm: int, chords: tuple[str, ...], decay: float, level: float,
           echo_out: float, echoes: tuple[tuple[int, float], ...], **kw: Any) -> Mix:  # fmt: skip
    return Mix(name, "soft_piano", bpm=bpm, chords=chords, decay=decay, level=level,
               tone=3000, echo_out=echo_out, echoes=echoes, **kw)  # fmt: skip


# The built-in tracks, by file, in each kind's order (the first is the one it always played).
BUILT_IN: tuple[tuple[str, Mix], ...] = (
    ("lofi.m4a", _lofi("Sunday kitchen", 80, ("Cmaj7", "Am7", "Fmaj7", "G6"))),
    ("lofi-simmer.m4a", _lofi("Slow simmer", 72, ("Dm9", "G13", "Cmaj9", "Am9"))),
    ("lofi-window.m4a", _lofi("Window light", 84, ("Fmaj7 open", "Em7", "Dm7 low", "Cmaj7 low"),
                              crackle=0.008)),
    ("lofi-supper.m4a", _lofi("Late supper", 76, ("Am9 close", "Dm9 open", "Gmaj7", "Cmaj7 open"),
                              strikes=1, crackle=0.015)),
    ("lofi-bread.m4a", _lofi("Warm bread", 82, ("Ebmaj7", "Cm7", "Abmaj7", "Bb6"))),
    ("rain.m4a", Mix("Steady rain", "rain", noise=Noise(
        "pink", 0.6, highpass=500, lowpass=7000, swell_hz=0.15, swell_depth=0.35, gain=1.6))),
    ("rain-drizzle.m4a", Mix("Light drizzle", "rain", noise=Noise(
        "white", 0.35, highpass=1800, lowpass=9000, swell_hz=0.4, swell_depth=0.25, gain=0.9))),
    ("rain-roof.m4a", Mix("Rain on the roof", "rain", noise=Noise(
        "pink", 0.6, highpass=200, lowpass=2400, swell_hz=0.1, swell_depth=0.45, gain=1.8))),
    ("soft-piano.m4a", _piano("Four slow chords", 66, ("Cmaj7", "Am7", "Fmaj7", "G6"), 0.9, 0.16,
                              0.6, ((180, 0.25),))),
    ("soft-piano-evening.m4a", _piano("Evening", 60, ("Em9", "Cmaj7", "G", "D/F#"), 0.7, 0.15,
                                      0.7, ((260, 0.3),))),
    ("soft-piano-snowfall.m4a", _piano("Snowfall", 70, ("Dmaj7", "Bm7", "Gmaj7 close", "A"), 1.1,
                                       0.14, 0.5, ((120, 0.25), (360, 0.15)), strikes=2)),
    ("soft-piano-waltz.m4a", _piano("Little waltz", 84, ("Fmaj7 high", "Dm7", "Gm7", "C"), 1.6,
                                    0.13, 0.6, ((200, 0.2),), beats=3, strikes=3, bars=24)),
    ("brown-noise.m4a", Mix("Deep", "brown_noise", noise=Noise("brown", 0.5, lowpass=900,
                                                               gain=0.9))),
    ("brown-noise-hum.m4a", Mix("Soft hum", "brown_noise", noise=Noise("brown", 0.5, lowpass=420,
                                                                       gain=1.3))),
)  # fmt: skip
