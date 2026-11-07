"""Fail if code outside the home pack imports it at runtime (the core refactor, CR10a).

The home pack is the family's household features: groceries and the pantry, recipes and
cooking, the body double, the appliances, the Cozyla wall, Safeway, spending, upkeep and
passing notes between partners. Everything else (the core, the standard modules every
template uses, the connectors) must work without it, so it may not import a home file at
runtime. A type-only import (inside `if TYPE_CHECKING:`) is allowed until CR10b splits
`keys.py` by pack. The composition root (`themi.app`, and `themi.cli`'s commands for each
service) is exempt; the home pack's own website pages are in the pack.

Usage: python tools/check_packs.py [src root]   (defaults to src)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HOME_CORE = {
    "appliances", "body_double", "body_double_guided", "body_double_modes", "body_double_music",
    "body_double_scene", "buying", "calls", "chore_chart", "cookbook", "cookbook_save",
    "cooking", "cooking_timers", "cozyla_chores", "cozyla_lists", "cozyla_routines",
    "cozyla_todos", "dishwasher", "feeders", "groceries", "home_modules", "keep_groceries",
    "laundry", "liaison", "litter_box", "maintenance", "meals", "music", "pantry", "quantities",
    "recipe_groceries", "recipe_ideas", "recipes", "routines_wall", "safeway", "spending",
    "step_images", "vacuum", "web_recipes", "which_list",
}  # fmt: skip
HOME_WEB = {
    "grocery_pages", "maintenance_pages", "recipe_pages", "safeway_pages", "session_pages",
    "spending_pages",
}  # fmt: skip
HOME = {f"themi.core.{m}" for m in HOME_CORE} | {f"themi.web.{m}" for m in HOME_WEB}
EXEMPT = {"themi.app", "themi.cli"}  # the composition root, and the commands for each service


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
            if node.module == "themi.core" or node.module == "themi.web":
                found += [(node.lineno, f"{node.module}.{a.name}") for a in node.names]
            else:
                found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names]
    return found


def problems(src: Path) -> list[str]:
    out = []
    for path in sorted((src / "themi").rglob("*.py")):
        name = module_name(src, path)
        if name in HOME or name in EXEMPT:
            continue
        for line, imported in runtime_imports(path):
            if imported in HOME or any(imported.startswith(h + ".") for h in HOME):
                rel = path.relative_to(src).as_posix()
                out.append(f"{rel}:{line}: imports the home pack's {imported} at runtime")
    return out


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else REPO_ROOT / "src"
    found = problems(src)
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
