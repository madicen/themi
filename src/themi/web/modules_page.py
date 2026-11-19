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
from themi.accounts import AccountsError
from themi.accounts.preferences import Preferences
from themi.config import InstanceConfig, available_modules, template_packages
from themi.localtime import to_utc_iso
from themi.modules import Module, StartReport
from themi.modules.groups import (
    ModuleGroup,
    group_of,
    guests,
    known_groups,
    members,
    parent_in_group,
    starter,
    tree,
)
from themi.modules.guides import guide
from themi.modules.planning import Change, Planner, TemplateSwitch
from themi.modules.portal import Portal, PortalError
from themi.modules.settings import FieldSpec, fields, value_sources
from themi.modules.store import Draft, DraftStore, ModuleSecrets
from themi.web import model_forms
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


# The badge each state shows: (words, the chip's colour)
BADGES = {
    "waiting": ("Waiting for restart", "info"),
    "failed": ("Couldn't start", "bad"),
    "needs_settings": ("Needs settings", "warn"),
    "needs_library": ("Not in this install", "warn"),
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
class Row:
    """MP1: a card in its group's list: indented under what it builds on, or a guest from
    another group."""

    card: Card
    depth: int = 0
    home: str = ""  # a guest's own group's title
    on: bool = False  # MP6: on, or coming on at the restart (its card's switch)
    needs: tuple[str, ...] = ()  # MP6: what it requires that's off, by title
    cost: str = ""


@dataclass(frozen=True)
class Pick:
    """MP2: a module on a review sheet, ticked or not; `fixed` when it's on already."""

    card: Card
    checked: bool
    fixed: bool = False
    note: str = ""


@dataclass(frozen=True)
class Offer:
    """MP2: an extra on a review sheet: `field` is the form's name for it (`spare`)."""

    card: Card
    field: str
    checked: bool = False
    note: str = ""


def _note(cls: type[Module]) -> str:
    """What a module asks for on a sheet: an account, or its cost."""
    if cls.needs_accounts is not None:
        return f"Needs {cls.needs_accounts.what} linked"
    return cls.cost


@dataclass(frozen=True)
class GroupSection:
    group: ModuleGroup
    rows: list[Row]
    on: int = 0  # MP2: its own modules on (or waiting to come on)
    total: int = 0
    attention: int = 0  # MP6: its own modules that need something done


def group_sections(
    known: dict[str, type[Module]],
    cards: dict[str, Card],
    shown: set[str],
    desired: set[str] | frozenset[str] = frozenset(),
) -> list[GroupSection]:
    """MP1: the page's groups in order, each with its modules as a tree and its guests
    after them; a group with nothing shown is left out."""
    titles = {n: c.title for n, c in cards.items()}

    def row(n: str, depth: int, home: str = "") -> Row:
        cls = known[n]
        needs = tuple(titles.get(r, r) for r in cls.requires if r not in desired)
        on = n in desired
        return Row(cards[n], depth, home, on, () if on else needs, cls.cost)

    out = []
    for group in known_groups(known.values()):
        rows = [
            row(n, depth) for n, depth in tree(members(group, known), known, titles) if n in shown
        ]
        rows += [
            row(n, 0, group_of(known[n]).title)
            for n in sorted(guests(group, known), key=lambda n: titles[n].lower())
            if n in shown
        ]
        if rows:
            own = members(group, known)
            out.append(
                GroupSection(
                    group,
                    rows,
                    sum(n in desired for n in own),
                    len(own),
                    sum(cards[n].badge in ATTENTION for n in own),
                )
            )
    return out


def template_by_group(
    switch: TemplateSwitch, known: dict[str, type[Module]]
) -> list[tuple[str, list[str], list[str]]]:
    """MP7: what a template switch turns off and on, group by group: (group, off, on)."""
    gone = [n for name, more in switch.off for n in (name, *more)]
    out = []
    for group in known_groups(known.values()):
        own = set(members(group, known))
        off = sorted((known[n].title or n) for n in gone if n in own)
        on = sorted((known[n].title or n) for n in switch.on if n in own)
        if off or on:
            out.append((group.title, off, on))
    return out


# MP6: the badges that need someone to do something, and where on its page that's done
ATTENTION = {
    "failed": "",
    "needs_settings": "#server",
    "needs_library": "",
    "needs_account": "#accounts",
}
SHOWS = {"all": "All", "on": "On", "off": "Off", "attention": "Needs attention"}


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
        elif state == "needs_library":
            badge = "needs_library"
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
    def modules_page(
        request: Request, q: str = "", only_on: str = "", show: str = "all"
    ) -> HTMLResponse:
        session = kit.admin(request)
        view = overview(kit)
        if only_on:  # the SP4 checkbox's address, kept
            show = "on"
        if show not in SHOWS:
            show = "all"
        words = q.strip().lower()
        cards = {name: view.card(name, app.services) for name in view.known}
        planner = portal().planner(view.draft)
        desired = set(planner.desired())
        shown = set(cards)
        if words:  # MP6: a group's name matches all of it
            matched = {g.id for g in known_groups(view.known.values()) if words in g.title.lower()}
            shown = {
                n
                for n, c in cards.items()
                if words in f"{c.name} {c.title} {c.summary}".lower().replace("_", " ")
                or group_of(view.known[n]).id in matched
            }
        if show == "on":  # running, or about to be, or trying to
            shown = {n for n in shown if cards[n].badge != "off"}
        elif show == "off":
            shown = {n for n in shown if cards[n].badge == "off"}
        elif show == "attention":
            shown = {n for n in shown if cards[n].badge in ATTENTION}
        attention = sorted(
            (c for c in cards.values() if c.badge in ATTENTION), key=lambda c: c.title.lower()
        )
        return kit.with_flash(
            request,
            "modules.html",
            session,
            groups=group_sections(view.known, cards, shown, desired),
            q=q,
            show=show,
            shows=SHOWS,
            attention=[(c, f"/modules/{c.name}{ATTENTION[c.badge]}") for c in attention],
            warnings=view.report.warnings(),
            template=planner.template,
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
            metered=any(m.module == name for m in app.services.usage.meters.values()),  # UC5
            **own_parts(cls, session.member, view),  # MP5
            **page_helps(cls, card, view, module),  # MP7
        )
        response.status_code = status
        return response

    def own_parts(cls: type[Module], member: Any, view: Overview) -> dict[str, Any]:
        """MP5: the rest of what configures a module, for its page: the household's settings,
        the admin's own preferences, its pages, and who can use it."""
        store = app.store
        name = cls.name
        planner = portal().planner(view.draft)
        household = (
            model_forms.inputs(cls.household, store.household(cls.household), None)
            if cls.household is not None
            else []
        )
        prefs: list[model_forms.Input] = []
        if cls.preferences is not None:
            model = cls.preferences
            prefs = model_forms.inputs(
                model, store.preferences(member.id, model), shown_preferences(model, member)
            )
        owned = app.services.owned_by(name)
        roles = [(role, planner.may_use(role, name)) for role in sorted(planner.roles())]
        return {
            "household_inputs": household,
            "pref_inputs": prefs,
            "settings_anchor": (cls.preferences.settings_anchor if cls.preferences else ""),
            "own_pages": [m for m in owned.menu if not m.admin_only or member.is_admin],
            "has_pages": bool(owned.menu),
            "is_on": name in view.built,
            "roles": roles,
            "roles_waiting": any(
                role in (view.draft.roles if view.draft else {}) for role, _ in roles
            ),
        }

    def page_helps(
        cls: type[Module], card: Card, view: Overview, module: Module | None
    ) -> dict[str, Any]:
        """MP7: where the module sits (its group and the group's others), the setup
        checklist, and whether it has a Test, with the last one's result."""
        name = cls.name
        known = view.known
        group = group_of(cls)
        own = members(group, known)
        titles = {n: (known[n].title or n) for n in known}
        neighbours = [(view.card(n, app.services), depth) for n, depth in tree(own, known, titles)]
        has_check = cls.check is not Module.check
        last = portal().last_test(card.title) if has_check else None
        desired = set(portal().planner(view.draft).desired())
        in_list = name in desired
        need = cls.needs_accounts
        linked = module.accounts_linked(app.services) if module is not None else None
        steps: list[tuple[str, bool]] = [("Turned on", in_list)]
        if cls.settings is not None and fields(cls.settings):
            steps.append(("Settings filled in", card.badge not in ("needs_settings", "failed")))
        if has_check:
            steps.append(("Tested", bool(last) and last[0].endswith(" worked.")))
        steps.append(
            ("Running (restarted since the last change)", card.badge in ("on", "needs_account"))
        )
        if need is not None:
            steps.append((f"{need.what[:1].upper()}{need.what[1:]} linked", linked is True))
        return {
            "group": group,
            "neighbours": neighbours,
            "has_check": has_check,
            "last_test": last,
            "steps": steps if in_list and not all(done for _, done in steps) else [],
            "desired": desired,
        }

    def shown_preferences(model: type[Preferences], member: Any) -> set[str] | None:
        try:
            return model.on_form(app.services, member)
        except Exception:  # a module that's off may not have what its check reads
            return None

    @router.post("/modules/{name}/household", response_class=HTMLResponse)
    async def save_household(request: Request, name: str) -> Response:
        """MP5: the household's settings for a module, saved now (as on Family)."""
        session, form = await kit.checked(request, admin=True)
        cls = available_modules().get(name)
        if cls is None or cls.household is None:
            return kit.redirect("/modules", "That module has no household settings.")
        try:
            values = model_forms.parse(cls.household, form, None)
            app.store.save_household(session.member, cls.household, **values)
        except AccountsError as exc:
            return show_module(request, name, (str(exc),), 400)
        return kit.redirect(f"/modules/{name}#household", "Saved.")

    @router.post("/modules/{name}/preferences", response_class=HTMLResponse)
    async def save_preferences(request: Request, name: str) -> Response:
        """MP5: the admin's own preferences for a module, saved now (as on Settings)."""
        session, form = await kit.checked(request, admin=True)
        cls = available_modules().get(name)
        if cls is None or cls.preferences is None:
            return kit.redirect("/modules", "That module has no settings of yours.")
        member = session.member
        try:
            shown = shown_preferences(cls.preferences, member)
            values = model_forms.parse(cls.preferences, form, shown)
            app.store.save_preferences(member, member.id, cls.preferences, **values)
        except AccountsError as exc:
            return show_module(request, name, (str(exc),), 400)
        return kit.redirect(f"/modules/{name}#yours", "Saved.")

    @router.post("/modules/{name}/roles", response_class=HTMLResponse)
    async def save_roles(request: Request, name: str) -> Response:
        """MP5: which roles may use a module: into the draft, for themi.toml at the restart."""
        session, form = await kit.checked(request, admin=True)
        known = available_modules()
        if name not in known:
            return kit.redirect("/modules", f"There's no module called {name}.")
        planner = portal().planner()
        before = planner.draft.switches()
        changed = []
        for role in sorted(planner.roles()):
            allowed = form.get(f"role_{role}") == "1"
            if planner.may_use(role, name) != allowed:
                planner.let_use(role, name, allowed)
                changed.append(f"{role} {'may' if allowed else 'may not'}")
        if not changed:
            return kit.redirect(f"/modules/{name}#roles", "Nothing to change.")
        title = known[name].title or name
        what = f"who can use {title}: {', '.join(changed)}"
        portal().save(planner, session.member, what, before)
        return kit.redirect(
            f"/modules/{name}#roles", f"Saved: {what}. It changes when Themi restarts."
        )

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
            if change.kept:
                return kit.redirect(f"/modules/{name}", change.kept[0][1])
            return kit.redirect(f"/modules/{name}", "Nothing to change.")
        extras = offers(name, planner, change) if on else []
        if (len(names) > 1 or change.spare or change.kept or extras) and form.get(
            "confirmed"
        ) != "1":
            view = overview(kit)
            card = view.card(name, app.services)
            return sheet(
                request,
                session,
                view,
                heading=f"Turn {'on' if on else 'off'} {card.title}?",
                action=f"/modules/{name}/switch",
                on=on,
                needed=[n for n in names if n != name],
                subject=card.title,
                offered=[Offer(view.card(n, app.services), "spare", True) for n in change.spare]
                + [Offer(view.card(n, app.services), "add", False, why) for n, why in extras],
                offered_words=(
                    "These build on it or make it better: tick any to turn on as well"
                    if on
                    else "No longer needed: on only for what's going"
                ),
                kept=change.kept,
                button=f"Yes, turn {'them' if len(names) > 1 else 'it'} {'on' if on else 'off'}",
                back=f"/modules/{name}",
                back_field=str(form.get("back", "")),
            )
        before = planner.draft.switches()
        added = [n for n, _ in extras if form.get(f"add_{n}") == "1"]
        if added:
            change = planner.turn_on_many([name, *added])
            names = change.on
        planner.apply(change)
        spare = [n for n in change.spare if form.get(f"spare_{n}") == "1"]
        if spare:
            planner.apply(planner.turn_off_many(spare))
        titles = [known[n].title or n for n in (*names, *spare)]
        what = f"turned {'on' if on else 'off'} {', '.join(titles)}"
        portal().save(planner, session.member, what, before)
        back = f"/modules/{name}"
        if form.get("back") == "list":  # MP6: a card's switch goes back to its card
            back = f"/modules#module-{name}"
        elif str(form.get("back", "")) in known:  # MP7: from another module's page
            back = f"/modules/{form.get('back')}#works-with"
        return kit.redirect(back, f"Saved: {what}. It changes when Themi restarts.")

    def offers(name: str, planner: Planner, change: Change) -> list[tuple[str, str]]:
        """MP3: what to offer with `name` turned on, unticked: its add-ons (the modules shown
        under it on the list), then what it does more with (`optional`); none that
        are on, or coming on with it."""
        known = planner.known
        cls = known[name]
        coming = set(planner.desired()) | set(change.on)
        own = members(group_of(cls), known)
        add_ons = [  # shown under it on the list
            n for n in own if parent_in_group(n, own, known) == name and n not in coming
        ]
        better = [n for n in cls.optional if n in known and n not in coming and n not in add_ons]
        by_title = sorted(add_ons, key=lambda n: (known[n].title or n).lower())
        return [(n, "Builds on it") for n in by_title] + [
            (n, "It does more with it") for n in better
        ]

    # ----- MP2: a group at once -------------------------------------------------------------

    def find_group(group_id: str) -> ModuleGroup | None:
        return next(
            (g for g in known_groups(available_modules().values()) if g.id == group_id), None
        )

    @router.get("/modules/group/{group_id}", response_class=HTMLResponse)
    def group_sheet(request: Request, group_id: str, to: str = "on") -> Response:
        session = kit.admin(request)
        group = find_group(group_id)
        if group is None:
            return kit.redirect("/modules", "There's no such group.")
        view = overview(kit)
        known = view.known
        planner = portal().planner(view.draft)
        desired = set(planner.desired())
        names = members(group, known)
        on = to != "off"
        if on:
            ticked = [n for n in starter(group, known) if n not in desired]
            picks = [
                Pick(
                    view.card(n, app.services),
                    n in ticked or n in desired,
                    n in desired,
                    _note(known[n]),
                )
                for n in names
            ]
            change = planner.turn_on_many(ticked)
            needed = [n for n in change.on if n not in names]
            kept: tuple[tuple[str, str], ...] = ()
            offered: list[Offer] = []
        else:
            ticked = [n for n in names if n in desired]
            picks = [Pick(view.card(n, app.services), True, False) for n in ticked]
            change = planner.turn_off_many(ticked)
            needed = [n for n in change.off if n not in names]
            kept = change.kept
            offered = [Offer(view.card(n, app.services), "spare", True) for n in change.spare]
        if not ticked and not (on and any(not p.fixed for p in picks)):
            words = "is on already" if on else "has nothing on"
            return kit.redirect(f"/modules#group-{group.id}", f"{group.title} {words}.")
        return sheet(
            request,
            session,
            view,
            heading=f"Turn {'on' if on else 'off'} {group.title}?",
            action=f"/modules/group/{group.id}/switch",
            on=on,
            picks=picks,
            needed=needed,
            offered=offered,
            offered_words="No longer needed: on only for what's going",
            kept=kept,
            button=f"Turn {'on' if on else 'off'} what's ticked",
            back=f"/modules#group-{group.id}",
        )

    @router.post("/modules/group/{group_id}/switch", response_class=HTMLResponse)
    async def group_switch(request: Request, group_id: str) -> Response:
        session, form = await kit.checked(request, admin=True)
        group = find_group(group_id)
        if group is None:
            return kit.redirect("/modules", "There's no such group.")
        known = available_modules()
        planner = portal().planner()
        on = form.get("to") == "on"
        picked = [n for n in members(group, known) if form.get(f"pick_{n}") == "1"]
        change = planner.turn_on_many(picked) if on else planner.turn_off_many(picked)
        names = list(change.on if on else change.off)
        spare = [n for n in change.spare if form.get(f"spare_{n}") == "1"]
        if not names and not spare:
            return kit.redirect(f"/modules#group-{group.id}", "Nothing to change.")
        before = planner.draft.switches()
        planner.apply(change)
        if spare:
            planner.apply(planner.turn_off_many(spare))
        every = [*names, *spare]
        titles = ", ".join(known[n].title or n for n in every)
        count = f"{len(every)} module{'s' if len(every) != 1 else ''}"
        what = f"turned {'on' if on else 'off'} {group.title}: {count} ({titles})"
        portal().save(planner, session.member, what, before)
        return kit.redirect(
            f"/modules#group-{group.id}", f"Saved: {what}. It changes when Themi restarts."
        )

    def sheet(
        request: Request,
        session: Session,
        view: Overview,
        *,
        needed: list[str],
        kept: tuple[tuple[str, str], ...] = (),
        **values: Any,
    ) -> HTMLResponse:
        return kit.with_flash(
            request,
            "module_sheet.html",
            session,
            needed=[view.card(n, app.services) for n in needed],
            kept=[(view.card(n, app.services), why) for n, why in kept],
            **{
                "picks": [],
                "offered": [],
                "offered_words": "",
                "subject": "",
                "back_field": "",
                **values,
            },
        )

    @router.post("/modules/undo-last", response_class=HTMLResponse)
    async def undo_last(request: Request) -> Response:
        session, _ = await kit.checked(request, admin=True)
        what = portal().undo_last(session.member)
        if what is None:
            return kit.redirect("/modules", "There's no switch to undo.")
        return kit.redirect("/modules", f"Undone: {what}.")

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
                by_group=template_by_group(switch, known),  # MP7
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
