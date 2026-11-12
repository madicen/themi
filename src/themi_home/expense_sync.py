"""Expense sheets copied to Google Sheets (EX4a, EX4b).

Themi's database is the truth; a book's Google spreadsheet is a copy Themi writes, through
the person's own linked Google account, with the `drive.file` scope (only files Themi makes).
Writing to it is a side effect, so it goes through the trust tiers: the category "expense
sheet sync", each person's own, asking first to start, and it may become automatic. At Tier
1 a sync is one approval per sheet per day, not one per row.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from themi.accounts import Member
from themi.core import keys
from themi.modules import AccountNeed, Module, ModuleContext, ModuleSetup
from themi_google.connectors.google import DRIVE_FILE_SCOPE, GoogleConfig, ScopeNeed
from themi_google.connectors.gsheets import SheetsClient

if TYPE_CHECKING:
    from themi.accounts.models import LinkedAccount
    from themi.core.services import Services
    from themi_google.connectors.google import GoogleAccounts

log = logging.getLogger(__name__)

CATEGORY = "expense_sheet_sync"
EXECUTOR = "expense_sheet_sync"
SYNC_EVERY = timedelta(minutes=5)


class ExpenseSync:
    def __init__(
        self, services: Services, google: GoogleAccounts | None, config: GoogleConfig | None
    ) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        self.google = google
        self.config = config

    def install(self) -> None:
        self.services.provide(keys.expense_sync, self)

    def ready(self) -> bool:
        return self.google is not None and self.config is not None

    def client(self, account_id: int) -> SheetsClient:
        assert self.google is not None and self.config is not None
        google = self.google
        return SheetsClient(
            self.config.sheets_url,
            lambda: google.access_token(account_id),
            lambda: google.forget_access_token(account_id),
        )

    def accounts_for(self, member: Member) -> list[LinkedAccount]:
        """Their linked Google accounts that may make and write spreadsheets."""
        return [
            a
            for a in self.store.linked_accounts(member.id)
            if a.enabled and a.allows(DRIVE_FILE_SCOPE)
        ]


class ExpenseSyncModule(Module):
    """EX4a: expense sheets kept in step in Google Sheets."""

    name = "expense_sync"
    kind = "connector"
    title = "Expense sheets in Google Sheets"
    summary = "Copies each expense spreadsheet to Google Sheets, kept up to date."
    requires = ("spending",)
    optional = ("google",)
    needs_accounts = AccountNeed(
        "a Google account with Google Drive allowed",
        "/accounts",
        "each person",
        "SELECT 1 FROM linked_accounts WHERE enabled = 1 AND scopes LIKE '%/auth/drive.file%'",
    )
    google_scopes: ClassVar[tuple[ScopeNeed, ...]] = (  # CR18a: only the files Themi makes
        ScopeNeed(
            "expense sheets",
            (DRIVE_FILE_SCOPE,),
            "Google Drive isn't allowed for this account yet. Linking it again lets Themi "
            "keep your expense sheets in Google Sheets (it can open only the files it makes).",
        ),
    )
    migrations = Path(__file__).parent / "expense_sync_schema"

    def __init__(self, config: GoogleConfig | None = None) -> None:
        self.config = config

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        from themi_google.google_settings import GoogleSettings

        return cls(setup.read(GoogleSettings, "google").config())

    def install(self, ctx: ModuleContext) -> None:
        sync = ctx.provide(ExpenseSync(ctx.services, ctx.services.maybe(keys.google), self.config))
        sync.install()
