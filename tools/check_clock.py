"""Fail if code outside `themi.clock` reads the wall clock directly.

Flags calls such as `datetime.now()`, `datetime.utcnow()`, `date.today()`,
`datetime.datetime.now()` and `time.time()`. `time.monotonic()` stays allowed
for measuring durations.

Usage: python tools/check_clock.py [paths...]   (defaults to src/themi)
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_FILES = {REPO_ROOT / "src/themi/clock.py"}

# (object name, attribute) pairs that read the wall clock.
FORBIDDEN = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
    ("time", "time_ns"),
}


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def violations_in_source(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        owner = _dotted(node.func.value)
        if owner is None:
            continue
        # `datetime.datetime.now()` -> owner "datetime.datetime", last part "datetime"
        if (owner.rsplit(".", 1)[-1], node.func.attr) in FORBIDDEN:
            found.append((node.lineno, f"{owner}.{node.func.attr}()"))
    return found


def _python_files(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))
        elif path.suffix == ".py":
            yield path


def find_violations(paths: Iterable[Path], allowed: set[Path] | None = None) -> list[str]:
    allowed = ALLOWED_FILES if allowed is None else allowed
    allowed_resolved = {p.resolve() for p in allowed}
    problems = []
    for file in _python_files(paths):
        if file.resolve() in allowed_resolved:
            continue
        for lineno, call in violations_in_source(file.read_text(), str(file)):
            problems.append(f"{file}:{lineno}: {call} — use themi.clock.now() instead")
    return problems


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or [REPO_ROOT / "src/themi"]
    problems = find_violations(paths)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
