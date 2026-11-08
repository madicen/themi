"""An instance's choices: its template and modules (CR5a).

`themi.toml` holds choices and plain settings; secrets stay in `.env`. With no file,
Themi is the family template, built from today's environment variables, so an existing
install changes nothing.

    template = "family"
    modules = ["-safeway", "+travel"]   # leave one out, add one

    [workspace]                          # CR9
    name = "The Madicens"

    [module.gmail]                       # CR5b: a module's own settings
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from themi.modules import Module, ModuleSetup
from themi.modules.settings import SettingsProblem
from themi.settings import Settings, SettingsError

ENTRY_POINTS = "themi.modules"
DEFAULT_PATHS = (Path("/data/themi.toml"), Path("themi.toml"))


@dataclass(frozen=True)
class RoleSpec:
    """CR9: a role a template's members can have: whether it's an admin's, and which
    modules' tools it may use ("*": every module's)."""

    name: str
    admin: bool = False
    modules: tuple[str, ...] = ("*",)

    def allowed(self) -> set[str] | None:
        """The modules this role may use, or None for all of them."""
        return None if "*" in self.modules else set(self.modules)


@dataclass(frozen=True)
class Template:
    name: str
    modules: tuple[str, ...]
    persona: str = ""  # CR8a: the system prompt's opening
    prompt: dict[str, str] = field(default_factory=dict)  # rewordings by fragment key
    roles: dict[str, RoleSpec] = field(default_factory=dict)  # CR9: by role name
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)  # CR12: tool rewordings
    groups: dict[str, str] = field(default_factory=dict)  # CR12: group descriptions


@dataclass(frozen=True)
class InstanceConfig:
    template: str = "family"
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    workspace: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    path: Path | None = None  # where it was read from; None for the default


def config_path(env: dict[str, str] | None = None) -> Path | None:
    env = dict(os.environ) if env is None else env
    if named := env.get("THEMI_CONFIG", "").strip():
        path = Path(named)
        if not path.exists():
            raise SettingsError(
                f"Themi can't start:\n  - THEMI_CONFIG names {path}, which isn't there"
            )
        return path
    return next((p for p in DEFAULT_PATHS if p.exists()), None)


def load_config(path: Path | None) -> InstanceConfig:
    if path is None:
        return InstanceConfig()
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SettingsError(f"Themi can't start:\n  - {path} can't be read: {exc}") from exc
    return parse_config(data, path)


def parse_config(data: dict[str, Any], path: Path | None = None) -> InstanceConfig:
    problems = []
    unknown = set(data) - {"template", "modules", "workspace", "module"}
    if unknown:
        problems.append(f"{', '.join(sorted(unknown))} isn't something themi.toml sets")
    template = data.get("template", "family")
    if not isinstance(template, str) or not template:
        problems.append('template is a name, like "family"')
    changes = data.get("modules", [])
    added, removed = [], []
    if not isinstance(changes, list):
        changes = [changes]
    for change in changes:
        if isinstance(change, str) and change[:1] in "+-" and len(change) > 1:
            (added if change[0] == "+" else removed).append(change[1:])
        else:
            problems.append(f'modules lists "+name" or "-name", not {change!r}')
    raw_sections = data.get("module", {})
    sections: dict[str, dict[str, Any]] = {}
    if isinstance(raw_sections, dict):
        for name, value in raw_sections.items():
            if isinstance(value, dict):
                sections[name] = value
            else:
                problems.append(f"[module.{name}] is a section of settings")
    workspace = data.get("workspace", {})
    if problems:
        where = f" in {path}" if path else ""
        raise SettingsError(f"Themi can't start{where}:\n  - " + "\n  - ".join(problems))
    return InstanceConfig(template, tuple(added), tuple(removed), dict(workspace), sections, path)


def available_modules() -> dict[str, type[Module]]:
    """Every module installed in this Python, by name."""
    found: dict[str, type[Module]] = {}
    for entry in entry_points(group=ENTRY_POINTS):
        cls = entry.load()
        if getattr(cls, "name", None) != entry.name:
            raise SettingsError(f"module entry {entry.name} loads a module named {cls.name}")
        found[entry.name] = cls
    return found


def load_template(name: str) -> Template:
    try:
        text = resources.files("themi.templates").joinpath(f"{name}.toml").read_text()
    except FileNotFoundError as exc:
        raise SettingsError(f"Themi can't start:\n  - there's no template called {name}") from exc
    data = tomllib.loads(text)
    return Template(
        data.get("name", name),
        tuple(data.get("modules", [])),
        data.get("persona", "").lstrip("\n"),
        dict(data.get("prompt", {})),
        {
            role: RoleSpec(role, bool(spec.get("admin", False)), tuple(spec.get("modules", ["*"])))
            for role, spec in data.get("roles", {}).items()
        },
        dict(data.get("tools", {})),
        {name: str(g.get("description", "")) for name, g in data.get("groups", {}).items()},
    )


def resolve_modules(
    config: InstanceConfig,
    settings: Settings,
    known: dict[str, type[Module]] | None = None,
) -> list[Module]:
    """The template's modules with the file's changes, each built from the settings.

    A template module that isn't set up (`build` gives None) is left out quietly, and so is
    anything of the template's that then lacks a module it requires: that's a connector
    nobody has configured. A module the file adds must be known and set up, and must have
    what it requires; a module the file removes mustn't be needed by another. Otherwise
    Themi says so and stops."""
    known = available_modules() if known is None else known
    template = load_template(config.template)
    problems = []
    for name in (*config.added, *config.removed):
        if name not in known:
            problems.append(f"there's no module called {name}")
    for name in template.modules:
        if name not in known:
            problems.append(f"the {template.name} template names {name}, which isn't installed")
    for name in config.sections:  # CR5b: a section is a module's own settings
        if name not in known:
            problems.append(f"[module.{name}]: there's no module called {name}")
        elif known[name].settings is None:
            problems.append(f"[module.{name}]: {name} has no settings of its own")
    if problems:
        raise SettingsError("Themi can't start:\n  - " + "\n  - ".join(problems))
    names = [n for n in template.modules if n not in config.removed]
    names += [n for n in config.added if n not in names]
    shared: dict[str, object] = {}  # one store of shared objects for every module
    built: dict[str, Module] = {}
    for name in names:
        setup = ModuleSetup(
            settings, config.sections.get(name), shared, module=name, sections=config.sections
        )
        try:
            module = known[name].build(setup)
        except SettingsProblem as exc:  # CR5b: its settings, in the person's words
            problems.extend(exc.problems)
            continue
        if module is None and name in config.added:
            problems.append(f"{name} is added in themi.toml, but its settings aren't there")
        elif module is not None:
            built[name] = module
    changed = True
    while changed:  # leave out what requires a module that isn't set up
        changed = False
        for name, module in list(built.items()):
            missing = [r for r in module.requires if r not in built]
            if not missing:
                continue
            removed = [r for r in missing if r in config.removed]
            if removed:
                problems.append(f"{name} needs {', '.join(removed)}, which themi.toml removes")
            elif name in config.added:
                problems.append(f"{name} needs {', '.join(missing)}, which isn't set up")
            del built[name]
            changed = True
    if problems:
        raise SettingsError("Themi can't start:\n  - " + "\n  - ".join(sorted(set(problems))))
    return [built[n] for n in names if n in built]
