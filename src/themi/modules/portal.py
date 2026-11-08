"""SP5: what the Modules page does, apart from showing: changes into the draft, settings
checked before they're kept, and Test.

Test builds the module from the draft (the config's values with the draft's over them, the
stored secrets with the draft's) and runs its `check()` against its service. It goes
through the trust tiers as `server_control`, like the server's restart, and a few a minute
at most.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from themi import clock
from themi.modules.base import Module, ModuleSetup
from themi.modules.planning import Planner
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
