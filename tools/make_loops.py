"""Make the session page's built-in loops (BD5a) with ffmpeg alone: original sounds,
synthesised from code, so they're ours to give away (CC0, see static/audio/LICENCES.md).

    python3 tools/make_loops.py [name ...]   # writes src/themi_home/web/static/audio/*.m4a

Each is mono AAC (plays on every phone browser), about a minute, slow (60-90 BPM) and
made to loop: chord loops are whole bars, noise loops have nothing to line up. CK15a: what
each track is (its chords, tempo, noise) lives in `themi_home/music_mix.py`, which the cook
screen's player reads too.

F48a: the built-ins made here are rain and brown noise. Lofi and soft piano are composed on
real instruments by `compose_loops.py`; a musical mix still renders here as mix.js plays it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parents[1] / "src"
OUT = SRC / "themi_home" / "web" / "static" / "audio"
RATE = 48000

sys.path.insert(0, str(SRC))
from themi_home.music_mix import BUILT_IN, CHORDS, Mix, Noise  # noqa: E402


def note(name: str) -> float:
    names = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    semis = names[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 261.6256 * 2 ** (semis / 12)


def piano(bar: float, decay: float, level: float, strikes_per_bar: int,
          chords: list[tuple[str, ...]]) -> str:  # fmt: skip
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


def noise_filters(n: Noise) -> str:
    return ",".join(f for f in (
        f"highpass=f={n.highpass}" if n.highpass else "",
        f"lowpass=f={n.lowpass}" if n.lowpass else "",
        f"tremolo=f={n.swell_hz}:d={n.swell_depth}" if n.swell_hz else "",
        f"volume={n.gain}" if n.gain != 1 else "",
    ) if f)  # fmt: skip


def noise_source(n: Noise, seconds: float | str) -> str:
    return (
        f"anoisesrc=color={n.color}:amplitude={n.amplitude}:sample_rate={RATE}:duration={seconds}"
    )


def args(mix: Mix) -> list[str]:
    """ffmpeg's inputs and filters for a mix (CK15a: the settings live in music_mix.py)."""
    if not mix.chords:  # noise alone: rain, brown noise
        assert mix.noise is not None
        return ["-f", "lavfi", "-i", noise_source(mix.noise, mix.seconds),
                "-af", noise_filters(mix.noise)]  # fmt: skip
    bar = mix.bar_seconds
    length = f"{bar * mix.bars:.4f}"
    chords = [CHORDS[c] for c in mix.chords]
    expr = piano(bar, mix.decay, mix.level, mix.strikes, chords)
    if mix.beat:
        beat = bar / mix.beats
        kick = f"0.5*sin(2*PI*52*mod(t,{2 * beat:.6f}))*exp(-14*mod(t,{2 * beat:.6f}))"
        hat = f"0.04*(random(0)*2-1)*exp(-45*mod(t+{beat / 2:.6f},{beat:.6f}))"
        expr = f"{expr}+{kick}+{hat}"
    keys = ["-f", "lavfi", "-i", f"aevalsrc='{expr}':s={RATE}:d={length}"]
    echo = ""
    if mix.echoes:
        delays = "|".join(str(d) for d, _ in mix.echoes)
        louds = "|".join(str(v) for _, v in mix.echoes)
        echo = f",aecho=0.8:{mix.echo_out}:{delays}:{louds}"
    if mix.noise is None:
        return [*keys, "-af", f"lowpass=f={mix.tone}{echo}"]
    crackle = noise_filters(mix.noise)
    mixdown = (f"[0]lowpass=f={mix.tone}{echo}[a];[1]{crackle}[c];"
               "[a][c]amix=inputs=2:normalize=0")  # fmt: skip
    return [*keys, "-f", "lavfi", "-i", noise_source(mix.noise, length),
            "-filter_complex", mixdown]  # fmt: skip


TRACKS = {file.removesuffix(".m4a"): args(mix) for file, mix in BUILT_IN}


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
