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
"""

from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from themi.web.kit import Kit
from themi_google.connectors.gmail.parse import web_link
from themi_google.email_buttons import GONE_TEXT, OPEN_PATH, OPEN_PURPOSE

# The Gmail app's link for one conversation. Undocumented: Michael checks it on his iPhone,
# and the Notes say which form opened the thread (the inbox is the fallback).
IOS_THREAD_LINK = "googlegmail:///cv={thread}"
IOS_APP_LINK = "googlegmail://"
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


def routes(kit: Kit) -> APIRouter:
    router = APIRouter()
    app = kit.app

    def gone(request: Request) -> HTMLResponse:
        return kit.page(request, "message.html", 404, title="Not here", body=GONE_TEXT)

    @router.get(OPEN_PATH + "{email_id:int}", response_class=HTMLResponse)
    def open_email(request: Request, email_id: int, s: str = "") -> Response:
        if not app.services.store.cipher.signed(OPEN_PURPOSE, str(email_id), s):
            return gone(request)
        row = app.db.one(
            "SELECT e.gmail_id, e.thread_id, e.from_name, e.from_address, e.subject, "
            "a.address FROM emails e JOIN linked_accounts a ON a.id = e.account_id "
            "WHERE e.id = ?",
            (email_id,),
        )
        if row is None:  # an account unlinked takes its emails with it
            return gone(request)
        web = web_link(row["address"], row["gmail_id"])
        kind = phone(request.headers.get("user-agent", ""))
        if not kind:
            return RedirectResponse(web, status_code=303)
        thread = str(row["thread_id"] or row["gmail_id"])
        if kind == "ios":
            app_link = (
                IOS_THREAD_LINK.format(thread=thread) if _THREAD.match(thread) else IOS_APP_LINK
            )
            inbox = IOS_APP_LINK
        else:
            app_link = inbox = ANDROID_APP_LINK.format(fallback=quote(web, safe=""))
        return kit.page(
            request,
            "open_email.html",
            app_link=app_link,
            inbox_link=inbox,
            web_link=web,
            sender=row["from_name"] or row["from_address"],
            subject=row["subject"] or "(no subject)",
            address=row["address"],
        )

    return router
