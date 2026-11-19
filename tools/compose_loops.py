"""Compose the built-in lofi and soft piano tracks (F48a), played on real instruments.

    .venv/bin/python tools/compose_loops.py [name ...]   # writes static/audio/*.m4a

Each track is written from a seed (`music_mix.COMPOSED`): its key, tempo, chords, voicings,
hook or tune, and drums. The same seed gives the same track, so a track is remade only by
naming it. Rain and brown noise stay with `make_loops.py`.

The instruments are samples, fetched once at pinned commits into a cache outside the repo
(`~/.cache/themi/loop-samples`, or $THEMI_LOOP_SAMPLES) and never committed:
- VCSL, the Versilian Community Sample Library (CC0): the Kawai grand, hi-hats, snare.
- jRhodes3d by Jeff Learman, a 1977 Rhodes Mark I. Its samples are CC BY-NC, and music made
  with them is CC0, so the rendered tracks stay ours to give away (static/audio/LICENCES.md).
The kick and the bass are synthesised here.

What the lofi leans on, from 93 lofi MIDI files and the genre's production guides: minor and
major 7ths and 9ths (no altered chords), voiced wide with a low root, on a Rhodes or a soft
grand; a four-bar hook around B4 that repeats exactly; a round sine bass; a soft kit that
sits back (dark short hats, a late soft snare, the kick on a looser swing than the hats); a
short room. Nothing imitates a record: no crackle, no hiss, no wobble.

numpy and scipy come with the dev extra; ffmpeg decodes the samples and encodes the tracks.
"""

from __future__ import annotations

import itertools
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SRC = Path(__file__).parents[1] / "src"
OUT = SRC / "themi_home" / "web" / "static" / "audio"
SR = 48000
KBPS = 96

sys.path.insert(0, str(SRC))
from themi_home.music_mix import COMPOSED, Composed  # noqa: E402

# ---------------------------------------------------------------- the samples

CACHE = Path(os.environ.get("THEMI_LOOP_SAMPLES", Path.home() / ".cache/themi/loop-samples"))


@dataclass(frozen=True)
class Source:
    folder: str
    repo: str
    commit: str  # pinned: the same files, so the same tracks
    wanted: str  # the paths used, as a regex


SOURCES = (
    Source("vcsl", "sgossner/VCSL", "c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e",
           r"Grand Piano, Kawai/Sustains/GPiano_sus_.*_v[12]_rr1_.*\.wav"
           r"|Hi-Hat Cymbal/HiHat_(Close|HitC_v[12])_.*\.wav"
           r"|Snare Drum, Modern 1/Snare2_(HitSN_v3|taps)_.*\.wav"),
    Source("rhodes", "sfzinstruments/jlearman.jRhodes3d",
           "aea5b8d3e11e2f7102593789a4e0a0e41b30271a", r"jRhodes3d-mono/A_\d+__\w+_[245]\.flac"),
)  # fmt: skip


def fetch() -> None:
    """Download whatever of the samples isn't in the cache yet (the only network use)."""
    for src in SOURCES:
        base = CACHE / src.folder
        listing = base / f"tree-{src.commit}.json"
        if not listing.exists():
            base.mkdir(parents=True, exist_ok=True)
            url = f"https://api.github.com/repos/{src.repo}/git/trees/{src.commit}?recursive=1"
            with urllib.request.urlopen(url, timeout=60) as reply:
                listing.write_bytes(reply.read())
        paths = [e["path"] for e in json.loads(listing.read_text())["tree"]
                 if e["type"] == "blob" and re.search(src.wanted, e["path"])]  # fmt: skip
        missing = [p for p in paths if not (base / p).exists()]
        for k, path in enumerate(missing, 1):
            target = base / path
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = f"https://raw.githubusercontent.com/{src.repo}/{src.commit}/"
            with urllib.request.urlopen(raw + urllib.parse.quote(path), timeout=120) as reply:
                target.with_suffix(".part").write_bytes(reply.read())
            target.with_suffix(".part").rename(target)
            print(f"{src.folder}: {k}/{len(missing)}", end="\r", file=sys.stderr)
        if missing:
            print(f"{src.folder}: fetched {len(missing)} samples", file=sys.stderr)


def files(folder: str, pattern: str) -> list[str]:
    return sorted(str(p) for p in (CACHE / folder).glob(pattern))


