"""Expense sheets copied to Google Sheets (EX4a, EX4b).

Themi's database is the truth; a book's Google spreadsheet is a copy Themi writes, through
the person's own linked Google account, with the `drive.file` scope (only files Themi makes).
Writing to it is a side effect, so it goes through the trust tiers: the category "expense
sheet sync", each person's own, asking first to start, and it may become automatic.

- When a book is made in chat (or "put the kitchen project in Google Sheets" for one that
  exists), Themi asks which linked Google account, makes the spreadsheet there with a tab
  per sheet, and offers the rule: "Keep this spreadsheet up to date on its own?" [Yes,
  always] [Ask me]. A sheet added to a book that's in Google Sheets is a new tab there,
  under the same rule.
- The sync queue (`expense_sync`) is filled when an entry or a value changes (and with
  entry 0 when a sheet's header or tab changes), and drained every few minutes. Automatic:
  written at once. Asking first: one approval per sheet per day, not one per row; a yes
  covers the rest of that day. Failures back off (1 minute up to 6 hours); after a day of
  them the owner hears once, in words.
- In the sheet: a hidden id column (an update finds its row, never a second one), the
  fields, and a Status column ("Checked", "Filled in by Themi", "Your estimate",
  "Missing"). Each value has its status's colour and a note: its source, how sure as a %,
  and the link. Colour alone is never the only sign. Verifying in Themi changes the
  database first, then the cells.
- A spreadsheet deleted in Google: the book forgets it and says so once; it can be made
  again. A tab deleted there is made again at the next sync, since Themi's database is the
  truth (archiving the sheet in Themi drops its tab). Edits made in Google aren't read back:
  Themi rewrites its own columns and leaves any others alone.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from zoneinfo import ZoneInfo

from themi import clock
from themi.accounts import Member
from themi.autonomy.engine import ExecutionContext
from themi.channels.events import Button, InboundEvent
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.localtime import to_utc_iso
from themi.modules import AccountNeed, Module, ModuleContext, ModuleSetup
from themi_google.connectors.google import DRIVE_FILE_SCOPE, GoogleConfig, ScopeNeed
from themi_google.connectors.gsheets import (
    Cell,
    SheetsAuthError,
    SheetsClient,
    SheetsError,
    SheetsNotFound,
    SheetsRateLimited,
    Tab,
    delete_sheet,
    update_sheet,
)
from themi_home import home_groups
from themi_home.expenses import SOURCE_WORDS, STATUS_WORDS, Book, Entry, Expenses, Field, Sheet

if TYPE_CHECKING:
    from themi.accounts.models import LinkedAccount
    from themi.core.services import Services
    from themi_google.connectors.google import GoogleAccounts
    from themi_home.expense_sheets import ExpenseSheets

log = logging.getLogger(__name__)

CATEGORY = "expense_sheet_sync"
EXECUTOR = "expense_sheet_sync"
CREATE_EXECUTOR = "expense_sheet_create"
SYNC_EVERY = timedelta(minutes=5)
BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
)
TELL_AFTER = timedelta(days=1)  # a day of failures: the owner hears once
BUTTON = "expense_gsheet"
KIND = "expense_gsheet"

# Each status's background: words in the Status column and the note say it too.
COLOURS = {
    "verified": (0.85, 0.94, 0.83),  # green
    "unverified": (1.0, 0.93, 0.76),  # amber
    "user_estimate": (0.82, 0.89, 0.98),  # blue
    "missing": (0.98, 0.84, 0.84),  # red
}

WHICH_TEXT = "Put {book} in Google Sheets? Which account should it live in?"
NO_ACCOUNT_TEXT = (
    "To put {book} in Google Sheets, a Google account with Google Drive allowed is needed: "
    "My accounts on the website links one."
)
MADE_TEXT = "{book} is in Google Sheets now: {link}"
RULE_TEXT = "Keep this spreadsheet up to date on its own?"
ALWAYS_TEXT = "It'll keep itself up to date. (The Rules page can change that.)"
ASK_TEXT = "I'll check with you first, once a day at most for each sheet."
NOT_NOW_TEXT = "Left out of Google Sheets for now."
GONE_TEXT = (
    "The Google spreadsheet for {book} was deleted, so Themi stopped copying it there. "
    'Saying "put {book} in Google Sheets" makes it again.'
)
FAILING_TEXT = (
    "Google Sheets hasn't taken the changes to {book} since yesterday ({why}). Themi keeps "
    "trying, and the website has everything meanwhile."
)


def sheet_link(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"


def entry_status(entry: Entry, fields: list[Field]) -> str:
    """The Status column: the least sure of its values."""
    if entry.missing(fields):
        return "missing"
    statuses = {v.status for v in entry.values.values() if v.value is not None}
    for status in ("user_estimate", "unverified"):
        if status in statuses:
            return status
    return "verified"


def row_cells(entry: Entry, fields: list[Field], link: Any) -> list[Cell]:  # link: Value -> str
    """An entry's cells: each field's value, coloured by its status, with a note saying
    where it came from and how sure; then the Status column, in words."""
    cells = []
    for f in fields:
        value = entry.values.get(f.key)
        if value is None or value.value is None:
            missing = f.critical
            cells.append(
                Cell("", "Missing" if missing else "", COLOURS["missing"] if missing else None)
            )
            continue
        shown: str | float | int
        if f.type == "money":
            shown = round(int(value.value) / 100, 2)
        elif f.type == "number" and isinstance(value.value, int | float):
            shown = value.value
        else:
            shown = str(value.value)
        note = [f"{STATUS_WORDS[value.status]}, from {SOURCE_WORDS[value.source_type]}"]
        if value.confidence is not None:
            note.append(f"{round(value.confidence * 100)}% sure")
        where = link(value)
        if where:
            note.append(where)
        cells.append(Cell(shown, ". ".join(note) + ".", COLOURS[value.status]))
    status = entry_status(entry, fields)
    cells.append(Cell(STATUS_WORDS[status], "", COLOURS[status]))
    return cells


def header(fields: list[Field]) -> list[str]:
    return [*(f.label for f in fields), "Status"]


class ExpenseSync:
    def __init__(
        self, services: Services, google: GoogleAccounts | None, config: GoogleConfig | None
    ) -> None:
        self.services = services
        self.store = services.store
        self.db = services.store.db
        self.google = google
        self.config = config
        self.outbox = services.outbox

    @property
    def expenses(self) -> Expenses:
        found = self.services.maybe(keys.expenses)
        assert found is not None
        return found

    @property
    def sheets(self) -> ExpenseSheets:
        found = self.services.maybe(keys.expense_sheets)
        assert found is not None
        return found

    def install(self) -> None:
        s = self.services
        s.provide(keys.expense_sync, self)
        s.button_handlers[BUTTON] = self.on_button
        s.tools.register(put_in_google_sheets)
        self.expenses.change_listeners.append(self.on_change)
        self.sheets.book_listeners.append(self.on_book)
        self.sheets.tab_listeners.append(self.on_tab)

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

    def link_of(self, book_id: int) -> dict[str, Any] | None:
        """Who and which account copies this book to Google Sheets, while it's there."""
        row = self.db.one("SELECT * FROM expense_book_links WHERE book_id = ?", (book_id,))
        if row is None or not self.expenses.book(book_id).google_spreadsheet_id:
            return None
        return row

    # ----- offering it -------------------------------------------------------------------

    async def on_book(self, member: Member, book: Book) -> None:
        """A book made in chat: offer Google Sheets, when they have an account for it."""
        if self.ready() and self.accounts_for(member):
            await self.offer(member, book, quiet=True)

    async def offer(self, member: Member, book: Book, *, quiet: bool = False) -> str:
        """Ask which account the book's spreadsheet lives in. Returns what was done."""
        if not self.ready():
            raise ToolFailed("Google isn't set up for Themi, so it can't use Google Sheets.")
        accounts = self.accounts_for(member)
        if not accounts:
            if not quiet:
                await self.outbox.send(
                    member, NO_ACCOUNT_TEXT.format(book=book.title), priority=Priority.REPLY
                )
            return "no account"
        buttons = [Button(a.address, BUTTON, {"book": book.id, "account": a.id}) for a in accounts]
        buttons.append(Button("Not now", BUTTON, {"book": book.id, "account": 0}))
        await self.outbox.send(
            member, WHICH_TEXT.format(book=book.title), priority=Priority.REPLY, kind=KIND,
            buttons=buttons,
        )  # fmt: skip
        return "asked"

    async def on_button(self, event: InboundEvent) -> None:
        assert event.button is not None
        member = self.store.get_member(event.member.id)
        payload = event.button.payload
        if "rule" in payload:
            text = ASK_TEXT
            if payload["rule"] == "always" and self.services.rulebook is not None:
                if not self.services.autonomy.is_automatic(CATEGORY, member):
                    self.services.rulebook.grant_automatic(member, CATEGORY)
                text = ALWAYS_TEXT
            if event.button.message_id is not None:
                await self.outbox.edit(member, event.button.message_id, text)
            return
        book = self.expenses.book(int(payload["book"]))
        account_id = int(payload.get("account") or 0)
        if not account_id:
            if event.button.message_id is not None:
                await self.outbox.edit(member, event.button.message_id, NOT_NOW_TEXT)
            return
        if account_id not in {a.id for a in self.accounts_for(member)}:
            return
        outcome = await self.services.autonomy.stage(
            CATEGORY,
            member,
            f"Make {book.title} in Google Sheets",
            {"book": book.id, "account": account_id},
            CREATE_EXECUTOR,
            interactive=True,
            requested=True,  # they picked the account for exactly this
        )
        if event.button.message_id is not None:
            await self.outbox.edit(member, event.button.message_id, outcome.message)
        if outcome.action.status == "done" and not self.services.autonomy.is_automatic(
            CATEGORY, member
        ):
            await self.outbox.send(
                member, RULE_TEXT, priority=Priority.REPLY, kind=KIND,
                buttons=[Button("Yes, always", BUTTON, {"rule": "always"}),
                         Button("Ask me", BUTTON, {"rule": "ask"})],
            )  # fmt: skip

    async def create(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        """The executor: make the book's spreadsheet, a tab per sheet, and write them all.
        Run again (a retry), it finds the spreadsheet made and writes it again."""
        book = self.expenses.book(int(payload["book"]))
        account_id = int(payload["account"])
        client = self.client(account_id)
        tabs = self.expenses.sheets(book.id)
        if book.google_spreadsheet_id is None:
            sid, made = await client.create(book.title, [s.title for s in tabs])
            self.expenses.set_spreadsheet(book.id, sid)
            for sheet, tab in zip(tabs, made, strict=False):
                self.expenses.set_tab_id(sheet.id, tab.id)
        sid = self.expenses.book(book.id).google_spreadsheet_id
        assert sid is not None
        self.db.execute(
            "INSERT OR REPLACE INTO expense_book_links (book_id, member_id, account_id, "
            "made_at) VALUES (?, ?, ?, ?)",
            (book.id, ctx.member.id, account_id, to_utc_iso(clock.now())),
        )
        for sheet in tabs:
            await self.write_sheet(sheet, full=True)
        return MADE_TEXT.format(book=book.title, link=sheet_link(sid))

    # ----- the queue ---------------------------------------------------------------------

    def on_change(self, entry_id: int, sheet_id: int) -> None:
        """An entry (or a sheet: entry 0) changed: write it again, if its book is copied."""
        try:
            sheet = self.expenses.sheet(sheet_id)
        except Exception:
            return
        if self.link_of(sheet.book_id) is None:
            return
        if self.db.one(
            "SELECT 1 FROM expense_sync WHERE entry_id = ? AND sheet_id = ? AND done_at IS NULL "
            "AND attempts = 0",
            (entry_id, sheet_id),
        ):
            return
        now = to_utc_iso(clock.now())
        self.db.execute(
            "INSERT INTO expense_sync (entry_id, sheet_id, wanted_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (entry_id, sheet_id, now, now),
        )

    async def on_tab(self, member: Member, sheet: Sheet) -> None:
        """A sheet added to a book that's in Google Sheets: a new tab there, at the next
        drain (under the same rule)."""
        self.on_change(0, sheet.id)

    def waiting(self, sheet_id: int | None = None) -> list[dict[str, Any]]:
        where = "" if sheet_id is None else " AND sheet_id = ?"
        return self.db.query(
            f"SELECT * FROM expense_sync WHERE done_at IS NULL{where} ORDER BY id",
            () if sheet_id is None else (sheet_id,),
        )

    async def drain(self) -> int:
        """The job: each sheet with changes due goes through the trust tiers. Returns how
        many sheets were written."""
        now = clock.now()
        due: dict[int, list[dict[str, Any]]] = {}
        for row in self.waiting():
            if datetime.fromisoformat(row["wanted_at"]) <= now:
                due.setdefault(row["sheet_id"], []).append(row)
        written = 0
        for sheet_id, rows in due.items():
            sheet = self.expenses.sheet(sheet_id)
            link = self.link_of(sheet.book_id)
            if link is None:  # forgotten meanwhile: nothing to write to
                self._done([r["id"] for r in rows])
                continue
            member = self.store.get_member(link["member_id"])
            if self.services.autonomy.is_automatic(CATEGORY, member) or self._approved_today(
                member, sheet
            ):
                if await self._write_now(sheet, member):
                    written += 1
                continue
            if self._open_action(member, sheet) or self._declined_today(member, sheet):
                continue
            changes = len({r["entry_id"] for r in rows if r["entry_id"]})
            what = f"{changes} change{'s' if changes != 1 else ''}" if changes else "its layout"
            await self.services.autonomy.stage(
                CATEGORY,
                member,
                f"Update {sheet.title} in Google Sheets ({what})",
                {"sheet": sheet.id, "day": self._today(member)},
                EXECUTOR,
            )
        return written

    def _actions(
        self, member: Member, sheet: Sheet, statuses: tuple[str, ...], day: str | None = None
    ) -> list[dict[str, Any]]:
        """This sheet's sync actions of theirs in these states (on `day`, if given)."""
        marks = ", ".join("?" for _ in statuses)
        on = "" if day is None else " AND json_extract(payload, '$.day') = ?"
        return self.db.query(
            "SELECT * FROM pending_actions WHERE category = ? AND member_id = ? "
            f"AND executor = ? AND status IN ({marks}) "
            f"AND json_extract(payload, '$.sheet') = ?{on}",
            (CATEGORY, member.id, EXECUTOR, *statuses, sheet.id, *(() if day is None else (day,))),
        )

    def _approved_today(self, member: Member, sheet: Sheet) -> bool:
        """At Tier 1, a yes covers that sheet for the rest of the day."""
        return bool(self._actions(member, sheet, ("done",), self._today(member)))

    def _declined_today(self, member: Member, sheet: Sheet) -> bool:
        return bool(self._actions(member, sheet, ("declined", "expired"), self._today(member)))

    def _open_action(self, member: Member, sheet: Sheet) -> bool:
        return bool(self._actions(member, sheet, ("pending", "snoozed", "executing", "failed")))

    def _today(self, member: Member) -> str:
        family = self.store.get_family()
        return (
            clock.now()
            .astimezone(ZoneInfo(family.timezone if family else "UTC"))
            .date()
            .isoformat()
        )

    async def sync_action(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        """The executor for an approved sheet: write what's waiting (and, the rest of that
        day, what comes after, without asking again)."""
        sheet = self.expenses.sheet(int(payload["sheet"]))
        await self._write_now(sheet, ctx.member, raise_errors=True)
        return f"{sheet.title} is up to date in Google Sheets."

    async def _write_now(self, sheet: Sheet, member: Member, *, raise_errors: bool = False) -> bool:
        rows = self.waiting(sheet.id)
        try:
            await self.write_sheet(sheet, entries={r["entry_id"] for r in rows if r["entry_id"]})
        except SheetsNotFound:
            await self._gone(sheet)
            self._done([r["id"] for r in rows])
            return False
        except SheetsError as exc:
            self._failed(rows, exc)
            await self._maybe_tell(sheet, rows, exc)
            if raise_errors:
                raise
            return False
        self._done([r["id"] for r in rows])
        self.db.execute(
            "UPDATE expense_book_links SET failing_told_at = NULL WHERE book_id = ?",
            (sheet.book_id,),
        )
        return True

    def _done(self, ids: list[int]) -> None:
        now = to_utc_iso(clock.now())
        self.db.executemany(
            "UPDATE expense_sync SET done_at = ? WHERE id = ?", [(now, i) for i in ids]
        )

    def _failed(self, rows: list[dict[str, Any]], exc: SheetsError) -> None:
        for row in rows:
            attempts = row["attempts"] + 1
            wait = BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
            if isinstance(exc, SheetsRateLimited) and exc.retry_after:
                wait = max(wait, timedelta(seconds=exc.retry_after))
            self.db.execute(
                "UPDATE expense_sync SET attempts = ?, wanted_at = ? WHERE id = ?",
                (attempts, to_utc_iso(clock.now() + wait), row["id"]),
            )
        log.info("Expense sync waits after %s", type(exc).__name__)

    async def _maybe_tell(self, sheet: Sheet, rows: list[dict[str, Any]], exc: SheetsError) -> None:
        oldest = min(datetime.fromisoformat(r["created_at"]) for r in rows)
        link = self.db.one("SELECT * FROM expense_book_links WHERE book_id = ?", (sheet.book_id,))
        if link is None or clock.now() - oldest < TELL_AFTER or link["failing_told_at"]:
            return
        self.db.execute(
            "UPDATE expense_book_links SET failing_told_at = ? WHERE book_id = ?",
            (to_utc_iso(clock.now()), sheet.book_id),
        )
        book = self.expenses.book(sheet.book_id)
        await self.outbox.send(
            self.store.get_member(link["member_id"]),
            FAILING_TEXT.format(book=book.title, why=_why(exc)),
            priority=Priority.NORMAL,
            kind=KIND,
        )

    async def _gone(self, sheet: Sheet) -> None:
        """Deleted in Google: the book forgets it, and says so once."""
        book = self.expenses.book(sheet.book_id)
        link = self.db.one("SELECT * FROM expense_book_links WHERE book_id = ?", (book.id,))
        self.expenses.set_spreadsheet(book.id, None)
        self.db.execute("DELETE FROM expense_book_links WHERE book_id = ?", (book.id,))
        if link is not None:
            await self.outbox.send(
                self.store.get_member(link["member_id"]),
                GONE_TEXT.format(book=book.title),
                priority=Priority.NORMAL,
                kind=KIND,
            )

    # ----- writing -----------------------------------------------------------------------

    async def write_sheet(
        self, sheet: Sheet, *, entries: set[int] | None = None, full: bool = False
    ) -> None:
        """Bring a sheet's tab in line: made (again) if it's missing, its name and place,
        the header, and the rows of `entries` (each written, or taken out when it's left the
        sheet), or every row when `full`."""
        book = self.expenses.book(sheet.book_id)
        link = self.db.one("SELECT * FROM expense_book_links WHERE book_id = ?", (book.id,))
        sid = book.google_spreadsheet_id
        assert link is not None and sid is not None
        client = self.client(link["account_id"])
        tabs = await client.tabs(sid)
        sheet = self.expenses.sheet(sheet.id)
        if sheet.archived_at is not None:  # archived in Themi: its tab goes
            tab = next((t for t in tabs if t.id == sheet.google_tab_id), None)
            if tab is not None and len(tabs) > 1:
                await client.batch(sid, [delete_sheet(tab.id)])
            self.expenses.set_tab_id(sheet.id, None)
            return
        tab = await self._tab(client, sid, sheet, tabs)
        if tab.id not in {t.id for t in tabs}:
            full = True  # a new tab (or one deleted in Google): everything goes on it
        fields = self.expenses.fields(sheet.id)
        current = {e.id: e for e in self.expenses.entries([sheet.id])}
        wanted = set(current) if full else (entries or set())
        rows = {
            str(i): row_cells(current[i], fields, self.sheets.link)
            for i in sorted(wanted)
            if i in current
        }
        gone = [str(i) for i in sorted(wanted) if i not in current]
        await client.upsert(sid, tab, header(fields), rows, remove=gone)

    async def _tab(self, client: SheetsClient, sid: str, sheet: Sheet, tabs: list[Tab]) -> Tab:
        """The sheet's tab, named and placed as in Themi: made if it isn't there."""
        position = [s.id for s in self.expenses.sheets(sheet.book_id)].index(sheet.id)
        found = next((t for t in tabs if t.id == sheet.google_tab_id), None)
        if found is None:
            title = _free_title(sheet.title, [t.title for t in tabs])
            tab_id = await client.add_tab(sid, title, min(position, len(tabs)))
            self.expenses.set_tab_id(sheet.id, tab_id)
            return Tab(tab_id, title, position)
        if found.title != sheet.title or found.index != position:
            title = sheet.title if found.title == sheet.title else _free_title(
                sheet.title, [t.title for t in tabs if t.id != found.id]
            )  # fmt: skip
            await client.batch(sid, [update_sheet(found.id, title=title, index=position)])
            return Tab(found.id, title, position)
        return found


def _why(exc: SheetsError) -> str:
    """Why Google Sheets didn't take the changes, in plain words."""
    if isinstance(exc, SheetsRateLimited):
        return "it asked Themi to slow down"
    if isinstance(exc, SheetsAuthError):
        return "Google refused Themi's access; linking the account again on My accounts fixes that"
    return "it didn't answer"


def _free_title(title: str, taken: list[str]) -> str:
    """A tab name Google will take (unique in its spreadsheet)."""
    if title not in taken:
        return title
    n = 2
    while f"{title} ({n})" in taken:
        n += 1
    return f"{title} ({n})"


def _sync(ctx: ToolContext) -> ExpenseSync:
    sync = ctx.services.maybe(keys.expense_sync)
    if sync is None:
        raise ToolFailed("Google Sheets isn't set up for expense sheets.")
    return sync


@tool(
    "put_in_google_sheets",
    "Copy one of their expense spreadsheets to Google Sheets, kept up to date ('put the "
    "kitchen project in Google Sheets'). book: its name. Themi asks which Google account, "
    "with a button each.",
    {"book": {"type": "string"}},
)
async def put_in_google_sheets(ctx: ToolContext, args: dict[str, Any]) -> str:
    sync = _sync(ctx)
    name = str(args.get("book") or "").strip()
    book = sync.expenses.book_by_title(ctx.member, name)
    if book is None:
        names = ", ".join(b.title for b in sync.expenses.books(ctx.member)) or "none yet"
        raise ToolFailed(f"There's no spreadsheet called {name}. Theirs: {names}. Ask them.")
    if book.google_spreadsheet_id:
        return f"{book.title} is in Google Sheets already: {sheet_link(book.google_spreadsheet_id)}"
    done = await sync.offer(ctx.member, book)
    ctx.cards.append(f"google sheets for book {book.id}: {done}")
    return "Asked them which Google account, with a button each."


class ExpenseSyncModule(Module):
    """EX4a, EX4b: expense sheets kept in step in Google Sheets."""

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
    tool_groups = (home_groups.SPENDING,)
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
        ctx.executor(CREATE_EXECUTOR, sync.create)
        ctx.executor(EXECUTOR, sync.sync_action)
        ctx.periodic("expense_sync.drain", SYNC_EVERY, sync.drain)
