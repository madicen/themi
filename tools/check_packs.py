"""Fail if code imports a pack it may not (the core refactor, CR10a, CR10b1).

Packs, and what each may import at runtime:
- the core and the standard modules (everything not in a pack): neither pack;
- the Google pack (Gmail and its email features, Calendar and events, Google Tasks, travel
  heads-ups, the Google connectors): not the home pack;
- the home pack (the household: groceries and pantry, recipes and cooking, body double,
  appliances and devices, the Cozyla wall, Safeway, spending, upkeep, notes between
  partners, and those services' connectors): anything (the cookbook uses Google Docs).

A type-only import (inside `if TYPE_CHECKING:`) is allowed: `keys.py` names every pack's
types. The composition root (`themi.app`, and `themi.cli`'s commands for each service) is
exempt, and so are the two Accounts pages (`google_pages`, `connection_pages`), which show
each pack's connections until they're in sections of their own.

Usage: python tools/check_packs.py [src root]   (defaults to src)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# CR10b2: a pack is its own package.
PACKAGES = {"themi_google": "google", "themi_home": "home"}
EXEMPT = {"themi.app", "themi.cli", "themi.web.google_pages", "themi.web.connection_pages"}
MAY_IMPORT = {"core": set(), "google": set(), "home": {"google"}}


def pack_of(module: str) -> str:
    return PACKAGES.get(module.split(".")[0], "core")


def module_name(src: Path, path: Path) -> str:
    return ".".join(path.relative_to(src).with_suffix("").parts).removesuffix(".__init__")


def runtime_imports(path: Path) -> list[tuple[int, str]]:
    """Imports outside `if TYPE_CHECKING:` blocks: (line, module)."""
    tree = ast.parse(path.read_text(), filename=str(path))
    type_only: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and ast.unparse(node.test) in (
            "TYPE_CHECKING",
            "typing.TYPE_CHECKING",
        ):
            type_only |= {id(n) for child in node.body for n in ast.walk(child)}
    found = []
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module in ("themi", "themi.core", "themi.web", "themi.connectors"):
                found += [(node.lineno, f"{node.module}.{a.name}") for a in node.names]
            else:
                found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names]
    return found


def problems(src: Path) -> list[str]:
    out = []
    files = [p for top in ("themi", *PACKAGES) for p in sorted((src / top).rglob("*.py"))]
    for path in files:
        name = module_name(src, path)
        if name in EXEMPT:
            continue
        mine = pack_of(name)
        for line, imported in runtime_imports(path):
            if imported.split(".")[0] not in ("themi", *PACKAGES):
                continue
            theirs = pack_of(imported)
            if theirs != mine and theirs != "core" and theirs not in MAY_IMPORT[mine]:
                rel = path.relative_to(src).as_posix()
                out.append(f"{rel}:{line}: the {mine} code imports the {theirs} pack's {imported}")
    return out


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "src"
    found = problems(src)
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