def decode(path: str) -> np.ndarray:
    """A sample as floats, from its onset, scaled so its first 0.3 s peaks at 1."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout  # fmt: skip
    x = np.frombuffer(raw, np.float32).astype(np.float64)
    peak = np.max(np.abs(x)) or 1.0
    start = max(0, int(np.argmax(np.abs(x) > 0.03 * peak)) - int(0.002 * SR))
    x = x[start:]
    head = np.max(np.abs(x[: int(0.3 * SR)])) or 1.0
    return x / head


PCS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_midi(name: str) -> int:
    m = re.fullmatch(r"([A-G])(#?)(-?\d)", name)
    if not m:
        raise ValueError(name)
    return 12 * (int(m.group(3)) + 1) + PCS[m.group(1)] + (1 if m.group(2) else 0)


def measure(x: np.ndarray, near: float) -> float:
    """The sample's pitch as a fractional MIDI number, found near the one its name says:
    the sampler tunes from this, so every instrument agrees with every other."""
    seg = x[int(0.05 * SR) : int(0.05 * SR) + SR]
    n = 8 * len(seg)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    f = 440 * 2 ** ((near - 69) / 12)
    k = 1 if near >= 50 else 2  # low notes: tune from the 2nd harmonic
    band = (freqs > k * f * 2 ** (-0.7 / 12)) & (freqs < k * f * 2 ** (0.7 / 12))
    f0 = freqs[band][np.argmax(spec[band])] / k
    return 69 + 12 * math.log2(f0 / 440)


def mix_in(out: np.ndarray, at: float, y: np.ndarray) -> None:
    """Add `y` at `at` seconds. A negative time (a push before bar one) lands at the loop's
    end, and anything past the buffer wraps to the start."""
    i = round(at * SR) % len(out)
    j = min(len(out), i + len(y))
    out[i:j] += y[: j - i]
    if i + len(y) > len(out):
        rest = y[j - i :]
        out[: len(rest)] += rest[: len(out)]


@dataclass
class Sampler:
    name: str
    layers: dict[int, list[tuple[float, np.ndarray]]] = field(default_factory=dict)

    def add(self, layer: int, midi: float, x: np.ndarray) -> None:
        self.layers.setdefault(layer, []).append((midi, x))

    def play(self, out: np.ndarray, at: float, midi: int, vel: float, dur: float,
             release: float = 0.25) -> None:  # fmt: skip
        """The nearest sample in the velocity's layer, repitched, held `dur` seconds."""
        layer_keys = sorted(self.layers)
        layer = layer_keys[min(len(layer_keys) - 1, int(vel * len(layer_keys)))]
        src, x = min(self.layers[layer], key=lambda s: abs(s[0] - midi))
        ratio = 2 ** ((midi - src) / 12)
        n = min(int((dur + release) * SR), int((len(x) - 2) / ratio))
        if n <= 0:
            return
        y = np.interp(np.arange(n) * ratio, np.arange(len(x)), x)
        cut = int(dur * SR)
        if cut < n:
            y[cut:] *= np.exp(-np.arange(n - cut) / SR / (release / 4))
        mix_in(out, at, y * vel**1.5)


@cache
def instrument(name: str) -> Sampler:
    s = Sampler(name)
    if name == "grand":  # the Kawai: its names are an octave low (C3 is middle C)
        for f in files("vcsl", "**/Grand Piano, Kawai/Sustains/*_v[12]_rr1_*.wav"):
            m = re.search(r"_sus_([A-G]#?-?\d)_v(\d)", f)
            assert m, f
            midi = note_midi(m.group(1)) + 12
            if 33 <= midi <= 96:
                x = decode(f)
                s.add(int(m.group(2)), measure(x, midi), x)
    elif name == "rhodes":  # the layers with every note: 2, 4, 5
        for f in files("rhodes", "jRhodes3d-mono/A_*.flac"):
            m = re.search(r"A_(\d+)__\w+?_(\d)\.flac", f)
            assert m, f
            if int(m.group(2)) in (2, 4, 5):
                x = decode(f)
                s.add(int(m.group(2)), measure(x, int(m.group(1))), x)
    else:
        raise KeyError(name)
    if not s.layers:
        raise FileNotFoundError(f"no {name} samples under {CACHE} (fetch() gets them)")
    return s


@cache
def hits(pattern: str) -> list[np.ndarray]:
    return [decode(f) for f in files("vcsl", "**/" + pattern)]


# ---------------------------------------------------------------- harmony

NUMERALS = {"I": 0, "II": 2, "III": 4, "IV": 5, "V": 7, "VI": 9, "VII": 11}
UPPER = {"": (0, 4, 7), "maj7": (0, 4, 7, 11), "maj9": (0, 4, 7, 11, 14), "6": (0, 4, 7, 9),
         "7": (0, 4, 7, 10), "9": (0, 4, 7, 10, 14), "7sus": (0, 5, 7, 10),
         "9sus": (0, 5, 10, 14), "add9": (0, 4, 7, 14)}  # fmt: skip
LOWER = {"": (0, 3, 7), "7": (0, 3, 7, 10), "9": (0, 3, 7, 10, 14), "11": (0, 3, 7, 10, 14, 17),
         "6": (0, 3, 7, 9), "add9": (0, 3, 7, 14)}  # fmt: skip
NAMES = "C Db D Eb E F F# G Ab A Bb B".split()


@dataclass(frozen=True)
class Chord:
    root: int  # pitch class
    tones: tuple[int, ...]  # intervals over the root
    bass: int  # pitch class

    @property
    def pcs(self) -> set[int]:
        return {(self.root + t) % 12 for t in self.tones}


