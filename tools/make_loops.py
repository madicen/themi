"""Make the session page's built-in loops (BD5a) with ffmpeg alone: original sounds,
synthesised from code, so they're ours to give away (CC0, see static/audio/LICENCES.md).

    python3 tools/make_loops.py   # writes src/themi_home/web/static/audio/*.m4a

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


def piano(bar: float, decay: float, level: float, strikes_per_bar: int = 1) -> str:
    """An ffmpeg expression: the chords struck each bar (or more), a soft piano-like tone
    (a sine with a quieter octave), fading after each strike."""
    tau = f"mod(t,{bar / strikes_per_bar:.6f})"
    which = f"mod(floor(t/{bar:.6f}),{len(CHORDS)})"
    parts = []
    for c, chord in enumerate(CHORDS):
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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    seconds = 60
    run("brown-noise", ["-f", "lavfi", "-i",
        f"anoisesrc=color=brown:amplitude=0.5:sample_rate={RATE}:duration={seconds}",
        "-af", "lowpass=f=900,volume=0.9"])  # fmt: skip
    run("rain", ["-f", "lavfi", "-i",
        f"anoisesrc=color=pink:amplitude=0.6:sample_rate={RATE}:duration={seconds}",
        "-af", "highpass=f=500,lowpass=f=7000,tremolo=f=0.15:d=0.35,volume=1.6"])  # fmt: skip
    bar = 4 * 60 / 66  # 66 BPM
    bars = 16
    run("soft-piano", ["-f", "lavfi", "-i",
        f"aevalsrc='{piano(bar, 0.9, 0.16)}':s={RATE}:d={bar * bars:.4f}",
        "-af", "lowpass=f=3000,aecho=0.8:0.6:180:0.25"])  # fmt: skip
    bar = 4 * 60 / 80  # 80 BPM
    beat = bar / 4
    kick = f"0.5*sin(2*PI*52*mod(t,{2 * beat:.6f}))*exp(-14*mod(t,{2 * beat:.6f}))"
    hat = f"0.04*(random(0)*2-1)*exp(-45*mod(t+{beat / 2:.6f},{beat:.6f}))"
    keys = piano(bar, 1.4, 0.045, strikes_per_bar=2)
    run("lofi", ["-f", "lavfi", "-i",
        f"aevalsrc='{keys}+{kick}+{hat}':s={RATE}:d={bar * bars:.4f}",
        "-f", "lavfi", "-i",
        f"anoisesrc=color=white:amplitude=0.012:sample_rate={RATE}:duration={bar * bars:.4f}",
        "-filter_complex", MIX])  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
