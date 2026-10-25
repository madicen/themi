"""Google OAuth and linked accounts, against the fake Google over real HTTP."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from tests.fakes.google_oauth import CLIENT_ID, REDIRECT_URI, FakeGoogle
from tests.fixtures.family import SeededFamily
from themi import clock
from themi.accounts import SYSTEM, PermissionDenied
from themi.connectors.google import (
    CALENDAR_SCOPE,
    CALENDAR_SCOPES,
    GMAIL_SCOPE,
    GoogleAccounts,
    GoogleOAuth,
    Grant,
    OAuthError,
    TokenRevoked,
)
from themi.connectors.google.oauth import code_challenge


@pytest.fixture
def oauth(family: SeededFamily, fake_google: FakeGoogle) -> GoogleOAuth:
    clock.freeze(clock.now())
    return GoogleOAuth(family.db, family.store.cipher, fake_google.config())


@pytest.fixture
def accounts(family: SeededFamily, oauth: GoogleOAuth) -> GoogleAccounts:
    return GoogleAccounts(family.store, oauth)


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def link_flow(
    oauth: GoogleOAuth, fake_google: FakeGoogle, member, address: str, **consent
) -> Grant:
    url = oauth.authorization_url("link", REDIRECT_URI, member)
    callback = query(fake_google.consent(url, address, **consent))
    return await oauth.complete(callback["state"], callback["code"], REDIRECT_URI)


# ----- the flow ----------------------------------------------------------------


def test_the_authorize_url_asks_for_the_right_things(
    oauth: GoogleOAuth, family: SeededFamily
) -> None:
    link = query(oauth.authorization_url("link", REDIRECT_URI, family.erin))
    assert link["client_id"] == CLIENT_ID and link["redirect_uri"] == REDIRECT_URI
    assert link["scope"].split() == ["openid", "email", GMAIL_SCOPE, *CALENDAR_SCOPES]
    assert GMAIL_SCOPE == "https://www.googleapis.com/auth/gmail.modify"
    assert CALENDAR_SCOPE == "https://www.googleapis.com/auth/calendar.events"
    assert (link["access_type"], link["prompt"]) == ("offline", "consent")
    assert link["code_challenge_method"] == "S256" and len(link["state"]) >= 32

    signin = query(oauth.authorization_url("signin", REDIRECT_URI))
    assert signin["scope"] == "openid email" and "access_type" not in signin


def test_the_pkce_challenge_is_rfc7636() -> None:
    # RFC 7636 appendix B's example.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_state_is_stored_hashed_and_the_verifier_encrypted(
    oauth: GoogleOAuth, family: SeededFamily
) -> None:
    state = query(oauth.authorization_url("signin", REDIRECT_URI))["state"]
    row = family.db.one("SELECT * FROM oauth_states")
    assert row is not None
    assert row["state_hash"] != state and state not in str(row)
    assert family.store.cipher.decrypt(row["code_verifier"]).reveal()  # decrypts, isn't plain


async def test_full_link_flow(
    oauth: GoogleOAuth, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    grant = await link_flow(oauth, fake_google, family.erin, "Erin@Gmail.com")
    assert (grant.purpose, grant.member_id) == ("link", family.erin.id)
    assert grant.email == "erin@gmail.com" and grant.email_verified
    assert GMAIL_SCOPE in grant.scopes and grant.refresh_token is not None
    assert fake_google.live_refresh_tokens("erin@gmail.com") == [grant.refresh_token.reveal()]


async def test_a_state_works_once(oauth: GoogleOAuth, fake_google: FakeGoogle) -> None:
    url = oauth.authorization_url("signin", REDIRECT_URI)
    callback = query(fake_google.consent(url, "erin@example.com"))
    await oauth.complete(callback["state"], callback["code"], REDIRECT_URI)
    with pytest.raises(OAuthError, match="expired or was already used"):
        await oauth.complete(callback["state"], callback["code"], REDIRECT_URI)


async def test_unknown_and_expired_states_are_rejected(
    oauth: GoogleOAuth, fake_google: FakeGoogle
) -> None:
    url = oauth.authorization_url("signin", REDIRECT_URI)
    callback = query(fake_google.consent(url, "erin@example.com"))
    with pytest.raises(OAuthError):
        await oauth.complete("forged-state", callback["code"], REDIRECT_URI)
    clock.advance(timedelta(minutes=10, seconds=1))
    with pytest.raises(OAuthError, match="expired"):
        await oauth.complete(callback["state"], callback["code"], REDIRECT_URI)


async def test_a_pkce_mismatch_is_rejected(oauth: GoogleOAuth, fake_google: FakeGoogle) -> None:
    # A code issued for one attempt, brought back with another attempt's state (and so
    # its verifier): Google refuses the exchange.
    first = oauth.authorization_url("signin", REDIRECT_URI)
    second = query(oauth.authorization_url("signin", REDIRECT_URI))
    stolen_code = query(fake_google.consent(first, "erin@example.com"))["code"]
    with pytest.raises(OAuthError, match="turned that sign-in down"):
        await oauth.complete(second["state"], stolen_code, REDIRECT_URI)
    assert fake_google.state.token_requests[-1]["code_verifier"]


async def test_the_callback_must_return_to_the_same_address(
    oauth: GoogleOAuth, fake_google: FakeGoogle
) -> None:
    url = oauth.authorization_url("signin", REDIRECT_URI)
    callback = query(fake_google.consent(url, "erin@example.com"))
    with pytest.raises(OAuthError, match="wrong address"):
        await oauth.complete(callback["state"], callback["code"], "http://elsewhere.test/cb")


# ----- sign-in -----------------------------------------------------------------


async def signin_grant(oauth: GoogleOAuth, fake_google: FakeGoogle, address: str) -> Grant:
    url = oauth.authorization_url("signin", REDIRECT_URI)
    callback = query(fake_google.consent(url, address))
    return await oauth.complete(callback["state"], callback["code"], REDIRECT_URI)


async def test_only_members_addresses_sign_in(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    family.store.set_email(SYSTEM, family.erin.id, "erin@example.com")
    grant = await signin_grant(oauth, fake_google, "ERIN@example.com")
    assert accounts.member_for(grant).id == family.erin.id
    stranger = await signin_grant(oauth, fake_google, "stranger@example.com")
    with pytest.raises(OAuthError, match="isn't one of the family's"):
        accounts.member_for(stranger)


async def test_an_unverified_address_is_refused(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    family.store.set_email(SYSTEM, family.erin.id, "erin@example.com")
    fake_google.add_account("erin@example.com", verified=False)
    grant = await signin_grant(oauth, fake_google, "erin@example.com")
    with pytest.raises(OAuthError, match="didn't confirm"):
        accounts.member_for(grant)


def test_sign_in_addresses_are_unique_and_admin_set(family: SeededFamily) -> None:
    family.store.set_email(family.erin, family.erin.id, "erin@example.com")
    with pytest.raises(Exception, match="already belongs to Erin"):
        family.store.set_email(SYSTEM, family.husband.id, "Erin@Example.com")
    with pytest.raises(PermissionDenied):
        family.store.set_email(family.husband, family.husband.id, "him@example.com")
    assert family.store.set_email(SYSTEM, family.erin.id, "").email is None


# ----- linking -----------------------------------------------------------------


async def test_a_member_can_link_several_accounts(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    for address in ("erin@gmail.com", "erin.rentals@gmail.com", "erin@work.example"):
        await accounts.link(await link_flow(oauth, fake_google, family.erin, address))
    linked = [a.address for a in family.store.linked_accounts(family.erin.id)]
    assert linked == ["erin@gmail.com", "erin.rentals@gmail.com", "erin@work.example"]
    # Her first linked address became her sign-in address.
    assert family.store.get_member(family.erin.id).email == "erin@gmail.com"


async def test_refresh_tokens_are_encrypted_at_rest(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    grant = await link_flow(oauth, fake_google, family.erin, "erin@gmail.com")
    assert grant.refresh_token is not None
    account = await accounts.link(grant)
    raw = family.db.one("SELECT refresh_token FROM linked_accounts WHERE id = ?", (account.id,))
    assert raw is not None
    assert grant.refresh_token.reveal().encode() not in bytes(raw["refresh_token"])
    assert family.store.refresh_token(account.id) == grant.refresh_token


async def test_relinking_replaces_the_token(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    first = await accounts.link(await link_flow(oauth, fake_google, family.erin, "erin@gmail.com"))
    second_grant = await link_flow(oauth, fake_google, family.erin, "erin@gmail.com")
    second = await accounts.link(second_grant)
    assert second.id == first.id
    assert family.store.refresh_token(first.id) == second_grant.refresh_token


async def test_an_address_linked_by_someone_else_is_refused(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    await accounts.link(await link_flow(oauth, fake_google, family.erin, "shared@gmail.com"))
    grant = await link_flow(oauth, fake_google, family.husband, "shared@gmail.com")
    with pytest.raises(OAuthError, match="already linked by someone else"):
        await accounts.link(grant)
    assert grant.refresh_token is not None
    assert grant.refresh_token.reveal() in fake_google.state.revoked  # not left dangling


async def test_unticking_gmail_links_nothing(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    grant = await link_flow(
        oauth, fake_google, family.erin, "erin@gmail.com", scopes=("openid", "email")
    )
    with pytest.raises(OAuthError, match="Gmail access wasn't granted"):
        await accounts.link(grant)
    assert family.store.linked_accounts(family.erin.id) == []
    assert fake_google.live_refresh_tokens("erin@gmail.com") == []


# ----- tokens and unlinking ----------------------------------------------------


async def test_access_tokens_refresh_when_due(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    account = await accounts.link(
        await link_flow(oauth, fake_google, family.erin, "erin@gmail.com")
    )
    first = await accounts.access_token(account.id)
    assert await accounts.access_token(account.id) == first  # cached
    refreshes = len(fake_google.state.token_requests)
    clock.advance(timedelta(minutes=59))
    fresh = await accounts.access_token(account.id)
    assert fresh != first and len(fake_google.state.token_requests) == refreshes + 1
    assert fake_google.state.token_requests[-1]["grant_type"] == "refresh_token"


async def test_a_revoked_refresh_token_disables_the_account(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    account = await accounts.link(
        await link_flow(oauth, fake_google, family.erin, "erin@gmail.com")
    )
    fake_google.revoke_everything_for("erin@gmail.com")
    clock.advance(timedelta(hours=2))
    with pytest.raises(TokenRevoked):
        await accounts.access_token(account.id)
    assert not family.store.get_linked_account(account.id).enabled
    await accounts.link(await link_flow(oauth, fake_google, family.erin, "erin@gmail.com"))
    assert family.store.get_linked_account(account.id).enabled  # linking again fixes it


async def test_unlinking_revokes_at_google_and_forgets_the_account(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    grant = await link_flow(oauth, fake_google, family.erin, "erin@gmail.com")
    account = await accounts.link(grant)
    assert grant.refresh_token is not None
    result = await accounts.unlink(family.erin, account.id)
    assert result.revoked and result.address == "erin@gmail.com"
    assert fake_google.state.revoked == [grant.refresh_token.reveal()]
    assert fake_google.live_refresh_tokens("erin@gmail.com") == []
    assert family.store.linked_accounts(family.erin.id) == []


async def test_only_the_owner_can_unlink(
    oauth: GoogleOAuth, accounts: GoogleAccounts, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    account = await accounts.link(
        await link_flow(oauth, fake_google, family.erin, "erin@gmail.com")
    )
    with pytest.raises(PermissionDenied):
        await accounts.unlink(family.husband, account.id)
    assert fake_google.state.revoked == []


async def test_unlinking_still_forgets_when_google_is_down(
    oauth: GoogleOAuth, fake_google: FakeGoogle, family: SeededFamily
) -> None:
    accounts = GoogleAccounts(family.store, oauth)
    account = await accounts.link(
        await link_flow(oauth, fake_google, family.erin, "erin@gmail.com")
    )
    down = GoogleOAuth(
        family.db,
        family.store.cipher,
        replace(fake_google.config(), revoke_url="http://127.0.0.1:9/revoke"),
    )
    result = await GoogleAccounts(family.store, down).unlink(family.erin, account.id)
    assert not result.revoked
    assert family.store.linked_accounts(family.erin.id) == []
