"""SP4: the Modules page, for admins: what this Themi is made of, each module's state, what
it needs and what needs it, its settings and its guide.

It's an ordinary page in the Admin menu, used for the first setup and every change after.
The badges come from what happened at the last start (`services.start_report`), the draft
of changes waiting for a restart (`config_drafts`), and, for modules people link on the
website, whether anyone has.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from themi.config import InstanceConfig, available_modules
from themi.modules import KINDS, Module, StartReport
from themi.modules.guides import guide
from themi.modules.settings import FieldSpec, fields, value_sources
from themi.modules.store import Draft, DraftStore, ModuleSecrets
from themi.web.kit import Kit
from themi.web.markdown import render

KIND_HEADINGS = {
    "channel": "How you talk to Themi",
    "ai": "AI",
    "capability": "What Themi can do with voice and pictures",
    "connector": "Services",
    "feature": "Features",
}

# The badge each state shows: (words, the chip's colour)
BADGES = {
    "waiting": ("Waiting for restart", "info"),
    "failed": ("Couldn't start", "bad"),
    "needs_settings": ("Needs settings", "warn"),
    "needs_account": ("Needs an account linked", "warn"),
    "on": ("On", "good"),
    "off": ("Off", ""),
}


@dataclass(frozen=True)
class Card:
    name: str
    title: str
    summary: str
    kind: str
    badge: str  # a key of BADGES
    reason: str = ""  # why it isn't on, from the start report

    @property
    def badge_words(self) -> str:
        return BADGES[self.badge][0]

    @property
    def badge_colour(self) -> str:
        return BADGES[self.badge][1]


@dataclass(frozen=True)
class FieldView:
    spec: FieldSpec
    source: str  # environment, stored, file, default
    value: Any = None  # plain fields only; never a secret's value
    ending: str = ""  # a stored secret's last four characters
    waiting: bool = False  # the draft changes it


@dataclass
class Overview:
    """Everything the page needs, read once per request."""

    known: dict[str, type[Module]]
    report: StartReport
    draft: Draft | None
    built: dict[str, Module] = field(default_factory=dict)  # the modules running now

    def card(self, name: str, services: Any) -> Card:
        cls = self.known[name]
        status = self.report.modules.get(name)
        state = status.state if status else "off"
        if self.draft is not None and self._changed(name):
            badge = "waiting"
        elif state == "failed":
            badge = "failed"
        elif state == "not_set_up":
            badge = "needs_settings"
        elif state == "on":
            module = self.built.get(name)
            linked = module.accounts_linked(services) if module is not None else None
            badge = "needs_account" if linked is False else "on"
        else:
            badge = "off"
        return Card(
            name,
            cls.title or name,
            cls.summary,
            cls.kind,
            badge,
            status.reason if status and state != "on" else "",
        )

    def _changed(self, name: str) -> bool:
        draft = self.draft
        assert draft is not None
        return name in draft.modules or name in draft.sections or name in draft.secrets

    def required_by(self, name: str) -> list[str]:
        return sorted(n for n, c in self.known.items() if name in c.requires)

    def improves(self, name: str) -> list[str]:
        """Modules that use this one when it's there (it's in their `optional`)."""
        return sorted(n for n, c in self.known.items() if name in c.optional)


def overview(kit: Kit) -> Overview:
    services = kit.app.services
    return Overview(
        available_modules(),
        services.start_report,
        DraftStore(kit.app.db).get(),
        {m.name: m for m in kit.app.modules},
    )


def field_views(kit: Kit, name: str, draft: Draft | None) -> list[FieldView]:
    cls = available_modules()[name]
    if cls.settings is None:
        return []
    services = kit.app.services
    config: InstanceConfig = services.instance_config or InstanceConfig()
    section = config.sections.get(name, {})
    stored = ModuleSecrets(kit.app.db, kit.app.store.cipher).info(name)
    sources = value_sources(cls.settings, services.environment, section, stored)
    out = []
    for spec in fields(cls.settings):
        source = sources[spec.name]
        waiting = draft is not None and (
            spec.name in draft.sections.get(name, {}) or spec.name in draft.secrets.get(name, {})
        )
        if spec.secret:
            ending = stored[spec.name].ending if source == "stored" else ""
            out.append(FieldView(spec, source, None, ending, waiting))
            continue
        if source == "environment":
            value = services.environment.get(spec.env, "")
        elif source == "file":
            value = section.get(spec.name)
        else:
            value = spec.default
        out.append(FieldView(spec, source, value, "", waiting))
    return out


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    @router.get("/modules", response_class=HTMLResponse)
    def modules_page(request: Request, q: str = "", only_on: str = "") -> HTMLResponse:
        session = kit.admin(request)
        view = overview(kit)
        words = q.strip().lower()
        cards = [view.card(name, app.services) for name in sorted(view.known)]
        if words:
            cards = [
                c
                for c in cards
                if words in f"{c.name} {c.title} {c.summary}".lower().replace("_", " ")
            ]
        if only_on:
            cards = [c for c in cards if c.badge not in ("off",)]
        groups = [
            (KIND_HEADINGS[kind], sorted((c for c in cards if c.kind == kind), key=_by_title))
            for kind in KINDS
        ]
        return kit.with_flash(
            request,
            "modules.html",
            session,
            groups=[(heading, items) for heading, items in groups if items],
            q=q,
            only_on=bool(only_on),
            warnings=view.report.warnings(),
            template=view.report.template,
            draft=view.draft,
        )

    @router.get("/modules/{name}", response_class=HTMLResponse)
    def module_page(request: Request, name: str) -> HTMLResponse:
        session = kit.admin(request)
        view = overview(kit)
        if name not in view.known:
            return kit.page(
                request,
                "message.html",
                404,
                title="No such module",
                body=f"There's no module called {name} in this Themi.",
            )
        cls = view.known[name]
        card = view.card(name, app.services)
        text = guide(cls)
        module = view.built.get(name)
        views = field_views(kit, name, view.draft)

        def cards(names: list[str] | tuple[str, ...]) -> list[Card]:
            return [view.card(n, app.services) for n in names if n in view.known]

        return kit.with_flash(
            request,
            "module.html",
            session,
            card=card,
            cls=cls,
            guide=render(text.replace("$SITE", kit.ctx.base_url)) if text else None,
            fields=[f for f in views if not f.spec.advanced],
            advanced=[f for f in views if f.spec.advanced],
            requires=cards(cls.requires),
            required_by=cards(view.required_by(name)),
            optional=cards(cls.optional),
            improves=cards(view.improves(name)),
            groups=[g.description for g in cls.tool_groups],
            need=cls.needs_accounts,
            linked=module.accounts_linked(app.services) if module is not None else None,
            website=cls.website,
        )

    return router


def _by_title(card: Card) -> str:
    return card.title.lower()
