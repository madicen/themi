"""F56a (Michael's bug #246, "open in Gmail should open the app"): the page behind an email
notice's [Open in Gmail].

Telegram opens a button's link in its own browser, where Gmail on the web never hands over
to the app, and a button can't carry the app's own `googlegmail://` link. So the button
comes here (`email_buttons.open_link`), signed, with no sign-in (Telegram's browser may not
send a cookie), and the page picks by the phone:

- iPhone/iPad: the Gmail app's link for the thread; if the page is still showing after a
  moment, a button for the app and one for the web, with the sender and subject.
- Android: an intent for the Gmail app, falling back to the web link.
- Anything else (a computer, Telegram Desktop): straight to Gmail on the web.

F58a (bug #247): on Michael's iPhone the Gmail app said "Unable to understand the link" to
`googlegmail:///cv=<thread>`. The app's links for one email are undocumented, so nothing is
guessed in the open page any more: it uses the form the household chose ("Gmail app link on
iPhone", `EmailLinkSettings`), which is the inbox until one is proven. The try-out page
(`/open/email/<id>/try`) lists every candidate form as a button, so a tap on the phone shows
which one opens the email. The candidates are guesses gathered from what people report
working, not anything Google publishes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar, Literal
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import Field

from themi.accounts.household import HouseholdSettings
from themi.storage.db import Database
from themi.web.kit import Kit
from themi_google.connectors.gmail.parse import web_link
from themi_google.email_buttons import GONE_TEXT, OPEN_PATH, OPEN_PURPOSE

IOS_APP_LINK = "googlegmail://"  # the inbox: the one link the app is known to take

# F58a: the forms of the Gmail app's link for one email, by the name the setting shows.
THREAD, THREAD_DECIMAL = "Thread link", "Thread link (decimal)"
SEARCH, SEARCH_SLASHES, INBOX = "Search link", "Search link (three slashes)", "The inbox"
IphoneLink = Literal[
    "The inbox",
    "Thread link",
    "Thread link (decimal)",
    "Search link",
    "Search link (three slashes)",
]
FORMS: dict[str, str] = {
    THREAD: "googlegmail:///cv={thread}/accountId={account}&create-new-tab",
    THREAD_DECIMAL: "googlegmail:///cv={decimal}/accountId={account}&create-new-tab",
    SEARCH: "googlegmail://search?q=rfc822msgid:{msgid}",
    SEARCH_SLASHES: "googlegmail:///search?q=rfc822msgid:{msgid}",
    INBOX: IOS_APP_LINK,
}
TRY_PATH = "/try"


class EmailLinkSettings(HouseholdSettings):
    """F58a: which form of the Gmail app's link the iPhone gets, and the accounts' order in
    the app (its `accountId` is the account's place there)."""

    module: ClassVar[str] = "email_triage"
    gmail_iphone_link: IphoneLink = Field(
        INBOX,
        description="How [Open in Gmail] opens an email in the Gmail app on an iPhone. The "
        "inbox always works; pick another once the try-out page shows it opens the email.",
    )
    gmail_app_order: str = Field(
        "",
        description="The Gmail addresses in the order the Gmail app on the iPhone lists "
        "them, separated by commas. Blank: the order they were linked in.",
    )


@dataclass(frozen=True)
class Candidate:
    label: str
    link: str


ANDROID_APP_LINK = (
    "intent:#Intent;action=android.intent.action.MAIN;"
    "category=android.intent.category.APP_EMAIL;package=com.google.android.gm;"
    "S.browser_fallback_url={fallback};end"
)
_IOS = re.compile(r"iPhone|iPad|iPod")
_ANDROID = re.compile(r"Android")
_THREAD = re.compile(r"^[0-9A-Za-z_-]{1,64}$")  # Gmail's are hex; nothing to escape


def phone(user_agent: str) -> str:
    """The phone from a browser's User-Agent: "ios", "android" or "" (anything else)."""
    if _IOS.search(user_agent):
        return "ios"
    if _ANDROID.search(user_agent):
        return "android"
    return ""


def message_id(header: str | None) -> str:
    """A Message-ID header without its angle brackets, URL-encoded for a search link."""
    return quote(str(header or "").strip().strip("<>"), safe="")


def account_place(db: Database, settings: EmailLinkSettings, address: str) -> int:
    """The account's place in the Gmail app (1, 2, ...): where the setting lists it, else
    its place among the linked Gmail accounts, oldest first."""
    said = [a.strip().lower() for a in settings.gmail_app_order.split(",") if a.strip()]
    if address.lower() in said:
        return said.index(address.lower()) + 1
    linked = [
        str(r["address"]).lower()
        for r in db.query(
            "SELECT address FROM linked_accounts WHERE provider = 'gmail' ORDER BY id"
        )
    ]
    return linked.index(address.lower()) + 1 if address.lower() in linked else 1


def app_link(form: str, thread: str, header: str | None, account: int) -> str:
    """The Gmail app's link for one email in `form`, or the inbox's when it can't be built
    (no thread id it would take, no Message-ID kept)."""
    if form in (THREAD, THREAD_DECIMAL):
        if not _THREAD.match(thread):
            return IOS_APP_LINK
        if form == THREAD_DECIMAL:
            try:
                return FORMS[form].format(decimal=int(thread, 16), account=account)
            except ValueError:
                return IOS_APP_LINK
        return FORMS[form].format(thread=thread, account=account)
    if form in (SEARCH, SEARCH_SLASHES):
        msgid = message_id(header)
        return FORMS[form].format(msgid=msgid) if msgid else IOS_APP_LINK
    return IOS_APP_LINK


def candidates(thread: str, header: str | None) -> list[Candidate]:
    """Every link the try-out page offers, numbered as F58a's prompt lists them."""
    found: list[Candidate] = []

    def add(form: str, account: int | None = None) -> None:
        link = app_link(form, thread, header, account or 1)
        if link == IOS_APP_LINK and form != INBOX:
            return  # this one can't be built for this email
        where = f", account {account}" if account else ""
        found.append(Candidate(f"{len(found) + 1}. {form}{where}", link))

    add(THREAD, 1)
    add(THREAD, 2)
    add(THREAD_DECIMAL, 1)
    add(SEARCH)
    add(SEARCH_SLASHES)
    add(INBOX)
    return found


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def gone(request: Request) -> HTMLResponse:
        return kit.page(request, "message.html", 404, title="Not here", body=GONE_TEXT)

    def email(email_id: int, s: str) -> Any:
        if not app.services.store.cipher.signed(OPEN_PURPOSE, str(email_id), s):
            return None
        return app.db.one(
            "SELECT e.gmail_id, e.thread_id, e.message_id_header, e.from_name, "
            "e.from_address, e.subject, a.address "
            "FROM emails e JOIN linked_accounts a ON a.id = e.account_id "
            "WHERE e.id = ?",
            (email_id,),
        )  # None too when an account unlinked took its emails with it

    @router.get(OPEN_PATH + "{email_id:int}", response_class=HTMLResponse)
    def open_email(request: Request, email_id: int, s: str = "") -> Response:
        row = email(email_id, s)
        if row is None:
            return gone(request)
        web = web_link(row["address"], row["gmail_id"])
        kind = phone(request.headers.get("user-agent", ""))
        if not kind:
            return RedirectResponse(web, status_code=303)
        thread = str(row["thread_id"] or row["gmail_id"])
        if kind == "ios":
            chosen = app.services.store.household(EmailLinkSettings)
            place = account_place(app.db, chosen, str(row["address"]))
            opens = app_link(chosen.gmail_iphone_link, thread, row["message_id_header"], place)
            inbox = IOS_APP_LINK
        else:
            opens = inbox = ANDROID_APP_LINK.format(fallback=quote(web, safe=""))
        return kit.page(
            request,
            "open_email.html",
            app_link=opens,
            inbox_link=inbox,
            web_link=web,
            sender=row["from_name"] or row["from_address"],
            subject=row["subject"] or "(no subject)",
            address=row["address"],
        )

    @router.get(OPEN_PATH + "{email_id:int}" + TRY_PATH, response_class=HTMLResponse)
    def try_links(request: Request, email_id: int, s: str = "") -> Response:
        """F58a: every candidate link as a button, to find on the phone which one opens it."""
        row = email(email_id, s)
        if row is None:
            return gone(request)
        thread = str(row["thread_id"] or row["gmail_id"])
        return kit.page(
            request,
            "open_email_try.html",
            candidates=candidates(thread, row["message_id_header"]),
            sender=row["from_name"] or row["from_address"],
            subject=row["subject"] or "(no subject)",
            address=row["address"],
        )

    return router
