"""SP5: what the Modules page does, apart from showing: changes into the draft, settings
checked before they're kept, and Test.

Test builds the module from the draft (the config's values with the draft's over them, the
stored secrets with the draft's) and runs its `check()` against its service. It goes
through the trust tiers as `server_control`, like the server's restart, and a few a minute
at most.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.accounts import NotFound
from themi.channels.outbox import SERVER_KIND, Priority
from themi.localtime import to_utc_iso
from themi.modules.base import Module, ModuleSetup
from themi.modules.planning import Planner
from themi.modules.report import StartReport
from themi.modules.settings import SettingsProblem, fields, read_settings
from themi.modules.store import ConfigAudit, Draft, DraftStore, ModuleSecrets

if TYPE_CHECKING:
    from datetime import datetime

    from themi.accounts import Member
    from themi.autonomy import ExecutionContext
    from themi.config import InstanceConfig
    from themi.core.services import Services
    from themi.storage.secrets import Cipher, Secret

log = logging.getLogger(__name__)

CATEGORY = "server_control"
TEST_EXECUTOR = "modules.test"
RESTART_EXECUTOR = "modules.restart"  # SP6
TEST_WITHIN = 20.0  # seconds a check gets
TESTS_PER_MINUTE = 5

Builder = Callable[[type[Module], ModuleSetup], "Module | None"]


class PortalError(Exception):
    """Something the page should say instead of doing it."""


@dataclass(frozen=True)
class Saved:
    changed: bool
    problems: tuple[str, ...] = ()


class Portal:
    def __init__(
        self,
        services: Services,
        cipher: Cipher,
        *,
        known: Callable[[], dict[str, type[Module]]] | None = None,
        templates: Callable[[str], tuple[str, ...]] | None = None,
        builder: Builder | None = None,
    ) -> None:
        """`known` and `templates`: the installed modules and a template's modules (the
        real ones by default); `builder`: how Test builds a module (tests give fakes)."""
        self.services = services
        self.db = services.store.db
        self.cipher = cipher
        self.drafts = DraftStore(self.db)
        self.secrets = ModuleSecrets(self.db, cipher)
        self.audit = ConfigAudit(self.db)
        self._known = known
        self._templates = templates
        self.builder: Builder = builder or (lambda cls, setup: cls.build(setup))
        self._tests: dict[int, list[datetime]] = {}

    def install(self) -> None:
        self.services.autonomy.executors.register(TEST_EXECUTOR)(self._run_test)
        self.services.autonomy.executors.register(RESTART_EXECUTOR)(self._apply)

    # ----- what there is ------------------------------------------------------------------

    def known(self) -> dict[str, type[Module]]:
        if self._known is not None:
            return self._known()
        from themi.config import available_modules

        return available_modules()

    def template_modules(self, name: str) -> tuple[str, ...]:
        if self._templates is not None:
            return self._templates(name)
        from themi.config import load_template

        return load_template(name).modules

    def config(self) -> InstanceConfig:
        from themi.config import InstanceConfig

        return self.services.instance_config or InstanceConfig(
            template=self.services.start_report.template
        )

    def draft(self) -> Draft:
        return self.drafts.get() or Draft()

    def planner(self, draft: Draft | None = None) -> Planner:
        return Planner(self.config(), self.known(), self.template_modules, draft or self.draft())

    # ----- changes ------------------------------------------------------------------------

    def save(self, planner: Planner, member: Member, what: str) -> None:
        planner.draft.note(member.id, what)
        self.drafts.save(planner.draft, member.id)
        self.audit.note(member.id, what)

    def undo(self, member: Member) -> None:
        self.drafts.discard()
        self.audit.note(member.id, "undid the changes waiting for a restart")

    def siblings(self, name: str) -> list[str]:
        """Modules that share `name`'s settings (the wall's two), itself first: a value set
        for one is set for each."""
        known = self.known()
        model = known[name].settings
        return [name] + [n for n, c in known.items() if n != name and model and c.settings is model]

    def save_settings(
        self,
        name: str,
        values: dict[str, Any],
        secrets: dict[str, str | None],
        member: Member,
    ) -> Saved:
        """Plain `values` (None or "" to go back to the default) and `secrets` (a new value,
        or None to clear) for a module, checked as the module would read them, then put in
        the draft for it and the modules sharing its settings."""
        cls = self.known()[name]
        if cls.settings is None:
            raise PortalError(f"{cls.title or name} has no settings of its own.")
        draft = self.draft()
        planner = self.planner(draft)
        section = dict(planner.as_config().sections.get(name, {}))
        for key, value in values.items():
            if value is None or value == "":
                section.pop(key, None)
            else:
                section[key] = value
        stored = self.stored_with_draft(name, draft)
        for key, value in secrets.items():
            if value is None:
                stored.pop(key, None)
            else:
                from themi.storage.secrets import Secret

                stored[key] = Secret(value)
        try:
            read_settings(cls.settings, self.services.environment, section, name, stored)
        except SettingsProblem as exc:
            return Saved(False, tuple(exc.problems))
        if not values and not secrets:
            return Saved(False)
        for module in self.siblings(name):
            draft.sections.setdefault(module, {}).update(values)
            for key, value in secrets.items():
                draft.put_secret(self.cipher, module, key, value)
        labels = {f.name: f.label for f in fields(cls.settings)}
        said = [labels.get(k, k) for k in (*values, *secrets)]
        self.save(planner, member, f"changed {cls.title or name}: {', '.join(said)}")
        return Saved(True)

    def move(self, name: str, field: str, member: Member) -> str:
        """SP8a: copy a setting from the environment (.env) into Themi: a secret into the
        module secrets, a plain value into themi.toml, for the module and those sharing its
        settings. The environment still wins until its line goes, so nothing changes now.
        Returns the variable, for the person to delete."""
        from themi.config import write_config, write_path

        cls = self.known()[name]
        spec = (
            next((f for f in fields(cls.settings) if f.name == field), None)
            if cls.settings
            else None
        )
        if spec is None:
            raise PortalError(f"{cls.title or name} has no setting called {field}.")
        value = self.services.environment.get(spec.env, "").strip()
        if not value:
            raise PortalError(f"{spec.env} isn't set on the server, so there's nothing to copy.")
        if spec.secret:
            for module in self.siblings(name):
                self.secrets.set(module, field, value, member.id)
        else:
            config = self.config()
            sections = {n: dict(v) for n, v in config.sections.items()}
            typed: Any = (
                value.lower() in ("1", "true", "yes", "on") if spec.kind == "bool" else value
            )
            for module in self.siblings(name):
                sections.setdefault(module, {})[field] = typed
            from dataclasses import replace

            config = replace(config, sections=sections)
            write_config(config, write_path(config, self.services.environment or None))
            self.services.instance_config = config
        self.audit.note(member.id, f"copied {spec.env} from the server into Themi")
        return spec.env

    def stored_with_draft(self, name: str, draft: Draft) -> dict[str, Secret]:
        """The module's stored secrets with the draft's changes over them."""
        stored = dict(self.secrets.all().get(name, {}))
        for key, token in draft.secrets.get(name, {}).items():
            if token is None:
                stored.pop(key, None)
            else:
                value = draft.secret(self.cipher, name, key)
                if value is not None:
                    stored[key] = value
        return stored

    # ----- Test ---------------------------------------------------------------------------

    async def test(self, name: str, member: Member) -> str:
        """Try the module, as the draft has it, against its service. Returns what to say."""
        cls = self.known().get(name)
        if cls is None:
            raise PortalError(f"There's no module called {name}.")
        now = clock.now()
        recent = [t for t in self._tests.get(member.id, []) if now - t < timedelta(minutes=1)]
        if len(recent) >= TESTS_PER_MINUTE:
            raise PortalError("That's a lot of tests in a minute. Try again shortly.")
        self._tests[member.id] = [*recent, now]
        outcome = await self.services.autonomy.stage(
            CATEGORY,
            member,
            f"Test {cls.title or name}",
            {"module": name},
            TEST_EXECUTOR,
            requested=True,
        )
        return outcome.message

    async def _run_test(self, payload: dict[str, Any], context: ExecutionContext) -> str:
        name = str(payload["module"])
        cls = self.known()[name]
        title = cls.title or name
        draft = self.draft()
        config = self.planner(draft).as_config()
        stored = {n: self.stored_with_draft(n, draft) for n in config.sections | {name: {}}}
        settings = self.services.settings or SimpleNamespace(environment=self.services.environment)
        setup = ModuleSetup(
            settings,  # type: ignore[arg-type]  # builds read only the environment from it
            config.sections.get(name),
            {},
            module=name,
            sections=config.sections,
            stored=stored,
        )
        try:
            module = self.builder(cls, setup)
        except SettingsProblem as exc:
            result = f"{title}'s settings aren't right yet: {'; '.join(exc.problems)}"
        except Exception as exc:
            result = f"{title} couldn't be set up: {exc}"
        else:
            if module is None:
                result = f"{title} isn't set up yet: fill in its settings first."
            else:
                result = await self._check(module, title)
        self.audit.note(context.member.id, f"tested {title}: {result}")
        return result

    async def _check(self, module: Module, title: str) -> str:
        try:
            problem = await asyncio.wait_for(module.check(), TEST_WITHIN)
        except TimeoutError:
            return f"{title} didn't answer within {int(TEST_WITHIN)} seconds."
        except Exception as exc:  # whatever went wrong, said once
            log.info("Test of %s raised", title, exc_info=True)
            return f"{title} couldn't be tried: {exc}"
        if problem:
            return f"{title} didn't work: {problem}"
        if type(module).check is Module.check:
            return f"{title} has nothing to try until it's on; its settings look right."
        return f"{title} worked."

    # ----- SP6: restart and apply -----------------------------------------------------------

    def _settings(self) -> Any:
        return self.services.settings or SimpleNamespace(environment=self.services.environment)

    def all_stored(self, draft: Draft) -> dict[str, dict[str, Secret]]:
        names = set(self.secrets.all()) | set(draft.secrets)
        return {n: self.stored_with_draft(n, draft) for n in names}

    def preflight(self) -> StartReport:
        """What starting with the draft would do, without installing anything: each module
        resolved and built from the draft's config and secrets."""
        from themi.config import resolve_start

        draft = self.draft()
        config = self.planner(draft).as_config()
        _, report = resolve_start(
            config, self._settings(), self.known(), stored=self.all_stored(draft)
        )
        return report

    async def restart(self, member: Member) -> str:
        """Apply the draft and restart Themi, through the trust tiers."""
        outcome = await self.services.autonomy.stage(
            CATEGORY,
            member,
            "Restart Themi with the Modules page's changes",
            {},
            RESTART_EXECUTOR,
            requested=True,
        )
        return outcome.message

    async def _apply(self, payload: dict[str, Any], context: ExecutionContext) -> str:
        self.apply(context.member)
        restart = self.services.restart
        if restart is None:
            return "Saved. Restart Themi on the server to put the changes in place."
        restart()
        return "Restarting Themi with the changes. It's back in about half a minute."

    def apply(self, member: Member) -> None:
        """Make the draft the live setup: the current one kept as the last good, the draft
        written to themi.toml and the module secrets, the draft gone, and a note to tell
        `member` how it went once Themi is back."""
        from themi.config import as_toml, write_config, write_path

        draft = self.draft()
        current = self.config()
        snapshot = [
            [row["module"], row["field"], bytes(row["ciphertext"]).decode()]
            for row in self.db.query("SELECT module, field, ciphertext FROM module_secrets")
        ]
        now = to_utc_iso(clock.now())
        self.db.execute(
            "INSERT INTO config_last_good (id, toml, secrets, saved_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET toml = excluded.toml, secrets = excluded.secrets, "
            "saved_at = excluded.saved_at",
            (as_toml(current), json.dumps(snapshot), now),
        )
        if not draft.is_empty():
            config = self.planner(draft).as_config()
            write_config(config, write_path(config, self.services.environment or None))
            self.services.instance_config = config
            for module, values in draft.secrets.items():
                for key in values:
                    value = draft.secret(self.cipher, module, key)
                    if value is None:
                        self.secrets.clear(module, key)
                    else:
                        self.secrets.set(module, key, value, member.id)
        self.db.execute(
            "INSERT INTO config_restarts (member_id, changes, asked_at) VALUES (?, ?, ?)",
            (member.id, json.dumps([e["what"] for e in draft.log]), now),
        )
        self.drafts.discard()
        self.audit.note(member.id, "restarted Themi to put the changes in place")

    async def announce(self) -> None:
        """Once Themi is back: tell whoever restarted it what changed and what didn't start."""
        report = self.services.start_report
        for row in self.db.query(
            "SELECT id, member_id, changes FROM config_restarts WHERE announced_at IS NULL"
        ):
            self.db.execute(
                "UPDATE config_restarts SET announced_at = ? WHERE id = ?",
                (to_utc_iso(clock.now()), row["id"]),
            )
            if row["member_id"] is None:
                continue
            try:
                member = self.services.store.get_member(row["member_id"])
            except NotFound:
                continue
            await self.services.outbox.send(
                member,
                restart_words(json.loads(row["changes"]), report),
                priority=Priority.NORMAL,
                kind=SERVER_KIND,  # it answers what they asked for
                dedupe_key=f"modules-restart:{row['id']}",
            )

    # ----- going back -----------------------------------------------------------------------

    def last_good(self) -> tuple[InstanceConfig, dict[str, dict[str, str]]] | None:
        """The setup before the last one applied: its config, and its secrets (encrypted)."""
        from themi.config import parse_config

        row = self.db.one("SELECT toml, secrets FROM config_last_good WHERE id = 1")
        if row is None:
            return None
        config = parse_config(tomllib.loads(row["toml"]))
        secrets: dict[str, dict[str, str]] = {}
        for module, key, token in json.loads(row["secrets"]):
            secrets.setdefault(module, {})[key] = token
        return config, secrets

    def back_to_last_good(self, member: Member) -> bool:
        """Put the last good setup in the draft, to look at before restarting. False when
        there's none."""
        found = self.last_good()
        if found is None:
            return False
        config, secrets = found
        planner = self.planner(Draft())
        if config.template != planner.config.template:
            planner.use_template(config.template)
        was = Planner(config, self.known(), self.template_modules).desired()
        now = planner.desired()
        for name in was:
            if name not in now:
                planner.apply(planner.turn_on(name))
        for name in now:
            if name not in was and name in planner.desired():
                planner.apply(planner.turn_off(name))
        current = self.config().sections
        for name in set(current) | set(config.sections):
            mine, theirs = current.get(name, {}), config.sections.get(name, {})
            changed = {k: theirs.get(k, "") for k in set(mine) | set(theirs)}
            changed = {k: v for k, v in changed.items() if mine.get(k) != theirs.get(k)}
            if changed:
                planner.draft.sections[name] = changed
        stored = {
            (row["module"], row["field"]): self.cipher.decrypt(row["ciphertext"]).reveal()
            for row in self.db.query("SELECT module, field, ciphertext FROM module_secrets")
        }
        before = {
            (module, key): self.cipher.decrypt(token.encode()).reveal()
            for module, values in secrets.items()
            for key, token in values.items()
        }
        for module, key in set(stored) | set(before):
            if stored.get((module, key)) != before.get((module, key)):
                planner.draft.put_secret(self.cipher, module, key, before.get((module, key)))
        self.save(planner, member, "put back the last working setup, to restart with")
        return True


def restart_words(changes: list[str], report: StartReport) -> str:
    """What someone hears once Themi is back from a restart they asked for."""
    lines = ["Themi restarted."]
    if changes:
        lines[0] = "Themi restarted with your changes: " + "; ".join(changes) + "."
    failed = [s for s in report.modules.values() if s.state == "failed"]
    if failed:
        lines.append(
            "These couldn't start: "
            + "; ".join(f"{s.name} ({s.reason})" for s in failed)
            + ". The Modules page can put the last working setup back."
        )
    return "\n".join(lines)