def numeral(tok: str) -> tuple[int, bool]:
    """'bVI' -> (8, False): semitones over the key, and whether it's minor (lower case)."""
    m = re.fullmatch(r"(b?)(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)", tok)
    if not m:
        raise ValueError(tok)
    return NUMERALS[m.group(2).upper()] - (1 if m.group(1) else 0), m.group(2).islower()


def chord(tok: str, key: int) -> Chord:
    """'ii9', 'bVImaj7', 'I/iii' (over the third) in a key (0 = C)."""
    head, _, slash = tok.partition("/")
    m = re.fullmatch(r"(b?(?:VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i))(.*)", head)
    if not m:
        raise ValueError(tok)
    off, minor = numeral(m.group(1))
    qualities = LOWER if minor else UPPER
    if m.group(2) not in qualities:
        raise ValueError(tok)
    root = (key + off) % 12
    bass = (key + numeral(slash)[0]) % 12 if slash else root
    return Chord(root, qualities[m.group(2)], bass)


def scale_of(key: int, minor: bool) -> list[int]:
    steps = (0, 2, 3, 5, 7, 8, 10) if minor else (0, 2, 4, 5, 7, 9, 11)
    return sorted((key + s) % 12 for s in steps)


def voice(ch: Chord, prev: list[int] | None, lo: int, hi: int, drop_root: bool,
          max_notes: int = 4) -> list[int]:  # fmt: skip
    """Chord tones placed in [lo, hi], moving as little as they can from `prev`."""
    tones = [t for t in ch.tones if not (drop_root and t == 0)]
    if len(tones) > max_notes and 7 in tones:
        tones.remove(7)  # the fifth goes first
    tones = tones[:max_notes]
    pcs = [(ch.root + t) % 12 for t in tones]
    options = [[p for p in range(lo, hi + 1) if p % 12 == pc] for pc in pcs]
    best, best_cost = None, 1e9
    centre = (lo + hi) / 2
    for combo in itertools.product(*options):
        notes = sorted(combo)
        if notes[-1] - notes[0] > 15 or len(set(notes)) < len(notes):
            continue
        if any(b - a < 2 for a, b in itertools.pairwise(notes[:3])):
            continue  # no mud at the bottom
        cost = abs(sum(notes) / len(notes) - centre) * 0.6
        if prev:
            cost += sum(min(abs(n - p) for p in prev) for n in notes)
        if cost < best_cost:
            best, best_cost = notes, cost
    return best or sorted(o[0] for o in options)


def chord_at(harmony: list[tuple[float, float, Chord]], beat: float) -> Chord:
    for start, length, ch in harmony:
        if start <= beat < start + length:
            return ch
    return harmony[-1][2]


@dataclass
class Clock:
    bpm: float
    beats: int  # a bar
    swing: float = 0.5  # where the off-beat eighth lands (0.5 straight)

    def t(self, beat: float) -> float:
        whole, frac = divmod(beat, 1.0)
        if frac <= 0.5:
            frac = frac / 0.5 * self.swing
        else:
            frac = self.swing + (frac - 0.5) / 0.5 * (1 - self.swing)
        return (whole + frac) * 60 / self.bpm

    @property
    def bar(self) -> float:
        return self.beats * 60 / self.bpm


# ---------------------------------------------------------------- effects


def lowpass(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return np.asarray(sosfilt(butter(order, hz, "low", fs=SR, output="sos"), x))


def highpass(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return np.asarray(sosfilt(butter(order, hz, "high", fs=SR, output="sos"), x))


def reverb(x: np.ndarray, seconds: float, wet: float, rng: np.random.Generator,
           tone: float = 5000) -> np.ndarray:  # fmt: skip
    """A room: decaying noise as the impulse, darkened, after a short pre-delay."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = lowpass(rng.normal(0, 1, n) * np.exp(-6.9 * t / seconds), tone)
    ir[: int(0.012 * SR)] = 0
    ir /= np.sqrt(np.sum(ir**2))
    return x + wet * fftconvolve(x, ir)[: len(x)]


def sidechain(n: int, times: list[float], depth: float) -> np.ndarray:
    """A gain that dips `depth` at each kick and comes back over about 0.1 s."""
    env = np.ones(n)
    shape = 1 - depth * np.exp(-np.arange(int(0.35 * SR)) / SR / 0.09)
    for t in times:
        i = int(t * SR) % n
        j = min(n, i + len(shape))
        env[i:j] = np.minimum(env[i:j], shape[: j - i])
    return env


def finish(x: np.ndarray, loop_len: float, rms_db: float) -> np.ndarray:
    """Fold the tail past the loop onto its start (so it loops without a seam), then level
    it and round off the peaks."""
    x = highpass(x, 32)  # before the fold: a filter started at the fold would step at the seam
    n = round(loop_len * SR)
    y = x[:n].copy()
    tail = x[n:]
    y[: len(tail)] += tail[:n]
    y *= 10 ** (rms_db / 20) / (np.sqrt(np.mean(y**2)) or 1)
    return np.tanh(y * 1.4) / 1.4


def encode(x: np.ndarray, path: Path) -> None:
    """Mono AAC (every phone browser plays it), like make_loops.py's."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1",
                    "-i", "-", "-c:a", "aac", "-b:a", f"{KBPS}k", "-movflags", "+faststart",
                    str(path)], input=x.astype(np.float32).tobytes(), check=True)  # fmt: skip


