"""Fail unless coverage meets the plan's gates (run after `coverage run`).

At least 90% on the AI layer, the outbox, the PDA shield, the trust tiers and
the energy engine, and at least 75% overall. Lines and branches both count.

Usage: python tools/check_coverage.py   (reads the .coverage data file)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

OVERALL = 75.0
GATES = {
    "themi.ai": ("src/themi/ai/", 90.0),
    "themi.channels.outbox": ("src/themi/channels/outbox.py", 90.0),
    "themi.channels.pda": ("src/themi/channels/pda.py", 90.0),
    "themi.autonomy": ("src/themi/autonomy/", 90.0),
    "themi.energy": ("src/themi/energy/", 90.0),
}


def percent(files: dict[str, dict], prefix: str) -> float | None:
    covered = total = 0
    for name, data in files.items():
        if name.replace("\\", "/").startswith(prefix):
            summary = data["summary"]
            covered += summary["covered_lines"] + summary.get("covered_branches", 0)
            total += summary["num_statements"] + summary.get("num_branches", 0)
    return 100.0 * covered / total if total else None


def check(report: dict) -> list[str]:
    """The gates that fail, as lines to print (empty when all pass)."""
    problems = []
    overall = report["totals"]["percent_covered"]
    if overall < OVERALL:
        problems.append(f"overall {overall:.1f}% < {OVERALL:.0f}%")
    for name, (prefix, floor) in GATES.items():
        value = percent(report["files"], prefix)
        if value is None:
            problems.append(f"{name}: no coverage data (is {prefix} measured?)")
        elif value < floor:
            problems.append(f"{name} {value:.1f}% < {floor:.0f}%")
    return problems


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "coverage.json"
        subprocess.run([sys.executable, "-m", "coverage", "json", "-q", "-o", str(out)], check=True)
        report = json.loads(out.read_text())
    problems = check(report)
    for name, (prefix, _) in GATES.items():
        value = percent(report["files"], prefix)
        print(f"{name:24} {value:5.1f}%" if value is not None else f"{name:24}   n/a")
    print(f"{'overall':24} {report['totals']['percent_covered']:5.1f}%")
    if problems:
        print("Coverage gates failed:\n  - " + "\n  - ".join(problems))
        return 1
    print("Coverage gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
