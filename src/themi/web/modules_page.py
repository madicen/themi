"""SP4: the Modules page, for admins: what this Themi is made of, each module's state, what
it needs and what needs it, its settings and its guide.

It's an ordinary page in the Admin menu, used for the first setup and every change after.
The badges come from what happened at the last start (`services.start_report`), the draft
of changes waiting for a restart (`config_drafts`), and, for modules people link on the
website, whether anyone has.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from themi import clock
from themi.config import InstanceConfig, available_modules, template_packages
from themi.localtime import to_utc_iso
from themi.modules import KINDS, Module, StartReport
from themi.modules.guides import guide
from themi.modules.portal import Portal, PortalError
from themi.modules.settings import FieldSpec, fields, value_sources
from themi.modules.store import Draft, DraftStore, ModuleSecrets
from themi.web.auth import Session
from themi.web.kit import Kit
from themi.web.markdown import render

# SP5: saving a secret, testing with new secrets and switching template need a sign-in
# this recent
RECENT_SIGN_IN = timedelta(minutes=15)
SIGN_IN_AGAIN = (
    "For that, sign in again first: it's been a while since you did. Sign out, then use "
    "a new link (send /site to Themi), or sign in with Google."
)


def recently_signed_in(session: Session) -> bool:
    began = session.signed_in_at
    return began is not None and clock.now() - began < RECENT_SIGN_IN


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
    copied: bool = False  # SP8a: set on the server, and copied into Themi already


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
    portal = services.get(Portal)
    config: InstanceConfig = portal.planner(draft).as_config()  # the draft's values shown
    section = config.sections.get(name, {})
    stored: dict[str, Any] = dict(ModuleSecrets(kit.app.db, kit.app.store.cipher).info(name))
    for key, token in (draft.secrets.get(name, {}) if draft else {}).items():
        if token is None:
            stored.pop(key, None)
        else:
            value = draft.secret(kit.app.store.cipher, name, key) if draft else None
            stored[key] = SimpleNamespace(ending=value.reveal()[-4:] if value else "")
    sources = value_sources(cls.settings, services.environment, section, stored)
    out = []
    for spec in fields(cls.settings):
        source = sources[spec.name]
        waiting = draft is not None and (
            spec.name in draft.sections.get(name, {}) or spec.name in draft.secrets.get(name, {})
        )
        copied = source == "environment" and (
            spec.name in stored if spec.secret else spec.name in section
        )
        if spec.secret:
            ending = stored[spec.name].ending if source == "stored" else ""
            out.append(FieldView(spec, source, None, ending, waiting, copied))
            continue
        if source == "environment":
            value = services.environment.get(spec.env, "")
        elif source == "file":
            value = section.get(spec.name)
        else:
            value = spec.default
        out.append(FieldView(spec, source, value, "", waiting, copied))
    return out


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def pending(member: Any) -> int:
        """SP5: the bar on every admin page while changes wait for a restart."""
        if member is None or not member.is_admin:
            return 0
        draft = DraftStore(app.db).get()
        return draft.count() if draft else 0

    kit.templates.env.globals["pending_changes"] = pending

    def portal() -> Portal:
        return app.services.get(Portal)

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
            template=portal().planner(view.draft).template,
            templates=sorted(template_packages()),
            draft=view.draft,
            audit=portal().audit.recent(),
            last_good=bool(view.report.failed()) and portal().last_good() is not None,
        )

    def module_page(request: Request, name: str) -> HTMLResponse:
        return show_module(request, name)

    def show_module(
        request: Request, name: str, problems: tuple[str, ...] = (), status: int = 200
    ) -> HTMLResponse:
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

        response = kit.with_flash(
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
            problems=problems,
            in_list=name in portal().planner(view.draft).desired(),
        )
        response.status_code = status
        return response

    # ----- SP5: changes -------------------------------------------------------------------

    @router.post("/modules/{name}/switch", response_class=HTMLResponse)
    async def switch(request: Request, name: str) -> Response:
        session, form = await kit.checked(request, admin=True)
        known = available_modules()
        if name not in known:
            return kit.redirect("/modules", f"There's no module called {name}.")
        planner = portal().planner()
        on = form.get("to") == "on"
        change = planner.turn_on(name) if on else planner.turn_off(name)
        names = change.on if on else change.off
        if not names:
            return kit.redirect(f"/modules/{name}", "Nothing to change.")
        if len(names) > 1 and form.get("confirmed") != "1":
            view = overview(kit)
            return kit.with_flash(
                request,
                "module_confirm.html",
                session,
                card=view.card(name, app.services),
                on=on,
                others=[view.card(n, app.services) for n in names if n != name],
            )
        planner.apply(change)
        titles = [known[n].title or n for n in names]
        what = f"turned {'on' if on else 'off'} {', '.join(titles)}"
        portal().save(planner, session.member, what)
        return kit.redirect(f"/modules/{name}", f"Saved: {what}. It changes when Themi restarts.")

    @router.post("/modules/template", response_class=HTMLResponse)
    async def template(request: Request) -> Response:
        session, form = await kit.checked(request, admin=True)
        chosen = str(form.get("template", ""))
        if chosen not in template_packages():
            return kit.redirect("/modules", f"There's no template called {chosen}.")
        if not recently_signed_in(session):
            return kit.redirect("/modules", SIGN_IN_AGAIN)
        planner = portal().planner()
        if chosen == planner.template:
            return kit.redirect("/modules", f"This Themi is on the {chosen} template already.")
        switch = planner.switch_template(chosen)
        if form.get("confirmed") != "1":
            known = available_modules()
            return kit.with_flash(
                request,
                "template_confirm.html",
                session,
                switch=switch,
                title=lambda n: known[n].title or n if n in known else n,
            )
        planner.use_template(chosen)
        portal().save(planner, session.member, f"switched to the {chosen} template")
        return kit.redirect(
            "/modules", f"Saved: the {chosen} template. It changes when Themi restarts."
        )

    @router.post("/modules/{name}/settings", response_class=HTMLResponse)
    async def save_settings(request: Request, name: str) -> Response:
        session, form = await kit.checked(request, admin=True)
        cls = available_modules().get(name)
        if cls is None or cls.settings is None:
            return kit.redirect("/modules", "That module has no settings.")
        views = {v.spec.name: v for v in field_views(kit, name, DraftStore(app.db).get())}
        values: dict[str, Any] = {}
        secrets: dict[str, str | None] = {}
        problems: list[str] = []
        for spec in fields(cls.settings):
            view = views[spec.name]
            if view.source == "environment":
                continue  # set on the server: locked here
            raw = str(form.get(spec.name, "")).strip()
            if spec.secret:
                if raw:
                    secrets[spec.name] = raw
                elif form.get(f"clear_{spec.name}") and view.source == "stored":
                    secrets[spec.name] = None
                continue
            if spec.kind == "bool":
                value: Any = form.get(spec.name) in ("on", "1", "yes")
            elif spec.kind == "number" and raw:
                try:
                    value = int(raw) if raw.lstrip("-").isdigit() else float(raw)
                except ValueError:
                    problems.append(f"{spec.label} is a number, not {raw}")
                    continue
            elif spec.kind == "choice" and raw and raw not in spec.choices:
                problems.append(f"{spec.label} is one of {', '.join(spec.choices)}")
                continue
            else:
                value = raw
            current = view.value if view.value is not None else ""
            if value != current:
                values[spec.name] = value
        if secrets and not recently_signed_in(session):
            return kit.redirect(f"/modules/{name}", SIGN_IN_AGAIN)
        if problems:
            return show_module(request, name, tuple(problems), 400)
        try:
            saved = portal().save_settings(name, values, secrets, session.member)
        except PortalError as exc:
            return kit.redirect(f"/modules/{name}", str(exc))
        if saved.problems:
            return show_module(request, name, saved.problems, 400)
        message = "Saved. It changes when Themi restarts." if saved.changed else "Nothing changed."
        return kit.redirect(f"/modules/{name}", message)

    @router.post("/modules/{name}/test", response_class=HTMLResponse)
    async def test(request: Request, name: str) -> Response:
        session, _ = await kit.checked(request, admin=True)
        draft = DraftStore(app.db).get()
        if draft and draft.secrets.get(name) and not recently_signed_in(session):
            return kit.redirect(f"/modules/{name}", SIGN_IN_AGAIN)
        try:
            message = await portal().test(name, session.member)
        except PortalError as exc:
            message = str(exc)
        return kit.redirect(f"/modules/{name}", message)

    @router.post("/modules/{name}/move/{field}", response_class=HTMLResponse)
    async def move(request: Request, name: str, field: str) -> Response:
        """SP8a: a setting from the server's .env copied into Themi."""
        session, _ = await kit.checked(request, admin=True)
        cls = available_modules().get(name)
        secret = (
            any(f.name == field and f.secret for f in fields(cls.settings))
            if (cls and cls.settings)
            else False
        )
        if secret and not recently_signed_in(session):
            return kit.redirect(f"/modules/{name}", SIGN_IN_AGAIN)
        try:
            variable = portal().move(name, field, session.member)
        except (PortalError, KeyError) as exc:
            return kit.redirect(f"/modules/{name}", str(exc).strip("'"))
        return kit.redirect(
            f"/modules/{name}",
            f"Copied into Themi. On the server, delete the {variable} line from .env and "
            "restart Themi: it'll use the copy from then on.",
        )

    # ----- SP6: restart and apply ----------------------------------------------------------

    @router.get("/modules/restart", response_class=HTMLResponse)
    def restart_page(request: Request) -> HTMLResponse:
        session = kit.admin(request)
        draft = DraftStore(app.db).get()
        try:
            check = portal().preflight()
            problems = [w for w in check.warnings()]
            broken = ""
        except Exception as exc:  # a config the draft makes that can't even be read
            problems, broken = [], str(exc)
        return kit.with_flash(
            request,
            "restart.html",
            session,
            draft=draft,
            problems=problems,
            broken=broken,
        )

    @router.post("/modules/restart", response_class=HTMLResponse)
    async def restart(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        started = to_utc_iso(app.services.start_report.made_at)
        try:
            message = await portal().restart(session.member)
        except Exception as exc:
            return kit.redirect("/modules/restart", f"Couldn't restart: {exc}")
        return kit.with_flash(
            request,
            "restarting.html",
            session,
            message=message,
            started=started,
            restarting=app.services.restart is not None,
        )

    @router.get("/modules/restart/status")
    def restart_status(request: Request, since: str = "") -> Response:
        """Polled by the Restarting page: 204 while the same Themi is running, then a
        redirect to the Modules page once a new one has started."""
        kit.admin(request)
        if to_utc_iso(app.services.start_report.made_at) == since:
            return Response(status_code=204)
        return Response(status_code=200, headers={"HX-Redirect": "/modules"})

    @router.post("/modules/last-good", response_class=HTMLResponse)
    async def last_good(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        if not portal().back_to_last_good(session.member):
            return kit.redirect("/modules", "There's no earlier setup to go back to.")
        return kit.redirect(
            "/modules/restart", "The last working setup is waiting. Restart to go back to it."
        )

    @router.post("/modules/undo", response_class=HTMLResponse)
    async def undo(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        portal().undo(session.member)
        return kit.redirect("/modules", "The changes waiting for a restart are gone.")

    # Last, so the pages above (/modules/restart) aren't taken for a module's name.
    router.add_api_route(
        "/modules/{name}", module_page, methods=["GET"], response_class=HTMLResponse
    )
    return router


def _by_title(card: Card) -> str:
    return card.title.lower()
