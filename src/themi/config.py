"""An instance's choices: its template and modules (CR5a).

`themi.toml` holds choices and plain settings; secrets stay in `.env`. With no file,
Themi is the family template, built from today's environment variables, so an existing
install changes nothing.

    template = "family"
    modules = ["-safeway", "+travel"]   # leave one out, add one

    [workspace]                          # CR9
    name = "The Madicens"

    [module.gmail]                       # CR5b: a module's own settings

    [core]                               # SP2: the core's settings the website sets
    public_url = "https://themi.example.ts.net"

SP2: Themi writes this file itself when an admin changes something on the Modules page
(`write_config`), next to the database unless it was read from somewhere else.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING, Any

from themi.modules import Module, ModuleSetup, StartReport
from themi.modules.settings import SettingsProblem
from themi.settings import Settings, SettingsError

if TYPE_CHECKING:
    from themi.core.tools import ToolGroup
    from themi.storage.secrets import Secret

ENTRY_POINTS = "themi.modules"
DEFAULT_PATHS = (Path("/data/themi.toml"), Path("themi.toml"))
CORE_KEYS = {"public_url"}  # SP2: the core settings themi.toml may hold


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
    core: dict[str, Any] = field(default_factory=dict)  # SP2: public_url


def config_path(env: dict[str, str] | None = None) -> Path | None:
    env = dict(os.environ) if env is None else env
    if named := env.get("THEMI_CONFIG", "").strip():
        path = Path(named)
        if not path.exists():
            raise SettingsError(
                f"Themi can't start:\n  - THEMI_CONFIG names {path}, which isn't there"
            )
        return path
    beside = beside_database(env)
    return next((p for p in (beside, *DEFAULT_PATHS) if p.exists()), None)


def beside_database(env: dict[str, str] | None = None) -> Path:
    """SP2: themi.toml next to the database (/data/themi.toml in the container), where
    Themi writes it when nothing says otherwise."""
    env = dict(os.environ) if env is None else env
    return Path(env.get("THEMI_DB_PATH", "").strip() or "data/themi.db").parent / "themi.toml"


def write_path(config: InstanceConfig, env: dict[str, str] | None = None) -> Path:
    """Where the Modules page writes: where the config was read from, else next to the
    database."""
    return config.path or beside_database(env)


def as_toml(config: InstanceConfig) -> str:
    """The config as themi.toml, in the order people read it. Secrets are never here."""
    lines = [
        "# What this Themi is made of. Themi writes this file when an admin changes something",
        "# on the Modules page; secrets are kept encrypted in the database instead.",
        f"template = {json.dumps(config.template)}",
    ]
    changes = [f"+{n}" for n in config.added] + [f"-{n}" for n in config.removed]
    if changes:
        lines.append(f"modules = {json.dumps(changes)}")
    for title, table in (("core", config.core), ("workspace", config.workspace)):
        if table:
            lines += ["", f"[{title}]"]
            lines += [f"{key} = {_toml_value(value)}" for key, value in table.items()]
    for name, values in config.sections.items():
        if values:
            lines += ["", f"[module.{name}]"]
            lines += [f"{key} = {_toml_value(value)}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value))  # a TOML basic string is JSON's string


def write_config(config: InstanceConfig, path: Path) -> None:
    """Write themi.toml whole or not at all: a temporary file beside it, flushed to disk,
    then renamed over it. A crash leaves the old file (and perhaps a stray temporary)."""
    text = as_toml(config)
    parse_config(tomllib.loads(text), path)  # never write a file Themi couldn't read back
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    with open(temp, "w") as out:
        out.write(text)
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


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
    unknown = set(data) - {"template", "modules", "workspace", "module", "core"}
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
    core = data.get("core", {})
    if not isinstance(core, dict):
        problems.append("[core] is a section of settings")
        core = {}
    elif unknown_core := set(core) - CORE_KEYS:
        problems.append(f"[core] has {', '.join(sorted(unknown_core))}, which it doesn't set")
    if problems:
        where = f" in {path}" if path else ""
        raise SettingsError(f"Themi can't start{where}:\n  - " + "\n  - ".join(problems))
    return InstanceConfig(
        template, tuple(added), tuple(removed), dict(workspace), sections, path, dict(core)
    )


def available_modules() -> dict[str, type[Module]]:
    """Every module installed in this Python, by name."""
    found: dict[str, type[Module]] = {}
    for entry in entry_points(group=ENTRY_POINTS):
        cls = entry.load()
        if getattr(cls, "name", None) != entry.name:
            raise SettingsError(f"module entry {entry.name} loads a module named {cls.name}")
        found[entry.name] = cls
    return found


TEMPLATE_ENTRY_POINTS = "themi.templates"


def template_packages() -> dict[str, str]:
    """CR10b2: each installed template's package, by name: a pack ships its own (the
    family's is the home pack's), through the `themi.templates` entry points."""
    return {e.name: e.value for e in entry_points(group=TEMPLATE_ENTRY_POINTS)}


def load_template(name: str) -> Template:
    package = template_packages().get(name)
    if package is None:
        raise SettingsError(f"Themi can't start:\n  - there's no template called {name}")
    text = resources.files(package).joinpath(f"{name}.toml").read_text()
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
    given: dict[str, Module] | None = None,
    stored: dict[str, dict[str, Secret]] | None = None,
) -> list[Module]:
    """The template's modules with the file's changes, each built from the settings.

    A template module that isn't set up (`build` gives None) is left out quietly, and so is
    anything of the template's that then lacks a module it requires: that's a connector
    nobody has configured. A module the file adds must be known and set up, and must have
    what it requires; a module the file removes mustn't be needed by another. Otherwise
    Themi says so and stops. `themi run` uses `resolve_start` instead (SP1), which leaves
    such a module off and starts.
    `given`: modules already built, by name (the simulator's, on its fakes); one not given
    isn't set up."""
    modules, report = _resolve(config, settings, known, given, {}, stored, tolerant=False)
    if report.problems:
        raise SettingsError("Themi can't start:\n  - " + "\n  - ".join(report.problems))
    return modules


def resolve_start(
    config: InstanceConfig,
    settings: Settings,
    known: dict[str, type[Module]] | None = None,
    given: dict[str, Module] | None = None,
    unavailable: dict[str, str] | None = None,
    stored: dict[str, dict[str, Secret]] | None = None,
) -> tuple[list[Module], StartReport]:
    """SP1: as `resolve_modules`, but a module's problem leaves it (and what needs it) off
    and is said in the report, and Themi starts. Only a problem with themi.toml itself (a
    module or template that isn't installed, a section for nothing) still stops it.
    `unavailable`: modules the runner knows can't run here, with why (Telegram with no
    token). `stored`: the secrets kept on the Modules page, by module and field (SP2)."""
    return _resolve(config, settings, known, given, unavailable or {}, stored, tolerant=True)


def _resolve(
    config: InstanceConfig,
    settings: Settings,
    known: dict[str, type[Module]] | None,
    given: dict[str, Module] | None,
    unavailable: dict[str, str],
    stored: dict[str, dict[str, Secret]] | None,
    *,
    tolerant: bool,
) -> tuple[list[Module], StartReport]:
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
    if problems:  # themi.toml itself is wrong: that stops Themi either way
        raise SettingsError("Themi can't start:\n  - " + "\n  - ".join(problems))
    report = StartReport(
        template=template.name,
        ai_choices=tuple(sorted(n for n, cls in known.items() if cls.kind == "ai")),
    )

    def kind(name: str) -> str:
        return known[name].kind if name in known else "feature"

    for name in config.removed:
        report.note(name, "off", kind(name), "removed in themi.toml")
    names = [n for n in template.modules if n not in config.removed]
    names += [n for n in config.added if n not in names]
    shared: dict[str, object] = {}  # one store of shared objects for every module
    built: dict[str, Module] = {}
    for name in names:
        if name in unavailable:
            report.note(name, "not_set_up", kind(name), unavailable[name], warn=True)
            continue
        setup = ModuleSetup(
            settings,
            config.sections.get(name),
            shared,
            module=name,
            sections=config.sections,
            stored=stored,
        )
        try:
            # CR16: `given` is modules built already (the simulator's, on its fakes)
            module = given.get(name) if given is not None else known[name].build(setup)
        except SettingsProblem as exc:  # CR5b: its settings, in the person's words
            report.problems.extend(exc.problems)
            report.note(name, "failed", kind(name), "; ".join(exc.problems))
            continue
        except Exception as exc:
            if not tolerant:
                raise
            report.note(name, "failed", kind(name), f"it couldn't be set up: {exc}")
            continue
        if module is None:
            if name in config.added:
                report.problems.append(
                    f"{name} is added in themi.toml, but its settings aren't there"
                )
                report.note(name, "not_set_up", kind(name), "added, but its settings aren't there")
            else:
                report.note(name, "not_set_up", kind(name), "its settings aren't there")
        else:
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
                report.problems.append(
                    f"{name} needs {', '.join(removed)}, which themi.toml removes"
                )
                reason = f"it needs {', '.join(removed)}, which themi.toml removes"
            else:
                if name in config.added:
                    report.problems.append(f"{name} needs {', '.join(missing)}, which isn't set up")
                reason = f"it needs {', '.join(missing)}, which isn't on"
            report.note(name, "off", kind(name), reason)
            del built[name]
            changed = True
    for name, module in built.items():
        report.note(name, "on", known[name].kind if name in known else type(module).kind)
    report.modules = {  # in the order considered: removed first, then the list's order
        **{n: s for n, s in report.modules.items() if n in config.removed},
        **{n: report.modules[n] for n in names if n in report.modules},
    }
    if not report.problems and not report.has_ai():  # CR19
        providers = ", ".join(report.ai_choices)
        report.problems.append(f"a Themi needs at least one AI provider: add one of {providers}")
    report.problems = sorted(set(report.problems))
    return [built[n] for n in names if n in built], report


def all_groups(known: dict[str, type[Module]] | None = None) -> list[ToolGroup]:
    """CR10b1: every tool group the installed modules know, the core's settings group with
    them, in the order they're offered: for reading old replies, which were offered these."""
    from themi.core.tools import SETTINGS

    known = available_modules() if known is None else known
    found = {SETTINGS.name: SETTINGS}
    for cls in known.values():
        for group in cls.tool_groups:
            found.setdefault(group.name, group)
    return sorted(found.values(), key=lambda g: g.order)


def any_group_of(tool: str) -> str:
    """The group a tool is in among every known group, or "core"."""
    return next((g.name for g in all_groups() if tool in g.tools), "core")
