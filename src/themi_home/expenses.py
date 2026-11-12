"""Expense sheets (EX1a, from the spec "Themi Intelligent Expense Tracking Engine").

The family makes sheets when they want them (dining out, business travel, a project's
budget), each with its own fields. A *book* is one spreadsheet, with a title and an owner
(a person, or the household); each *sheet* belongs to one book and is one tab of it (idea
#167: the business spreadsheet has tabs for expenses, income and mileage).

An *entry* on a sheet holds one `Value` per field. A value keeps:
- its status: `verified` (the person said it, or checked it), `unverified` (Themi filled it
  in) or `user_estimate` (they guessed: "about $40, pretty sure");
- how sure it is (0 to 1), set by code, never by a model;
- its lineage: the source type (`direct_user_input`, `email_receipt`, `calendar_event`,
  `chat_context`, `user_estimate`), a reference (a Gmail message, a calendar event), the
  evidence (the words quoted) and when it was recorded.
Unknown is None (stored as NULL), never made up. Money is integer cents; a date is
YYYY-MM-DD.

Themi's database is the truth: Google Sheets and CSV are copies (EX3, EX4b). Two sheets are
built in: the household's "Takeout & eating out", and each person's "Business" (the first
tab of their "Business" book). X1's spending lives on them (`themi_home.spending`).

Who sees what: a household sheet is everyone's; a person's own sheet (their Business one,
or one they made for themselves) is theirs alone.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Literal

from themi import clock
from themi.accounts import InvalidValue, Member
from themi.localtime import to_utc_iso
from themi.storage.db import Database

log = logging.getLogger(__name__)

FieldType = Literal["money", "date", "text", "choice", "number"]
FIELD_TYPES: tuple[FieldType, ...] = ("money", "date", "text", "choice", "number")
Status = Literal["verified", "unverified", "user_estimate"]
STATUSES: tuple[Status, ...] = ("verified", "unverified", "user_estimate")
SourceType = Literal[
    "direct_user_input", "email_receipt", "calendar_event", "chat_context", "user_estimate"
]
SOURCE_TYPES: tuple[SourceType, ...] = (
    "direct_user_input",
    "email_receipt",
    "calendar_event",
    "chat_context",
    "user_estimate",
)
# How a status reads, on the website and in Google Sheets (EX1b, EX4b): words, never colour
# alone. A critical field with no value is "Missing".
STATUS_WORDS = {
    "verified": "Checked",
    "unverified": "Filled in by Themi",
    "user_estimate": "Your estimate",
    "missing": "Missing",
}
STATUS_MARKS = {"verified": "✓", "unverified": "◐", "user_estimate": "≈", "missing": "○"}
SOURCE_WORDS = {
    "direct_user_input": "said in chat",
    "email_receipt": "a receipt email",
    "calendar_event": "a calendar event",
    "chat_context": "the chat around it",
    "user_estimate": "their estimate",
}
Mode = Literal["personal", "business", "custom"]
MODES: tuple[Mode, ...] = ("personal", "business", "custom")
Origin = Literal["chat", "email", "website"]

TAKEOUT_TITLE = "Takeout & eating out"
BUSINESS_TITLE = "Business"
KIND_CHOICES = ("takeout", "eating_out", "other")
MAX_TITLE = 80
MAX_FIELDS = 15


@dataclass(frozen=True)
class FieldDef:
    """A field as proposed or declared, before it's on a sheet."""

    key: str
    label: str
    type: FieldType
    choices: tuple[str, ...] = ()
    critical: bool = False


BASE_FIELDS = (
    FieldDef("amount", "Amount", "money", critical=True),
    FieldDef("date", "Date", "date", critical=True),
    FieldDef("vendor", "Vendor", "text"),
    FieldDef("category", "Category", "text"),
    FieldDef("note", "Note", "text"),
)
TAKEOUT_FIELDS = (
    FieldDef("amount", "Amount", "money", critical=True),
    FieldDef("date", "Date", "date", critical=True),
    FieldDef("vendor", "Vendor", "text"),
    FieldDef("category", "Category", "choice", KIND_CHOICES),
    FieldDef("note", "Note", "text"),
)
BUSINESS_FIELDS = (
    FieldDef("amount", "Amount", "money", critical=True),
    FieldDef("date", "Date", "date", critical=True),
    FieldDef("vendor", "Vendor", "text", critical=True),
    FieldDef("category", "Category", "choice", KIND_CHOICES),
    FieldDef("purpose", "Business purpose", "text", critical=True),
    FieldDef("attendees", "Who was there", "text"),
    FieldDef("note", "Note", "text"),
)
BUSINESS_KEYWORDS = ("for work", "business", "client")


