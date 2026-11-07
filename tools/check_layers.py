"""Fail if Themi's core imports a feature or a connector (the core refactor, CR1).

Core is the code every Themi needs, whatever its template: the packages and files in
CORE below. It may import other core code, and the few parts of `themi.core` that are
core in all but location (CORE_IN_FEATURES: the service hub, the tool registry, the prompt
builder). It may not import any other `themi.core.*`, `themi.connectors.*`, `themi.energy`,
`themi.web` or `themi.app`. The composition root (`themi.app`, `themi.runtime`,
`themi.cli`) and the website are not checked: they wire everything together.

KNOWN lists the breaches that exist today, each with the prompt that removes it. A new
breach fails; so does a KNOWN entry that's gone, so the list can only shrink.

Usage: python tools/check_layers.py [src root]   (defaults to src)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CORE_PACKAGES = ("accounts", "ai", "autonomy", "backup", "channels", "modules", "storage")
CORE_FILES = (
    "clock.py",
    "http.py",
    "localtime.py",
    "logs.py",
    "scheduler.py",
    "settings.py",
    "updates.py",
)
CORE_IN_FEATURES = {
    "themi.web.kit",  # the website's shell (CR4)
    "themi.core.kept_pictures",
    "themi.core.naming",
    "themi.core.prompts",
    "themi.core.services",
    "themi.core.tools",
}
OUTSIDE = ("themi.core", "themi.connectors", "themi.energy", "themi.web", "themi.app")

# (file relative to the src root, imported module): the prompt that removes it.
KNOWN: dict[tuple[str, str], str] = {}  # none left after CR5b


def core_files(src: Path) -> list[Path]:
    root = src / "themi"
    found = [p for pkg in CORE_PACKAGES for p in sorted((root / pkg).rglob("*.py"))]
    found += [root / name for name in CORE_FILES if (root / name).exists()]
    return found


def imports_of(path: Path) -> list[tuple[int, str]]:
    out = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            out.extend((node.lineno, alias.name) for alias in node.names)
    return out


def is_outside(module: str) -> bool:
    if module in CORE_IN_FEATURES:
        return False
    return any(module == o or module.startswith(o + ".") for o in OUTSIDE)


def breaches(src: Path) -> list[tuple[str, int, str]]:
    """Every core import of a feature: (file relative to src, line, module)."""
    found = []
    for path in core_files(src):
        rel = path.relative_to(src).as_posix()
        for line, module in imports_of(path):
            if is_outside(module):
                found.append((rel, line, module))
    return found


def problems(src: Path, known: dict[tuple[str, str], str] = KNOWN) -> list[str]:
    found = breaches(src)
    out = [
        f"{rel}:{line}: core imports {module}; reach it through a module instead"
        for rel, line, module in found
        if (rel, module) not in known
    ]
    seen = {(rel, module) for rel, _, module in found}
    out += [
        f"{rel}: no longer imports {module}; remove it from KNOWN in tools/check_layers.py"
        for rel, module in known
        if (rel, module) not in seen
    ]
    return out


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "src"
    found = problems(src)
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