# ---------------------------------------------------------------- soft piano

PIANO_MAJOR = [
    ["I", "V/vii", "vi", "IV"],
    ["Iadd9", "iii", "IV", "iv"],
    ["vi", "IV", "I", "V"],
    ["Imaj7", "IVmaj7", "Imaj7", "IVmaj7"],
    ["I", "I/iii", "IV", "V9sus"],
    ["IVadd9", "I/iii", "ii7", "V7sus"],
    ["I", "vi7", "ii7", "V7sus"],
    ["Iadd9", "V/vii", "vi7", "I/v", "IVmaj7", "I/iii", "ii7", "V7sus"],
]
PIANO_MINOR = [
    ["i", "bVI", "bIII", "bVII"],
    ["i", "iv", "bVIIadd9", "bIIImaj7"],
    ["iadd9", "bVImaj7", "iv7", "V7sus"],
]
PIANO_RHYTHMS_4: list[list[tuple[float, float]]] = [  # two bars: (beat, length)
    [(0, 2), (2, 1), (3, 1), (4, 4)],
    [(0, 1.5), (1.5, 0.5), (2, 2), (4, 2), (6, 2)],
    [(1, 1), (2, 1), (3, 1), (4, 3)],
    [(0, 3), (3, 1), (4, 2), (6, 1), (7, 1)],
]
PIANO_RHYTHMS_3: list[list[tuple[float, float]]] = [
    [(0, 2), (2, 1), (3, 3)],
    [(0, 1), (1, 1), (2, 1), (3, 3)],
    [(0, 3), (3, 2), (5, 1)],
    [(1, 1), (2, 1), (3, 2), (5, 1)],
]

Harmony = list[tuple[float, float, Chord]]


