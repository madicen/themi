"""Make Themi's trills (WA4) with ffmpeg alone: original sounds, synthesised from code, so
they're ours to give away (CC0, see static/audio/LICENCES.md).

    python3 tools/make_trills.py [name ...]   # writes src/themi_home/web/static/audio/trills/*.m4a

What each trill is (its notes, pitches and vibrato) lives in `themi_home/trills.py`. Each is
mono AAC, under 1.5 seconds. Nothing random: the same notes make the same file.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parents[1] / "src"
OUT = SRC / "themi_home" / "web" / "static" / "audio" / "trills"
RATE = 48000
LEVEL = 0.55  # each note's peak, before its harmonic: about -5 dB at the loudest
TAIL = 0.08  # seconds of quiet after the last note

sys.path.insert(0, str(SRC))
from themi_home.trills import TRILLS, Note, length  # noqa: E402


def phase(n: Note, tau: str) -> str:
    """The note's phase at `tau` seconds in: the integral of its swept pitch plus vibrato,
    so the sweep and the trill stay smooth."""
    k = n.f1 / n.f0
    sweep = f"{n.f0 * n.dur / math.log(k):.6f}*(pow({k:.6f},{tau}/{n.dur:.4f})-1)"
    wobble = f"{n.depth / (2 * math.pi * n.rate):.6f}*(1-cos({2 * math.pi * n.rate:.6f}*{tau}))"
    return f"2*PI*({sweep}+{wobble})"


def expression(name: str) -> str:
    parts = []
    for n in TRILLS[name]:
        tau = f"(t-{n.at:.4f})"
        envelope = f"min({tau}/0.02,1)*exp(-2.5*{tau}/{n.dur:.4f})*(1-{tau}/{n.dur:.4f})"
        tone = f"(sin({phase(n, tau)})+0.18*sin(2*{phase(n, tau)}))"
        parts.append(f"if(between(t,{n.at:.4f},{n.at + n.dur:.4f}),{LEVEL}*{envelope}*{tone},0)")
    return "+".join(parts)


def run(name: str) -> None:
    target = OUT / f"{name}.m4a"
    seconds = f"{length(name) + TAIL:.3f}"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
           "-i", f"aevalsrc='{expression(name)}':s={RATE}:d={seconds}",
           "-ac", "1", "-ar", str(RATE), "-c:a", "aac", "-b:a", "64k",
           "-movflags", "+faststart", str(target)]  # fmt: skip
    subprocess.run(cmd, check=True)
    print(f"{target.name}: {target.stat().st_size // 1024} kB")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:] or list(TRILLS)
    unknown = [name for name in wanted if name not in TRILLS]
    if unknown:
        print(f"no such trill: {', '.join(unknown)}", file=sys.stderr)
        return 2
    for name in wanted:
        run(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
