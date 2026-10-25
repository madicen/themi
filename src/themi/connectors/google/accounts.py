"""Google accounts in Themi: who may sign in, linked Gmail accounts, access tokens.

- Sign-in: Google's verified address must be a member's sign-in address.
- Linking: a member can link any number of Gmail accounts. Linking an address
  they already linked just stores the new refresh token. An address linked by
  someone else is refused. If the member has no sign-in address yet, the first
  address they link becomes it: linking proved they own it.
- Access tokens are refreshed on demand and cached in memory until a minute
  before they expire. A refresh token Google no longer accepts disables the
  account until it's linked again.
- Unlinking revokes the token at Google, then deletes the account (and, through
  the database, everything stored for it).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from themi import clock
from themi.accounts import SYSTEM, AccountStore, Actor, LinkedAccount, Member
from themi.connectors.google.oauth import (
    GMAIL_SCOPE,
    AccessToken,
    GoogleOAuth,
    Grant,
    OAuthError,
    TokenRevoked,
)
from themi.storage.secrets import Secret

log = logging.getLogger(__name__)

EARLY_REFRESH = timedelta(minutes=1)
CALLBACK_PATH = "/auth/google/callback"


@dataclass(frozen=True)
class Unlinked:
    address: str
    revoked: bool  # False: Google couldn't be reached, so access may still be listed there


class GoogleAccounts:
    def __init__(self, store: AccountStore, oauth: GoogleOAuth) -> None:
        self.store = store
        self.oauth = oauth
        self._tokens: dict[int, AccessToken] = {}
        # Called after a link succeeds: (account, newly linked rather than re-linked).
        self.link_listeners: list[Callable[[LinkedAccount, bool], Awaitable[None]]] = []

    @staticmethod
    def redirect_uri(site_url: str) -> str:
        return f"{site_url.rstrip('/')}{CALLBACK_PATH}"

    # ----- sign-in ------------------------------------------------------------

    def member_for(self, grant: Grant) -> Member:
        if not grant.email or not grant.email_verified:
            raise OAuthError("Google didn't confirm that address, so it can't sign in here.")
        member = self.store.member_by_email(grant.email)
        if member is None:
            log.info("Refused Google sign-in for an address that isn't a member's")
            raise OAuthError(
                "That Google account isn't one of the family's sign-in addresses. An admin can "
                "add it on the Family page, or /site in Telegram sends a sign-in link."
            )
        return member

    # ----- linking ------------------------------------------------------------

    async def link(self, grant: Grant) -> LinkedAccount:
        if grant.purpose != "link" or grant.member_id is None:
            raise OAuthError("That wasn't a request to link an account.")
        member = self.store.get_member(grant.member_id)
        if GMAIL_SCOPE not in grant.scopes or grant.refresh_token is None:
            if grant.refresh_token is not None:
                await self.revoke_quietly(grant.refresh_token)
            raise OAuthError(
                "Gmail access wasn't granted, so nothing was linked. Linking again and leaving "
                "the Gmail box ticked works."
            )
        if not grant.email or not grant.email_verified:
            await self.revoke_quietly(grant.refresh_token)
            raise OAuthError("Google didn't confirm that address, so nothing was linked.")
        existing = self.store.linked_account_by_address("gmail", grant.email)
        if existing is not None and existing.member_id != member.id:
            await self.revoke_quietly(grant.refresh_token)
            raise OAuthError(f"{grant.email} is already linked by someone else in the family.")
        if existing is not None:
            self.store.replace_refresh_token(existing.id, grant.refresh_token)
            self.store.set_linked_account_enabled(existing.id, True)
            account = self.store.get_linked_account(existing.id)
        else:
            account = self.store.add_linked_account(
                member, member.id, "gmail", grant.email, grant.refresh_token
            )
        self._tokens[account.id] = grant.access
        if member.email is None and self.store.member_by_email(grant.email) is None:
            self.store.set_email(SYSTEM, member.id, grant.email)
        log.info("Linked a Gmail account (%s) for member %s", account.id, member.id)
        for listener in self.link_listeners:
            try:
                await listener(account, existing is None)
            except Exception:
                log.exception("A link listener failed for account %s", account.id)
        return account

    async def unlink(self, actor: Actor, account_id: int) -> Unlinked:
        account = self.store.get_linked_account(account_id)
        token = self.store.refresh_token(account_id)
        self.store.remove_linked_account(actor, account_id)  # checks it's theirs first
        self._tokens.pop(account_id, None)
        try:
            await self.oauth.revoke(token)
            revoked = True
        except OAuthError:
            log.warning("Couldn't revoke the token for unlinked account %s at Google", account_id)
            revoked = False
        return Unlinked(account.address, revoked)

    async def revoke_quietly(self, token: Secret) -> None:
        """Revoke a token Themi isn't keeping; a failure is only logged."""
        try:
            await self.oauth.revoke(token)
        except OAuthError:
            log.warning("Couldn't revoke a token Themi isn't keeping")

    # ----- access tokens ------------------------------------------------------

    def forget_access_token(self, account_id: int) -> None:
        """Drop a cached token Google just refused (a 401), so the next call refreshes."""
        self._tokens.pop(account_id, None)

    async def access_token(self, account_id: int) -> Secret:
        """A current access token for a linked account, refreshing it when needed."""
        cached = self._tokens.get(account_id)
        if cached is not None and cached.expires_at - EARLY_REFRESH > clock.now():
            return cached.token
        try:
            fresh = await self.oauth.refresh(self.store.refresh_token(account_id))
        except TokenRevoked:
            self._tokens.pop(account_id, None)
            self.store.set_linked_account_enabled(account_id, False)
            log.warning("Google no longer accepts linked account %s; disabled it", account_id)
            raise
        self._tokens[account_id] = fresh
        return fresh.token