def melody(rng: np.random.Generator, harmony: Harmony, scale: list[int], bars: int,
           clock: Clock, rhythms: list[list[tuple[float, float]]], lo: int, hi: int
           ) -> list[tuple[float, float, int, float]]:  # fmt: skip
    """The piano's tune, (beat, length, note, velocity): a two-bar motif, answered,
    repeated, resolved every eight bars."""
    bpb = clock.beats
    notes = []
    pool = [p for p in range(lo, hi + 1) if p % 12 in scale]
    motif = rhythms[rng.integers(len(rhythms))]
    answer = rhythms[rng.integers(len(rhythms))]
    prev = pool[len(pool) // 2]
    for phrase in range(0, bars, 2):
        place = (phrase % 8) // 2
        rhythm = motif if place in (0, 2) else answer
        if place == 3:  # the cadence: fewer notes, a long last one
            rhythm = [r for r in answer if r[0] < bpb] + [(bpb, bpb)]
        direction = 1 if place < 2 else -1
        for k, (onset, length) in enumerate(rhythm):
            beat = phrase * bpb + onset
            ch = chord_at(harmony, beat)
            strong = onset % 1 == 0 and (onset % 2 == 0 or length >= 1)
            last = k == len(rhythm) - 1
            if strong or last:
                cands = [p for p in pool if p % 12 in ch.pcs]
                if last and place == 3:
                    cands = [p for p in cands if (p - ch.root) % 12 in (0, 3, 4)] or cands
                target = prev + direction * rng.integers(0, 4)
                pitch = min(cands, key=lambda p: abs(p - target) + rng.random())
            else:
                i = min(range(len(pool)), key=lambda j: abs(pool[j] - prev))
                step = direction * rng.choice([1, 1, 1, 2, -1])
                pitch = pool[int(np.clip(i + step, 0, len(pool) - 1))]
            if abs(pitch - prev) > 7:
                pitch = prev + int(np.sign(pitch - prev)) * min(
                    (abs(p - prev) for p in pool if abs(p - prev) <= 7 and p % 12 in scale),
                    default=0,
                )
            if rng.random() < 0.12 and not last:  # breathe
                continue
            vel = 0.55 + 0.25 * (1 if strong else 0) + rng.normal(0, 0.05)
            notes.append((beat, length, int(pitch), float(np.clip(vel, 0.2, 0.95))))
            prev = pitch
    return notes


def piano(track: Composed) -> tuple[np.ndarray, str]:
    """The grand alone, pedal down, no drums: each eight-bar section picks a texture
    (sparse, broken chords, or rolled hymn chords) under a slow tune; some are waltzes."""
    rng = np.random.default_rng(track.seed + 7919)
    minor = rng.random() < 0.25
    key = int(rng.integers(12))
    waltz = rng.random() < 0.35
    clock = Clock(float(rng.integers(56, 73)) * (1.3 if waltz else 1), 3 if waltz else 4)
    pool = PIANO_MINOR if minor else PIANO_MAJOR
    a, b = (pool[i] for i in rng.choice(len(pool), 2, replace=False))
    bpb = clock.beats
    harmony: Harmony = []
    beat = 0.0
    for prog in (a, a, b, a):
        for tok in (prog * 4)[:8]:
            harmony.append((beat, bpb, chord(tok, key)))
            beat += bpb
    bars = 32
    loop_len = clock.t(bars * bpb)
    out = np.zeros(int((loop_len + 6) * SR))
    grand = instrument("grand")

    def hum() -> float:
        return rng.normal(0, 0.012)

    textures = ["sparse", "broken", "hymn", "broken"]
    tex = [textures[i] for i in rng.permutation(len(textures))]
    tex[3] = tex[0] if rng.random() < 0.5 else tex[3]
    scale = scale_of(key, minor)
    tune = melody(rng, harmony, scale, bars, clock,
                  PIANO_RHYTHMS_3 if waltz else PIANO_RHYTHMS_4, 67, 84)  # fmt: skip
    prev = None
    for bar in range(bars):
        t_bar = bar * bpb
        ch = chord_at(harmony, t_bar)
        lag = 0.08 if bar % 4 == 3 else 0.0  # lean on the phrase's last bar
        bass = 36 + (ch.bass - 36) % 12
        if bass < 40:
            bass += 12
        pedal = clock.bar * 1.02  # held through the bar
        style = tex[bar // 8]
        lh_vel = rng.uniform(0.35, 0.5)
        grand.play(out, clock.t(t_bar) + lag + hum(), bass, lh_vel, pedal, release=0.6)
        if style == "sparse":
            fifth = bass + 7 if (ch.root - ch.bass) % 12 == 0 else bass + 12
            grand.play(out, clock.t(t_bar) + lag + 0.03 + hum(), fifth, lh_vel * 0.8, pedal, 0.6)
        elif style == "broken":
            notes = voice(ch, prev, 55, 76, drop_root=False, max_notes=4)
            prev = notes
            shape = str(rng.choice(["up", "updown", "alberti"]))
            seq = {"up": notes + notes[1:][::-1][: max(0, 2 * bpb - len(notes))],
                   "updown": notes + notes[-2:0:-1],
                   "alberti": [notes[0], notes[-1], notes[1], notes[-1]] * 2}[shape]  # fmt: skip
            for e in range(2 * bpb):
                grand.play(out, clock.t(t_bar + e / 2) + lag + hum(), seq[e % len(seq)],
                           rng.uniform(0.25, 0.42), pedal - e * 30 / clock.bpm, 0.6)  # fmt: skip
        else:  # hymn: rolled chords, twice a bar
            notes = voice(ch, prev, 52, 74, drop_root=False, max_notes=4)
            prev = notes
            for half in (0, bpb // 2 + (bpb % 2)):
                if half and rng.random() < 0.4:
                    continue
                for k, m in enumerate(notes):
                    at = clock.t(t_bar + half) + lag + k * rng.uniform(0.02, 0.05) + hum()
                    grand.play(out, at, m, rng.uniform(0.3, 0.45),
                               pedal - half * 60 / clock.bpm, 0.6)  # fmt: skip
    for beat, length, m, vel in tune:
        bar = int(beat // bpb)
        style = tex[bar // 8]
        if style == "broken" and rng.random() < 0.5:
            continue  # the arpeggio carries it; the tune comes and goes
        if bar < 4:
            continue
        lag = 0.08 if bar % 4 == 3 else 0.0
        up = 12 if style == "broken" else 0
        soft = float(np.clip(vel * 0.75, 0.3, 0.7))
        grand.play(
            out, clock.t(beat) + lag + hum(), m + up, soft, length * 60 / clock.bpm * 1.4, 0.8
        )
    mix = lowpass(out, 6500)
    mix = reverb(mix, rng.uniform(2.2, 3.2), rng.uniform(0.35, 0.5), rng, tone=4500)
    info = (f"{NAMES[key]} {'minor' if minor else 'major'}, {clock.bpm:.0f} BPM in {bpb}, "
            f"{' / '.join(tex)}")  # fmt: skip
    return finish(mix, loop_len, -24), info


# ---------------------------------------------------------------- lofi

# From 44 keyed lofi MIDI files: m7 and maj7 above all, then minor triads, m9 and maj9;
# dominant 7ths rare and no altered chords; half in minor; often starting off the tonic.
LOFI_MINOR = [
    ["i9", "bVImaj7", "iv7", "bIIImaj7"],
    ["bVImaj7", "iv9", "i7", "i7"],
    ["i7", "v7", "bVImaj7", "bVImaj7"],
    ["iv9", "bVII", "bIIImaj7", "bVImaj7"],
    ["bVImaj7", "bVII", "i9", "i9"],
    ["i9", "iv9", "v7", "bVImaj7"],
    ["bVImaj7", "v7", "iv7", "i9"],
]
LOFI_MAJOR = [
    ["ii9", "IVmaj7", "Imaj9", "vi7"],
    ["IVmaj7", "V", "iii7", "vi9"],
    ["Imaj9", "vi9", "ii9", "IVmaj7"],
    ["vi9", "IVmaj7", "Imaj7", "iii7"],
    ["ii9", "iii7", "IVmaj9", "IVmaj9"],
    ["IVmaj9", "iii7", "vi9", "Imaj7"],
]
COMP = [  # one bar: (beat, length in beats, velocity); -0.5 is pushed from the bar before
    [(0, 3.9, 0.7)],
    [(-0.5, 4.4, 0.7)],
    [(0, 2.4, 0.7), (2.5, 1.4, 0.5)],
    [(-0.5, 2.9, 0.7), (2.5, 1.4, 0.5)],
    [(0, 1.4, 0.68), (1.5, 2.4, 0.55)],
]
KICKS = [[0, 2.5], [0, 1.75, 2.5], [0, 2.25], [0, 0.75, 2.5], [0, 2.5, 2.75]]
HATS = {  # which eighths play, and how hard
    "eighths": [1, 0.55, 0.8, 0.55, 1, 0.55, 0.8, 0.55],
    "skip": [1, 0, 0.8, 0.55, 1, 0, 0.8, 0.55],
    "offbeats": [0, 0.8, 0, 0.8, 0, 0.8, 0, 0.8],
    "quarters": [1, 0, 0.8, 0, 1, 0, 0.8, 0],
}
HOOKS = [  # four bars: (beat, length); sparse, room to breathe
    [(0, 1.5), (1.5, 0.5), (2, 2), (6.5, 0.5), (7, 1), (8, 1.5), (9.5, 2.5), (14, 2)],
    [(0.5, 0.5), (1, 1), (2, 3), (8.5, 0.5), (9, 1), (10, 1), (11, 3)],
    [(0, 0.5), (0.5, 0.5), (1, 2.5), (4, 2), (8, 0.5), (8.5, 0.5), (9, 2.5), (12, 1), (13, 3)],
    [(2, 0.5), (2.5, 0.5), (3, 2), (6, 1), (10, 0.5), (10.5, 0.5), (11, 3)],
    [(0, 3), (3, 0.5), (3.5, 0.5), (4, 3), (8, 3), (11, 1), (12, 4)],
]


def lofi_voice(ch: Chord, prev_rh: list[int] | None) -> tuple[list[int], list[int]]:
    """Left hand: the root low with its seventh (or fifth). Right hand: three colour notes
    close together, moving as little as they can. Wide, like the MIDI (about 22 semitones)."""
    root = 43 + (ch.bass - 43) % 12
    second = root + (10 if 10 in ch.tones else 11 if 11 in ch.tones else 7)
    upper = tuple(t for t in ch.tones if t not in (0, 7)) or ch.tones
    rh = voice(Chord(ch.root, upper, ch.bass), prev_rh, 58, 74, drop_root=False, max_notes=3)
    return [root, second], rh


def hook(
    rng: np.random.Generator,
    harmony: Harmony,
    scale: list[int],
    rhythm: list[tuple[float, float]],
    lo: int,
    hi: int,
) -> list[tuple[float, float, int]]:
    """One four-bar hook over the first round of chords: chord tones on the long and strong
    notes, steps between, rising then falling."""
    pool = [p for p in range(lo, hi + 1) if p % 12 in scale]
    prev = pool[len(pool) // 3 + int(rng.integers(0, 3))]
    out = []
    for k, (beat, length) in enumerate(rhythm):
        ch = chord_at(harmony, beat)
        up = k < len(rhythm) * 0.5
        if length >= 1 or beat % 1 == 0:
            cands = [p for p in pool if p % 12 in ch.pcs]
            target = prev + (2 if up else -2) * int(rng.integers(0, 2))
            pitch = min(cands, key=lambda p: abs(p - target) + 0.5 * rng.random())
        else:
            i = min(range(len(pool)), key=lambda j: abs(pool[j] - prev))
            pitch = pool[int(np.clip(i + (1 if up else -1), 0, len(pool) - 1))]
        out.append((beat, length, int(pitch)))
        prev = pitch
    return out


def fit(pitch: int, ch: Chord) -> int:
    """The hook again over other chords: a note a half step off a chord tone moves onto it."""
    if pitch % 12 in ch.pcs:
        return pitch
    if any((pitch - pc) % 12 in (1, 11) for pc in ch.pcs):
        return min((pitch + d for d in (-2, -1, 1, 2) if (pitch + d) % 12 in ch.pcs),
                   key=lambda p: abs(p - pitch))  # fmt: skip
    return pitch


def tremolo(x: np.ndarray, hz: float, depth: float) -> np.ndarray:
    t = np.arange(len(x)) / SR
    return x * (1 - depth / 2 + depth / 2 * np.sin(2 * np.pi * hz * t))


def echo(x: np.ndarray, seconds: float, feedback: float, mix: float) -> np.ndarray:
    d = int(seconds * SR)
    y = x.copy()
    tap = x.copy()
    for _ in range(4):
        tap = lowpass(np.concatenate([np.zeros(d), tap[:-d]]) * feedback, 2500)
        y += tap * mix / feedback
    return y


def kick(vel: float) -> np.ndarray:
    """Round: a soft attack, a low body that blooms a little, no click."""
    t = np.arange(int(0.55 * SR)) / SR
    f = 50 + 28 * np.exp(-t * 30)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR)
    env = np.exp(-t * 6.5) * np.minimum(1, t / 0.005)
    return lowpass(np.tanh(1.3 * body * env), 520, order=4) * vel


def sub(midi: int, dur: float, vel: float) -> np.ndarray:
    """The bass: a sine with a little of its octave, held, gently released."""
    t = np.arange(int((dur + 0.15) * SR)) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    y = np.sin(2 * np.pi * f * t) + 0.18 * np.sin(4 * np.pi * f * t)
    env = np.minimum(1, t / 0.012) * (0.8 + 0.2 * np.exp(-t * 4))
    env *= np.where(t > dur, np.exp(-(t - dur) / 0.05), 1)
    return lowpass(y * env, 420) * vel


def choke(x: np.ndarray, seconds: float) -> np.ndarray:
    y = x[: int(seconds * SR)].copy()
    fade = int(0.03 * SR)
    y[-fade:] *= np.linspace(1, 0, fade)
    return y


def lofi(track: Composed) -> tuple[np.ndarray, str]:
    """32 bars: two bars of keys alone, then the groove; the hook from bar 9; B from bar 17,
    its last bar without the kick; A again."""
    rng = np.random.default_rng(track.seed + 104729)
    minor = bool(track.minor)
    key = int(rng.integers(12))
    bpm = float(rng.integers(68, 87))
    hat_swing = float(rng.uniform(0.56, 0.6))
    kick_swing = float(rng.uniform(0.6, 0.66))  # the kick on a looser grid than the hats
    clock = Clock(bpm, 4, swing=hat_swing)
    kclock = Clock(bpm, 4, swing=kick_swing)
    pool = LOFI_MINOR if minor else LOFI_MAJOR
    a, b = (pool[i] for i in rng.choice(len(pool), 2, replace=False))
    harmony: Harmony = []
    beat = 0.0
    for prog in (a, a, b, a):
        for tok in prog * 2:
            harmony.append((beat, 4, chord(tok, key)))
            beat += 4
    bars = 32
    loop_len = clock.t(bars * 4)
    n = int((loop_len + 4) * SR)
    keys_bus, lead_bus, bass_bus, drum_bus, verb_send = (np.zeros(n) for _ in range(5))

    def j(ms: float) -> float:  # timing looseness
        return rng.normal(0, ms / 1000)

    keys_name = str(rng.choice(["rhodes", "grand"], p=[0.7, 0.3]))
    lead_name = str(rng.choice(["rhodes", "grand"]))
    comp_a, comp_b = (COMP[i] for i in rng.choice(len(COMP), 2, replace=False))
    kick_pat = KICKS[int(rng.integers(len(KICKS)))]
    hat_name = str(rng.choice(list(HATS), p=[0.4, 0.3, 0.1, 0.2]))
    snare_late = rng.uniform(0.014, 0.028)

    # keys: held chords, gently rolled, moving as little as they can
    keys = instrument(keys_name)
    prev = None
    for bar in range(bars):
        comp = comp_b if bar // 8 == 2 else comp_a
        for onset, length, vel in comp:
            lh, prev = lofi_voice(chord_at(harmony, bar * 4), prev)
            for k, m in enumerate(lh + prev):
                v = float(np.clip((vel + rng.normal(0, 0.05)) * 0.6, 0.2, 0.9))
                at = clock.t(bar * 4 + onset) + k * rng.uniform(0.008, 0.018) + j(6)
                keys.play(keys_bus, at, m, v, length * 60 / bpm, release=0.5)

    # the hook: four bars, the same each time it comes round
    lead = instrument(lead_name)
    scale = scale_of(key, minor)
    rhythm_a, rhythm_b = (HOOKS[i] for i in rng.choice(len(HOOKS), 2, replace=False))
    lo, hi = 62, 77  # D4 to F5: the MIDI's tunes sit around B4
    hook_a = hook(rng, harmony[:4], scale, rhythm_a, lo, hi)
    hook_b = hook(rng, harmony[16:20], scale, rhythm_b, lo, hi)
    for start_bar, notes in ((8, hook_a), (12, hook_a), (16, hook_b), (20, hook_b),
                             (24, hook_a), (28, hook_a)):  # fmt: skip
        for beat, length, m in notes:
            at = start_bar * 4 + beat
            v = float(np.clip(0.42 + rng.normal(0, 0.05), 0.25, 0.6))
            lead.play(lead_bus, clock.t(at) + j(8), fit(m, chord_at(harmony, at)), v,
                      length * 60 / bpm, release=0.5)  # fmt: skip

    # bass: the root held, again on the and-of-two when the kick is there
    for start, _length, ch in harmony:
        if start < 8:  # the opening two bars: keys alone
            continue
        root = 36 + (ch.bass - 36) % 12
        if root > 43:
            root -= 12
        hold = 2.4 if 2.5 in kick_pat else 3.6
        mix_in(bass_bus, kclock.t(start) + j(5), sub(root, hold * 60 / bpm, 0.9))
        if 2.5 in kick_pat:
            mix_in(bass_bus, kclock.t(start + 2.5) + j(5), sub(root, 1.3 * 60 / bpm, 0.75))

    # drums: dark short hats, the softest real snare hit set back, a round kick
    hats = [choke(lowpass(highpass(h, 700), 5500, order=4), 0.06)
            for h in hits("Hi-Hat Cymbal/HiHat_[CH]*.wav")]  # fmt: skip
    _ = rng.random(), rng.uniform(170, 200)  # draws the published seeds' tracks were made with
    snares = [lowpass(highpass(x, 120), 3800, order=4)
              for x in hits("Snare Drum, Modern 1/Snare2_HitSN_v3_*.wav")]  # fmt: skip
    taps = [lowpass(x, 1500, order=4) for x in hits("Snare Drum, Modern 1/Snare2_taps*.wav")]
    kick_times = []
    for bar in range(2, bars):  # the first two bars: keys alone
        sparse = bar < 4 or bar == 23  # the way in, and B's last bar
        if not sparse:
            for kb in kick_pat:
                at = kclock.t(bar * 4 + kb) + j(5)
                kick_times.append(at)
                mix_in(drum_bus, at, kick(0.6 if kb == 0 else 0.42))
        for sb in (1, 3):
            s = snares[int(rng.integers(len(snares)))] * 0.9 * rng.uniform(0.85, 1.0)
            at = clock.t(bar * 4 + sb) + snare_late + j(4)
            mix_in(drum_bus, at, s)
            mix_in(verb_send, at, s)
        if not sparse:
            for g in (1.75, 3.25, 3.75):  # ghost taps, now and then
                if rng.random() < 0.18:
                    tap = taps[int(rng.integers(len(taps)))]
                    mix_in(drum_bus, clock.t(bar * 4 + g) + j(6), tap * 0.1)
        for e, w in enumerate(HATS["offbeats"] if sparse else HATS[hat_name]):
            if not w or rng.random() < 0.05:
                continue
            h = hats[int(rng.integers(len(hats)))]
            mix_in(drum_bus, clock.t(bar * 4 + e / 2) + j(9), h * 0.16 * w * rng.uniform(0.8, 1.1))

    _ = rng.integers(2400, 3400)  # a draw the published seeds' tracks were made with
    if keys_name == "rhodes":
        keys_bus = tremolo(keys_bus, rng.uniform(3.5, 5), 0.18)
    keys_bus = lowpass(np.tanh(keys_bus * 1.5) / 1.5, 4000 if keys_name == "rhodes" else 4500)
    lead_bus = echo(lowpass(lead_bus, 4200), 0.75 * 60 / bpm, 0.35, 0.3)
    room = rng.uniform(0.9, 1.4)
    music = reverb(0.9 * keys_bus + 0.85 * lead_bus, room, 0.25, rng, tone=3500)
    drums = lowpass(np.tanh(1.3 * highpass(drum_bus, 35)) / 1.3, 6500) + 0.12 * reverb(
        lowpass(verb_send, 5000), room, 1.0, rng, tone=3000
    )
    mix = (music * sidechain(n, kick_times, 0.15)
           + 0.3 * bass_bus * sidechain(n, kick_times, 0.3) + 0.3 * drums)  # fmt: skip
    info = (f"{NAMES[key]} {'minor' if minor else 'major'}, {bpm:.0f} BPM, {keys_name} keys, "
            f"{lead_name} hook, A {' '.join(a)}, B {' '.join(b)}")  # fmt: skip
    return finish(mix, loop_len, -21), info


# ---------------------------------------------------------------- the tracks

STYLES: dict[str, Callable[[Composed], tuple[np.ndarray, str]]] = {
    "lofi": lofi,
    "soft_piano": piano,
}
TRACKS = {file.removesuffix(".m4a"): track for file, track in COMPOSED}


def main() -> int:
    """All of them, or only those named (`compose_loops.py lofi-simmer`)."""
    wanted = sys.argv[1:] or list(TRACKS)
    unknown = [name for name in wanted if name not in TRACKS]
    if unknown:
        print(f"no such track: {', '.join(unknown)}", file=sys.stderr)
        return 2
    fetch()
    OUT.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        track = TRACKS[name]
        mix, info = STYLES[track.kind](track)
        target = OUT / f"{name}.m4a"
        encode(mix, target)
        print(f"{target.name}: {track.name}, {info}, {len(mix) / SR:.0f}s, "
              f"{target.stat().st_size // 1024} kB")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