@dataclass(frozen=True)
class Field:
    id: int
    sheet_id: int
    key: str
    label: str
    type: FieldType
    choices: tuple[str, ...]
    critical: bool
    position: int


@dataclass(frozen=True)
class Book:
    id: int
    title: str
    member_id: int | None
    google_spreadsheet_id: str | None
    created_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class Sheet:
    id: int
    book_id: int
    title: str
    mode: Mode
    member_id: int | None
    prompt_on_missing_critical: bool
    csv_enabled: bool
    keywords: tuple[str, ...]
    google_tab_id: int | None
    position: int
    counts_as_spending: bool
    builtin: str | None
    created_at: datetime
    archived_at: datetime | None

    @property
    def household(self) -> bool:
        return self.member_id is None


@dataclass(frozen=True)
class Value:
    value: Any
    status: Status
    confidence: float | None
    source_type: SourceType
    source_ref: str = ""
    evidence: str = ""
    recorded_at: datetime | None = None

    @classmethod
    def said(cls, value: Any, evidence: str = "") -> Value:
        """What the person said themselves: theirs, so checked."""
        return cls(value, "verified", 1.0, "direct_user_input", "", evidence)

    @classmethod
    def estimate(cls, value: Any, confidence: float, evidence: str = "") -> Value:
        """Their own guess, as sure as they said ("pretty sure" is 0.8)."""
        return cls(value, "user_estimate", confidence, "user_estimate", "", evidence)

    @classmethod
    def filled(
        cls, value: Any, confidence: float, source_type: SourceType, ref: str, evidence: str
    ) -> Value:
        """Themi's reading of a receipt, an event or the chat: unverified until they check."""
        return cls(value, "unverified", confidence, source_type, ref, evidence)


@dataclass(frozen=True)
class Entry:
    id: int
    sheet_id: int
    member_id: int
    origin: Origin
    email_id: int | None
    created_at: datetime
    removed_at: datetime | None
    values: dict[str, Value] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        value = self.values.get(key)
        return None if value is None else value.value

    def missing(self, fields: Iterable[Field], *, critical_only: bool = True) -> list[Field]:
        return [f for f in fields if (f.critical or not critical_only) and self.get(f.key) is None]


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _book(row: dict[str, Any]) -> Book:
    return Book(
        row["id"], row["title"], row["member_id"], row["google_spreadsheet_id"],
        datetime.fromisoformat(row["created_at"]), _when(row["archived_at"]),
    )  # fmt: skip


def _sheet(row: dict[str, Any]) -> Sheet:
    return Sheet(
        row["id"], row["book_id"], row["title"], row["mode"], row["member_id"],
        bool(row["prompt_on_missing_critical"]), bool(row["csv_enabled"]),
        tuple(json.loads(row["keywords"] or "[]")), row["google_tab_id"], row["position"],
        bool(row["counts_as_spending"]), row["builtin"],
        datetime.fromisoformat(row["created_at"]), _when(row["archived_at"]),
    )  # fmt: skip


def _field(row: dict[str, Any]) -> Field:
    return Field(
        row["id"], row["sheet_id"], row["key"], row["label"], row["type"],
        tuple(json.loads(row["choices"] or "[]")), bool(row["critical"]), row["position"],
    )  # fmt: skip


def check_value(f: Field | FieldDef, value: Any) -> Any:
    """`value` as this field keeps it, or InvalidValue. None is always allowed (unknown)."""
    if value is None:
        return None
    if f.type == "money":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidValue(f"{f.label} is an amount in cents")
        return value
    if f.type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidValue(f"{f.label} is a number")
        return value
    if f.type == "date":
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise InvalidValue(f"{f.label} is a date like 2026-10-21") from exc
    text = " ".join(str(value).split())[:200]
    if f.type == "choice" and f.choices and text not in f.choices:
        raise InvalidValue(f"{f.label} is one of {', '.join(f.choices)}")
    return text


