"""The welcome page: Home for an admin while a Themi is being set up.

Only on a Themi set up through its claim code (SP7a): an install from before then (the
family's) never sees it. A numbered list of what makes a Themi useful, each step ticked as
soon as it's true (none is ticked by hand). It's Home until every step that isn't optional
is done, or an admin says they're done ("I'm done"), and then Home is the dashboard; what's
left of the setup stays on its "Finish setting up" card.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from themi.accounts import Member
from themi.accounts.claim import Claim
from themi.accounts.passkeys import Passkeys
from themi.modules.store import DraftStore

DONE_KEY = "welcome_done"  # in meta: an admin said they're done with it
KEYLESS_AI = frozenset({"ollama", "lm_studio", "openai_compat"})  # your own server: no key
SITE_LINK_CHANNELS = frozenset({"telegram", "slack"})  # where /site sends a sign-in link


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    detail: str
    done: bool
    href: str = ""
    action: str = ""  # the button's words, while it isn't done
    optional: bool = False
    after: str = ""  # the button's words once it's done, if it keeps one


def steps(app: Any, member: Member, words: dict[str, str]) -> list[Step]:
    report = app.services.start_report
    config = app.services.instance_config
    draft = DraftStore(app.db).get()
    waiting = draft is not None and not draft.is_empty()
    signs_in = bool(set(member.channels) & SITE_LINK_CHANNELS)
    chats = [s.name for s in report.modules.values() if s.kind == "channel" and s.state == "on"]
    out = [
        Step(
            "claim",
            "Claim it and save its key",
            "You're its first admin. Keep the key somewhere safe: backups need it.",
            True,
        ),
        Step(
            "passkey",
            "Add a passkey, so you can sign in again later",
            "Your phone or computer's fingerprint, face or PIN signs you in."
            if not signs_in
            else "You sign in with the link Themi sends when you send /site.",
            signs_in or bool(Passkeys(app.store).of(member)),
            "/passkeys",
            "Add",
        ),
        Step(
            "template",
            "Choose what Themi is for",
            "Family, Work, or build your own from here: turn on what you want on Modules.",
            waiting or _changed(config),
            "/modules",
            "Choose",
        ),
        Step(
            "ai",
            "Give it an AI to think with",
            "Add a key on My AI (Gemini has a free tier: a key from aistudio.google.com), "
            "or your own AI server.",
            any(b.has_key or b.kind in KEYLESS_AI for b in app.ai_settings.backends(member.id)),
            "/ai",
            "Set up",
        ),
        Step(
            "chat",
            "Talk to it",
            "The chat here works now. For your phone, add Telegram or Slack on Modules."
            if "web_chat" in chats
            else "Turn on a way to chat on Modules: the website's chat, Telegram or Slack.",
            bool(chats),
            "/chat" if "web_chat" in chats else "/modules",
            "Choose",
            after="Open the chat",
        ),
        Step(
            "people",
            "Invite the people who'll use it",
            f"Each gets a code to pair with, on the {words['family']} page.",
            len(app.store.list_members()) > 1,
            "/family",
            "Invite",
            optional=True,
        ),
    ]
    if waiting:
        out.append(
            Step(
                "restart",
                "Restart to apply your changes",
                "Modules keeps your changes until Themi restarts with them.",
                False,
                "/modules/restart",
                "Restart",
            )
        )
    return out


def shown(app: Any, member: Member, step_list: list[Step]) -> bool:
    """Home is the welcome page for an admin until the steps that matter are done, or an
    admin has said they're done."""
    if not member.is_admin or app.db.scalar("SELECT 1 FROM meta WHERE key = ?", (DONE_KEY,)):
        return False
    if Claim(app.store).claimant() is None:  # not a Themi that began with a claim
        return False
    return not all(s.done for s in step_list if not s.optional)


def ready(step_list: list[Step]) -> bool:
    """Themi can answer here: it has an AI to think with, and the website's chat is on."""
    by_key = {s.key: s for s in step_list}
    return by_key["ai"].done and by_key["chat"].href == "/chat"


def dismiss(app: Any) -> None:
    app.db.execute(
        "INSERT INTO meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO NOTHING", (DONE_KEY,)
    )


def _changed(config: Any) -> bool:
    """Set up past what a new Themi starts with (the empty template and the web chat)."""
    if config is None:
        return True
    return not (
        config.template == "empty"
        and set(config.added) <= {"web_chat"}
        and not config.removed
        and not config.sections
    )
