"""Make the session page's built-in loops (BD5a) with ffmpeg alone: original sounds,
synthesised from code, so they're ours to give away (CC0, see static/audio/LICENCES.md).

    python3 tools/make_loops.py [name ...]   # writes src/themi_home/web/static/audio/*.m4a

Each is mono AAC (plays on every phone browser), about a minute, slow (60-90 BPM) and
made to loop: chord loops are whole bars, noise loops have nothing to line up.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).parents[1] / "src" / "themi_home" / "web" / "static" / "audio"
RATE = 48000
MIX = "[0]lowpass=f=2600[a];[1]highpass=f=3000[c];[a][c]amix=inputs=2:normalize=0"


def note(name: str) -> float:
    names = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    semis = names[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 261.6256 * 2 ** (semis / 12)


# Cmaj7, Am7, Fmaj7, G6: soft, unresolved, easy to sit with
CHORDS = [
    ["C3", "E4", "G4", "B4"],
    ["A2", "C4", "E4", "G4"],
    ["F2", "A3", "C4", "E4"],
    ["G2", "B3", "D4", "E4"],
]
# CK14: more of each kind, so the cook screen's Next has somewhere to go
SIMMER = [  # Dm9, G13, Cmaj9, Am9
    ["D3", "F4", "A4", "E5"],
    ["G2", "F4", "B4", "E5"],
    ["C3", "E4", "B4", "D5"],
    ["A2", "G4", "C5", "B4"],
]
WINDOW = [  # Fmaj7, Em7, Dm7, Cmaj7
    ["F2", "A3", "E4", "C5"],
    ["E2", "G3", "D4", "B4"],
    ["D2", "F3", "C4", "A4"],
    ["C2", "E3", "B3", "G4"],
]
SUPPER = [  # Am9, Dm9, Gmaj7, Cmaj7
    ["A2", "C4", "G4", "B4"],
    ["D3", "F4", "C5", "E5"],
    ["G2", "B3", "F#4", "D5"],
    ["C3", "E4", "B4", "G4"],
]
BREAD = [  # D#maj7, Cm7, G#maj7, A#6
    ["D#3", "G4", "A#4", "D5"],
    ["C3", "D#4", "G4", "A#4"],
    ["G#2", "C4", "D#4", "G4"],
    ["A#2", "D4", "F4", "G4"],
]
EVENING = [  # Em9, Cmaj7, G, D/F#
    ["E3", "G4", "B4", "F#5"],
    ["C3", "E4", "G4", "B4"],
    ["G2", "B3", "D4", "G4"],
    ["F#2", "A3", "D4", "F#4"],
]
SNOWFALL = [  # Dmaj7, Bm7, Gmaj7, A
    ["D3", "F#4", "A4", "C#5"],
    ["B2", "D4", "F#4", "A4"],
    ["G2", "B3", "D4", "F#4"],
    ["A2", "C#4", "E4", "A4"],
]
WALTZ = [  # Fmaj7, Dm7, Gm7, C
    ["F3", "A4", "C5", "E5"],
    ["D3", "F4", "A4", "C5"],
    ["G3", "A#4", "D5", "F5"],
    ["C3", "E4", "G4", "C5"],
]


def piano(bar: float, decay: float, level: float, strikes_per_bar: int = 1,
          chords: list[list[str]] = CHORDS) -> str:  # fmt: skip
    """An ffmpeg expression: the chords struck each bar (or more), a soft piano-like tone
    (a sine with a quieter octave), fading after each strike."""
    tau = f"mod(t,{bar / strikes_per_bar:.6f})"
    which = f"mod(floor(t/{bar:.6f}),{len(chords)})"
    parts = []
    for c, chord in enumerate(chords):
        tone = "+".join(f"sin(2*PI*{note(n):.3f}*t)+0.25*sin(4*PI*{note(n):.3f}*t)" for n in chord)
        parts.append((c, tone))
    expr = "0"
    for c, tone in reversed(parts):
        expr = f"if(eq({which},{c}),{tone},{expr})"
    return f"{level}*({expr})*exp(-{decay}*{tau})*(1-exp(-60*{tau}))"


def run(name: str, args: list[str]) -> None:
    target = OUT / f"{name}.m4a"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args, "-ac", "1", "-ar", str(RATE),
           "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(target)]  # fmt: skip
    subprocess.run(cmd, check=True)
    print(f"{target.name}: {target.stat().st_size // 1024} kB")


def noise(color: str, amplitude: float, filters: str, seconds: int = 60) -> list[str]:
    return ["-f", "lavfi", "-i",
            f"anoisesrc=color={color}:amplitude={amplitude}:sample_rate={RATE}:duration={seconds}",
            "-af", filters]  # fmt: skip


def keys_only(bpm: int, chords: list[list[str]], decay: float, level: float, echo: str,
              beats: int = 4, strikes: int = 1, bars: int = 16) -> list[str]:  # fmt: skip
    bar = beats * 60 / bpm
    return ["-f", "lavfi", "-i",
            f"aevalsrc='{piano(bar, decay, level, strikes, chords)}':s={RATE}:d={bar * bars:.4f}",
            "-af", f"lowpass=f=3000,{echo}"]  # fmt: skip


def lofi(bpm: int, chords: list[list[str]], strikes: int = 2, crackle: float = 0.012,
         bars: int = 16) -> list[str]:  # fmt: skip
    bar = 4 * 60 / bpm
    beat = bar / 4
    kick = f"0.5*sin(2*PI*52*mod(t,{2 * beat:.6f}))*exp(-14*mod(t,{2 * beat:.6f}))"
    hat = f"0.04*(random(0)*2-1)*exp(-45*mod(t+{beat / 2:.6f},{beat:.6f}))"
    keys = piano(bar, 1.4, 0.045, strikes_per_bar=strikes, chords=chords)
    length = f"{bar * bars:.4f}"
    return ["-f", "lavfi", "-i",
            f"aevalsrc='{keys}+{kick}+{hat}':s={RATE}:d={length}",
            "-f", "lavfi", "-i",
            f"anoisesrc=color=white:amplitude={crackle}:sample_rate={RATE}:duration={length}",
            "-filter_complex", MIX]  # fmt: skip


TRACKS = {
    "brown-noise": noise("brown", 0.5, "lowpass=f=900,volume=0.9"),
    "brown-noise-hum": noise("brown", 0.5, "lowpass=f=420,volume=1.3"),
    "rain": noise("pink", 0.6, "highpass=f=500,lowpass=f=7000,tremolo=f=0.15:d=0.35,volume=1.6"),
    "rain-drizzle": noise(
        "white", 0.35, "highpass=f=1800,lowpass=f=9000,tremolo=f=0.4:d=0.25,volume=0.9"
    ),
    "rain-roof": noise(
        "pink", 0.6, "highpass=f=200,lowpass=f=2400,tremolo=f=0.1:d=0.45,volume=1.8"
    ),
    "soft-piano": keys_only(66, CHORDS, 0.9, 0.16, "aecho=0.8:0.6:180:0.25"),
    "soft-piano-evening": keys_only(60, EVENING, 0.7, 0.15, "aecho=0.8:0.7:260:0.3"),
    "soft-piano-snowfall": keys_only(
        70, SNOWFALL, 1.1, 0.14, "aecho=0.8:0.5:120|360:0.25|0.15", strikes=2
    ),
    "soft-piano-waltz": keys_only(
        84, WALTZ, 1.6, 0.13, "aecho=0.8:0.6:200:0.2", beats=3, strikes=3, bars=24
    ),
    "lofi": lofi(80, CHORDS),
    "lofi-simmer": lofi(72, SIMMER),
    "lofi-window": lofi(84, WINDOW, crackle=0.008),
    "lofi-supper": lofi(76, SUPPER, strikes=1, crackle=0.015),
    "lofi-bread": lofi(82, BREAD),
}


def main() -> int:
    """All of them, or only those named (`make_loops.py lofi-simmer rain-roof`), so a new
    track doesn't remake the others (the noise is random each time)."""
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or list(TRACKS)
    unknown = [name for name in wanted if name not in TRACKS]
    if unknown:
        print(f"no such track: {', '.join(unknown)}", file=sys.stderr)
        return 2
    for name in wanted:
        run(name, TRACKS[name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