def field_key(label: str) -> str:
    """A field's key from its label: "Who was there" -> who_was_there."""
    words = "".join(c if c.isalnum() else " " for c in label.lower()).split()
    return "_".join(words)[:40] or "field"


class Expenses:
    def __init__(self, db: Database) -> None:
        self.db = db
        # EX4b: told (entry id, sheet id) whenever an entry's values change, or it leaves or
        # joins a sheet, so the copy in Google Sheets can follow.
        self.change_listeners: list[Callable[[int, int], None]] = []

    # ----- books -------------------------------------------------------------------------

    def book(self, book_id: int) -> Book:
        row = self.db.one("SELECT * FROM expense_books WHERE id = ?", (book_id,))
        if row is None:
            raise InvalidValue(f"there's no expense book {book_id}")
        return _book(row)

    def books(self, member: Member) -> list[Book]:
        """The books they can see: the household's and their own, oldest first."""
        rows = self.db.query(
            "SELECT * FROM expense_books WHERE archived_at IS NULL "
            "AND (member_id IS NULL OR member_id = ?) ORDER BY id",
            (member.id,),
        )
        return [_book(r) for r in rows]

    def make_book(self, title: str, owner: Member | None) -> Book:
        title = " ".join(title.split())[:MAX_TITLE]
        if not title:
            raise InvalidValue("a spreadsheet needs a title")
        book_id = self.db.execute(
            "INSERT INTO expense_books (title, member_id, created_at) VALUES (?, ?, ?)",
            (title, owner.id if owner else None, to_utc_iso(clock.now())),
        )
        return self.book(book_id)

    def rename_book(self, book_id: int, title: str) -> Book:
        title = " ".join(title.split())[:MAX_TITLE]
        if not title:
            raise InvalidValue("a spreadsheet needs a title")
        self.db.execute("UPDATE expense_books SET title = ? WHERE id = ?", (title, book_id))
        return self.book(book_id)

    def set_spreadsheet(self, book_id: int, spreadsheet_id: str | None) -> None:
        """EX4b: the Google spreadsheet that copies this book (None: forgotten)."""
        self.db.execute(
            "UPDATE expense_books SET google_spreadsheet_id = ? WHERE id = ?",
            (spreadsheet_id, book_id),
        )
        if spreadsheet_id is None:
            self.db.execute(
                "UPDATE expense_sheets SET google_tab_id = NULL WHERE book_id = ?", (book_id,)
            )

    def book_by_title(self, member: Member, title: str) -> Book | None:
        """A book of theirs by its title, loosely ("the business spreadsheet")."""
        wanted = _words(title) - {"the", "spreadsheet", "sheet", "book", "my", "our"}
        best: Book | None = None
        for book in self.books(member):
            have = _words(book.title)
            if (wanted and wanted <= have) and (
                best is None or (book.member_id is not None and best.member_id is None)
            ):
                best = book
        return best

    # ----- sheets ------------------------------------------------------------------------

    def sheet(self, sheet_id: int) -> Sheet:
        row = self.db.one("SELECT * FROM expense_sheets WHERE id = ?", (sheet_id,))
        if row is None:
            raise InvalidValue(f"there's no expense sheet {sheet_id}")
        return _sheet(row)

    def sheets(self, book_id: int) -> list[Sheet]:
        """A book's tabs, in order."""
        rows = self.db.query(
            "SELECT * FROM expense_sheets WHERE book_id = ? AND archived_at IS NULL "
            "ORDER BY position, id",
            (book_id,),
        )
        return [_sheet(r) for r in rows]

    def visible_sheets(self, member: Member) -> list[Sheet]:
        """Every sheet they can see, book by book."""
        return [s for b in self.books(member) for s in self.sheets(b.id)]

    def all_sheets(self) -> list[Sheet]:
        rows = self.db.query(
            "SELECT * FROM expense_sheets WHERE archived_at IS NULL ORDER BY book_id, position"
        )
        return [_sheet(r) for r in rows]

    def can_see(self, member: Member, sheet: Sheet) -> bool:
        return sheet.member_id is None or sheet.member_id == member.id

    def can_change(self, member: Member, sheet: Sheet) -> bool:
        """Its fields and its settings: the owner's, or for the household's, any admin's."""
        if sheet.member_id is not None:
            return sheet.member_id == member.id
        return member.is_admin

    def make_sheet(
        self,
        book: Book,
        title: str,
        mode: Mode,
        fields: Sequence[FieldDef],
        *,
        keywords: Sequence[str] = (),
        counts_as_spending: bool = True,
        prompt_on_missing_critical: bool = True,
        csv_enabled: bool = True,
        builtin: str | None = None,
    ) -> Sheet:
        """A new tab at the end of `book`, owned as the book is."""
        title = " ".join(title.split())[:MAX_TITLE]
        if not title:
            raise InvalidValue("a sheet needs a title")
        if mode not in MODES:
            raise InvalidValue(f"a sheet's mode is one of {', '.join(MODES)}")
        if not fields:
            raise InvalidValue("a sheet needs at least one field")
        if len(fields) > MAX_FIELDS:
            raise InvalidValue(f"a sheet has at most {MAX_FIELDS} fields")
        keys = [f.key for f in fields]
        if len(set(keys)) != len(keys):
            raise InvalidValue("two fields have the same name")
        for f in fields:
            if f.type not in FIELD_TYPES:
                raise InvalidValue(f"a field's type is one of {', '.join(FIELD_TYPES)}")
        position = self.db.scalar(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM expense_sheets WHERE book_id = ? "
            "AND archived_at IS NULL",
            (book.id,),
        )
        now = to_utc_iso(clock.now())
        with self.db.transaction():
            sheet_id = self.db.execute(
                "INSERT INTO expense_sheets (book_id, title, mode, member_id, "
                "prompt_on_missing_critical, csv_enabled, keywords, position, "
                "counts_as_spending, builtin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    book.id, title, mode, book.member_id, int(prompt_on_missing_critical),
                    int(csv_enabled), json.dumps([k.lower() for k in keywords]), position,
                    int(counts_as_spending), builtin, now,
                ),
            )  # fmt: skip
            self.db.executemany(
                "INSERT INTO expense_fields (sheet_id, key, label, type, choices, critical, "
                "position) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (sheet_id, f.key, f.label[:60], f.type, json.dumps(list(f.choices)),
                     int(f.critical), i)
                    for i, f in enumerate(fields)
                ],
            )  # fmt: skip
        return self.sheet(sheet_id)

    def rename_sheet(self, sheet_id: int, title: str) -> Sheet:
        title = " ".join(title.split())[:MAX_TITLE]
        if not title:
            raise InvalidValue("a sheet needs a title")
        self.db.execute("UPDATE expense_sheets SET title = ? WHERE id = ?", (title, sheet_id))
        self._sheet_changed(sheet_id)
        return self.sheet(sheet_id)

    def move_tab(self, sheet_id: int, position: int) -> list[Sheet]:
        """Put a tab at `position` (0 first) in its book; the others keep their order."""
        sheet = self.sheet(sheet_id)
        others = [s for s in self.sheets(sheet.book_id) if s.id != sheet_id]
        position = max(0, min(position, len(others)))
        ordered = [*others[:position], sheet, *others[position:]]
        self.db.executemany(
            "UPDATE expense_sheets SET position = ? WHERE id = ?",
            [(i, s.id) for i, s in enumerate(ordered)],
        )
        for s in ordered:
            self._sheet_changed(s.id)
        return self.sheets(sheet.book_id)

    def archive_sheet(self, sheet_id: int) -> Sheet:
        """Put a tab away; archiving a book's last tab puts the book away too."""
        sheet = self.sheet(sheet_id)
        if sheet.builtin is not None:
            raise InvalidValue("a built-in sheet stays")
        now = to_utc_iso(clock.now())
        self.db.execute("UPDATE expense_sheets SET archived_at = ? WHERE id = ?", (now, sheet_id))
        self._sheet_changed(sheet_id)  # EX4b: its tab in Google Sheets goes
        if not self.sheets(sheet.book_id):
            self.db.execute(
                "UPDATE expense_books SET archived_at = ? WHERE id = ?", (now, sheet.book_id)
            )
        return self.sheet(sheet_id)

    def set_sheet_options(
        self,
        sheet_id: int,
        *,
        prompt_on_missing_critical: bool | None = None,
        csv_enabled: bool | None = None,
        keywords: Sequence[str] | None = None,
    ) -> Sheet:
        sheet = self.sheet(sheet_id)
        self.db.execute(
            "UPDATE expense_sheets SET prompt_on_missing_critical = ?, csv_enabled = ?, "
            "keywords = ? WHERE id = ?",
            (
                int(sheet.prompt_on_missing_critical if prompt_on_missing_critical is None
                    else prompt_on_missing_critical),
                int(sheet.csv_enabled if csv_enabled is None else csv_enabled),
                json.dumps(list(sheet.keywords if keywords is None
                                else [k.lower() for k in keywords])),
                sheet_id,
            ),
        )  # fmt: skip
        return self.sheet(sheet_id)

    def set_tab_id(self, sheet_id: int, tab_id: int | None) -> None:
        self.db.execute(
            "UPDATE expense_sheets SET google_tab_id = ? WHERE id = ?", (tab_id, sheet_id)
        )

    # ----- the built-in sheets -----------------------------------------------------------

    def takeout_sheet(self) -> Sheet:
        row = self.db.one("SELECT * FROM expense_sheets WHERE builtin = 'takeout'")
        if row is not None:
            return _sheet(row)
        book = self.make_book(TAKEOUT_TITLE, None)
        return self.make_sheet(
            book, TAKEOUT_TITLE, "personal", TAKEOUT_FIELDS, builtin="takeout",
            keywords=("takeout", "doordash", "restaurant", "dinner out", "eating out"),
        )  # fmt: skip

    def business_sheet(self, member: Member) -> Sheet:
        """Their Business sheet, the first tab of their Business book (made when needed)."""
        row = self.db.one(
            "SELECT * FROM expense_sheets WHERE builtin = 'business' AND member_id = ?",
            (member.id,),
        )
        if row is not None:
            return _sheet(row)
        book = self.make_book(BUSINESS_TITLE, member)
        return self.make_sheet(
            book, BUSINESS_TITLE, "business", BUSINESS_FIELDS, builtin="business",
            keywords=BUSINESS_KEYWORDS,
        )  # fmt: skip

    def builtin_sheet_ids(self) -> list[int]:
        return [
            r["id"]
            for r in self.db.query("SELECT id FROM expense_sheets WHERE builtin IS NOT NULL")
        ]

    # ----- fields ------------------------------------------------------------------------

    def fields(self, sheet_id: int) -> list[Field]:
        rows = self.db.query(
            "SELECT * FROM expense_fields WHERE sheet_id = ? ORDER BY position, id", (sheet_id,)
        )
        return [_field(r) for r in rows]

    def field(self, sheet_id: int, key: str) -> Field | None:
        row = self.db.one(
            "SELECT * FROM expense_fields WHERE sheet_id = ? AND key = ?", (sheet_id, key)
        )
        return _field(row) if row else None

    def add_field(self, sheet_id: int, f: FieldDef) -> Field:
        if self.field(sheet_id, f.key) is not None:
            raise InvalidValue(f"the sheet has a {f.label} field already")
        if f.type not in FIELD_TYPES:
            raise InvalidValue(f"a field's type is one of {', '.join(FIELD_TYPES)}")
        if len(self.fields(sheet_id)) >= MAX_FIELDS:
            raise InvalidValue(f"a sheet has at most {MAX_FIELDS} fields")
        position = self.db.scalar(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM expense_fields WHERE sheet_id = ?",
            (sheet_id,),
        )
        self.db.execute(
            "INSERT INTO expense_fields (sheet_id, key, label, type, choices, critical, "
            "position) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sheet_id, f.key, f.label[:60], f.type, json.dumps(list(f.choices)),
             int(f.critical), position),
        )  # fmt: skip
        self._sheet_changed(sheet_id)
        found = self.field(sheet_id, f.key)
        assert found is not None
        return found

    def update_field(
        self, sheet_id: int, key: str, *, label: str | None = None, critical: bool | None = None
    ) -> Field:
        f = self.field(sheet_id, key)
        if f is None:
            raise InvalidValue(f"the sheet has no {key} field")
        self.db.execute(
            "UPDATE expense_fields SET label = ?, critical = ? WHERE id = ?",
            (
                (label or f.label)[:60],
                int(f.critical if critical is None else critical),
                f.id,
            ),
        )
        self._sheet_changed(sheet_id)
        found = self.field(sheet_id, key)
        assert found is not None
        return found

    def remove_field(self, sheet_id: int, key: str) -> None:
        f = self.field(sheet_id, key)
        if f is None:
            raise InvalidValue(f"the sheet has no {key} field")
        if f.key in ("amount", "date") and self.sheet(sheet_id).builtin is not None:
            raise InvalidValue("a built-in sheet keeps its amount and date")
        with self.db.transaction():
            self.db.execute("DELETE FROM expense_values WHERE field_id = ?", (f.id,))
            self.db.execute("DELETE FROM expense_fields WHERE id = ?", (f.id,))
        self._sheet_changed(sheet_id)

    # ----- entries -----------------------------------------------------------------------

    def add(
        self,
        sheet: Sheet,
        member: Member,
        values: dict[str, Value],
        *,
        origin: Origin = "chat",
        email_id: int | None = None,
    ) -> Entry:
        fields = {f.key: f for f in self.fields(sheet.id)}
        unknown = set(values) - set(fields)
        if unknown:
            raise InvalidValue(f"the sheet has no {', '.join(sorted(unknown))} field")
        now = to_utc_iso(clock.now())
        with self.db.transaction():
            entry_id = self.db.execute(
                "INSERT INTO expense_entries (sheet_id, member_id, origin, email_id, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (sheet.id, member.id, origin, email_id, now),
            )
            for key, value in values.items():
                self._write(entry_id, fields[key], value)
        self._changed(entry_id)
        return self.entry(entry_id)

    def set(self, entry_id: int, key: str, value: Value) -> Entry:
        """Replace one value (a fill, a correction, a check)."""
        entry = self.entry(entry_id)
        f = self.field(entry.sheet_id, key)
        if f is None:
            raise InvalidValue(f"the sheet has no {key} field")
        self._write(entry_id, f, value)
        self._changed(entry_id)
        return self.entry(entry_id)

    def _write(self, entry_id: int, f: Field, value: Value) -> None:
        if value.status not in STATUSES or value.source_type not in SOURCE_TYPES:
            raise InvalidValue("that value's status or source isn't one Themi knows")
        if value.confidence is not None and not 0 <= value.confidence <= 1:
            raise InvalidValue("confidence is between 0 and 1")
        kept = check_value(f, value.value)
        self.db.execute(
            "INSERT OR REPLACE INTO expense_values (entry_id, field_id, value, status, "
            "confidence, source_type, source_ref, evidence, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id, f.id, None if kept is None else json.dumps(kept), value.status,
                value.confidence, value.source_type, value.source_ref[:200],
                value.evidence[:500], to_utc_iso(value.recorded_at or clock.now()),
            ),
        )  # fmt: skip

    def verify(self, entry_id: int) -> Entry:
        """The person says the entry is right: every value it has is checked."""
        self.db.execute(
            "UPDATE expense_values SET status = 'verified' WHERE entry_id = ? "
            "AND value IS NOT NULL",
            (entry_id,),
        )
        self._changed(entry_id)
        return self.entry(entry_id)

    def entry(self, entry_id: int) -> Entry:
        row = self.db.one("SELECT * FROM expense_entries WHERE id = ?", (entry_id,))
        if row is None:
            raise InvalidValue(f"there's no expense {entry_id}")
        return self._entries([row])[0]

    def entries(
        self,
        sheet_ids: Sequence[int],
        start: date | None = None,
        end: date | None = None,
    ) -> list[Entry]:
        """The sheets' entries (not removed), by their date then id. `start` and `end` (end
        excluded) keep those dated in between; an entry with no date is kept only when
        neither is given."""
        if not sheet_ids:
            return []
        marks = ", ".join("?" for _ in sheet_ids)
        params: list[Any] = list(sheet_ids)
        where = ""
        if start is not None or end is not None:
            where = " AND d.day IS NOT NULL AND d.day >= ? AND d.day < ?"
            params += [
                (start or date.min).isoformat(),
                (end or date.max).isoformat(),
            ]
        rows = self.db.query(
            "SELECT en.*, d.day FROM expense_entries en LEFT JOIN ("
            "  SELECT v.entry_id, json_extract(v.value, '$') AS day FROM expense_values v"
            "  JOIN expense_fields f ON f.id = v.field_id WHERE f.key = 'date'"
            f") d ON d.entry_id = en.id WHERE en.sheet_id IN ({marks}) AND en.removed_at IS NULL"
            f"{where} ORDER BY COALESCE(d.day, ''), en.id",
            params,
        )
        return self._entries(rows)

    def _entries(self, rows: list[dict[str, Any]]) -> list[Entry]:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        marks = ", ".join("?" for _ in ids)
        values: dict[int, dict[str, Value]] = {i: {} for i in ids}
        for v in self.db.query(
            "SELECT v.*, f.key FROM expense_values v JOIN expense_fields f ON f.id = v.field_id "
            f"WHERE v.entry_id IN ({marks})",
            ids,
        ):
            values[v["entry_id"]][v["key"]] = Value(
                None if v["value"] is None else json.loads(v["value"]),
                v["status"], v["confidence"], v["source_type"], v["source_ref"], v["evidence"],
                datetime.fromisoformat(v["recorded_at"]),
            )  # fmt: skip
        return [
            Entry(
                r["id"],
                r["sheet_id"],
                r["member_id"],
                r["origin"],
                r["email_id"],
                datetime.fromisoformat(r["created_at"]),
                _when(r["removed_at"]),
                values[r["id"]],
            )
            for r in rows
        ]

    def remove(self, entry_id: int) -> Entry:
        entry = self.entry(entry_id)
        self.db.execute(
            "UPDATE expense_entries SET removed_at = ?, email_id = NULL WHERE id = ?",
            (to_utc_iso(clock.now()), entry_id),
        )
        self._changed(entry_id)
        return entry

    def attach_email(self, entry_id: int, email_id: int) -> Entry:
        self.db.execute(
            "UPDATE expense_entries SET email_id = ? WHERE id = ?", (email_id, entry_id)
        )
        return self.entry(entry_id)

    def entry_for_email(self, email_id: int) -> Entry | None:
        row = self.db.one("SELECT * FROM expense_entries WHERE email_id = ?", (email_id,))
        return self._entries([row])[0] if row else None

    def move(self, entry_id: int, sheet: Sheet) -> Entry:
        """Put an entry on another sheet ("that's travel"): values whose field the new sheet
        has (by key) come along; the others are left behind."""
        entry = self.entry(entry_id)
        if entry.sheet_id == sheet.id:
            return entry
        target = {f.key: f for f in self.fields(sheet.id)}
        with self.db.transaction():
            self.db.execute("DELETE FROM expense_values WHERE entry_id = ?", (entry_id,))
            self.db.execute(
                "UPDATE expense_entries SET sheet_id = ? WHERE id = ?", (sheet.id, entry_id)
            )
            for key, value in entry.values.items():
                if key in target:
                    try:
                        self._write(entry_id, target[key], value)
                    except InvalidValue:  # a choice the new sheet doesn't have
                        continue
        self._changed(entry_id, entry.sheet_id)  # its row on the old tab goes
        self._changed(entry_id)
        return self.entry(entry_id)

    # ----- changes, for the sync queue (EX4b) --------------------------------------------

    def _changed(self, entry_id: int, sheet_id: int | None = None) -> None:
        on = sheet_id
        if on is None:
            on = int(
                self.db.scalar("SELECT sheet_id FROM expense_entries WHERE id = ?", (entry_id,))
            )
        for listener in self.change_listeners:
            try:
                listener(entry_id, on)
            except Exception:
                log.exception("An expense change listener failed for entry %s", entry_id)

    def _sheet_changed(self, sheet_id: int) -> None:
        """A sheet's header or place changed: it's synced again (through its first entry,
        or with no entry at all: entry id 0)."""
        first = self.db.scalar(
            "SELECT MIN(id) FROM expense_entries WHERE sheet_id = ? AND removed_at IS NULL",
            (sheet_id,),
        )
        for listener in self.change_listeners:
            try:
                listener(first or 0, sheet_id)
            except Exception:
                log.exception("An expense change listener failed for sheet %s", sheet_id)


def _words(text: str) -> set[str]:
    return set("".join(c if c.isalnum() else " " for c in text.lower()).split())


def with_value(entry: Entry, key: str, value: Value) -> Entry:
    """A copy of `entry` with one value changed (for showing a proposal)."""
    return replace(entry, values={**entry.values, key: value})
