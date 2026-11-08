"""The Safeway cart (35c): Themi's side of the Safeway helper, the Chrome extension in
`extension/safeway` that fills the cart in the family's own signed-in browser.

- Pairing: anyone can connect a helper on the website. Its token is shown once and kept
  hashed, and it can only claim and answer cart jobs and read and set remembered products.
- "Fill the Safeway cart" is a `safeway_cart` proposal (Tier 1, capped: always a yes). The
  yes queues a job with the grocery list's items, plus the things to buy that usually come
  from Safeway (L2b, named apart on the same card); a helper claims it once and posts what it
  added. The message names the family's items ("oat milk was out of stock"), never
  Safeway's product names, which only the website shows (escaped). Nothing the helper sends
  reaches the model.
- No helper, or a job nobody claims within 2 hours (or answers within 30 minutes of claiming
  it), sends the list once with a Safeway search link per item instead, and the job expires.
- Remembered products (`safeway_products`) are shared, so both browsers pick the same eggs.
  A Safeway receipt teaches an item's search words; the website can change or forget them.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

from themi import clock
from themi.accounts import Member
from themi.autonomy import ExecutionContext
from themi.channels.outbox import Priority
from themi.core import keys
from themi.core.tools import Proposal, ToolContext, ToolDeclined, ToolFailed, staged_tool
from themi.localtime import to_utc_iso
from themi.modules import Module, ModuleContext
from themi.standard.lists import name_key
from themi_home import home_groups
from themi_home.groceries import and_list

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi_home.groceries import GroceryList

CATEGORY = "safeway_cart"
EXECUTOR = "safeway.fill"
UNCLAIMED_FOR = timedelta(hours=2)
UNANSWERED_FOR = timedelta(minutes=30)
SEARCH_URL = "https://www.safeway.com/shop/search-results.html?q="
MAX_QTY = 20
MAX_ITEMS = 60
MAX_NAME = 80
MAX_PRODUCT_NAME = 200
MAX_SIZE = 40
MAX_SEARCH = 80
ResultStatus = Literal["added", "out_of_stock", "not_found", "failed"]
RESULT_STATUSES = ("added", "out_of_stock", "not_found", "failed")


class InvalidResults(ValueError):
    """What a helper sent isn't a valid answer; nothing was recorded."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _clean(raw: Any, limit: int) -> str:
    return " ".join(str(raw).split())[:limit]


def list_entry(raw: str) -> tuple[str, int]:
    """A grocery list name and its quantity, where the list has one: "2 oat milk",
    "oat milk x2" or "oat milk (2)". "7up" and "1% milk" are names."""
    text = _clean(raw, MAX_NAME)
    for pattern in (
        r"^(\d{1,2})\s*x?\s+(.+)$",
        r"^(.+?)\s+x\s*(\d{1,2})$",
        r"^(.+?)\s*\((\d{1,2})\)$",
    ):
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            qty, name = (match[1], match[2]) if match[1].isdigit() else (match[2], match[1])
            return name.strip(), max(1, min(int(qty), MAX_QTY))
    return text, 1


def search_link(name: str) -> str:
    return SEARCH_URL + quote(name)


@dataclass(frozen=True)
class Helper:
    id: int
    member_id: int
    created_at: datetime
    last_seen_at: datetime | None


@dataclass(frozen=True)
class Product:
    name: str
    product_id: str | None
    product_name: str | None
    size: str | None
    search_words: str | None


@dataclass(frozen=True)
class Job:
    id: int
    member_id: int
    action_id: int | None
    items: list[dict[str, Any]]
    status: str
    created_at: datetime


def _job(row: dict[str, Any]) -> Job:
    return Job(
        row["id"],
        row["member_id"],
        row["action_id"],
        json.loads(row["items"]),
        row["status"],
        datetime.fromisoformat(row["created_at"]),
    )


def _product(row: dict[str, Any]) -> Product:
    return Product(
        row["name"], row["product_id"], row["product_name"], row["size"], row["search_words"]
    )


def _things(n: int) -> str:
    return "1 thing" if n == 1 else f"{n} things"


def _was(names: list[str]) -> str:
    return f"{and_list(names)} {'was' if len(names) == 1 else 'were'}"


class SafewayCart:
    def __init__(self, services: Services, groceries: GroceryList) -> None:
        self.services = services
        self.groceries = groceries
        self.db = services.store.db

    def install(self) -> None:
        s = self.services
        s.provide(keys.safeway, self)
        s.autonomy.executors.register(EXECUTOR)(self._execute)
        s.tools.register(fill_safeway_cart)

    # ----- pairing ----------------------------------------------------------------------

    def connect(self, member: Member) -> str:
        """A new helper token, returned once; only its hash is kept."""
        token = "swh_" + secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO safeway_helpers (member_id, token_hash, created_at) VALUES (?, ?, ?)",
            (member.id, _hash(token), to_utc_iso(clock.now())),
        )
        return token

    def helpers(self) -> list[Helper]:
        rows = self.db.query("SELECT * FROM safeway_helpers WHERE revoked_at IS NULL ORDER BY id")
        return [
            Helper(
                r["id"],
                r["member_id"],
                datetime.fromisoformat(r["created_at"]),
                datetime.fromisoformat(r["last_seen_at"]) if r["last_seen_at"] else None,
            )
            for r in rows
        ]

    def revoke(self, helper_id: int) -> bool:
        return bool(
            self.db.update(
                "UPDATE safeway_helpers SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (to_utc_iso(clock.now()), helper_id),
            )
        )

    def helper_for(self, token: str | None) -> Helper | None:
        """The helper a bearer token belongs to, unless it's been revoked."""
        if not token:
            return None
        row = self.db.one(
            "SELECT * FROM safeway_helpers WHERE token_hash = ? AND revoked_at IS NULL",
            (_hash(token),),
        )
        if row is None:
            return None
        now = clock.now()
        self.db.execute(
            "UPDATE safeway_helpers SET last_seen_at = ? WHERE id = ?", (to_utc_iso(now), row["id"])
        )
        return Helper(row["id"], row["member_id"], datetime.fromisoformat(row["created_at"]), now)

    # ----- remembered products ----------------------------------------------------------

    def products(self) -> list[Product]:
        return [_product(r) for r in self.db.query("SELECT * FROM safeway_products ORDER BY name")]

    def product(self, name: str) -> Product | None:
        row = self.db.one("SELECT * FROM safeway_products WHERE name_key = ?", (name_key(name),))
        return _product(row) if row else None

    def _upsert(self, name: str, **columns: Any) -> None:
        name = _clean(name, MAX_NAME)
        if not name_key(name):
            raise InvalidResults("an item needs a name")
        sets = ", ".join(f"{c} = excluded.{c}" for c in columns)
        self.db.execute(
            f"INSERT INTO safeway_products (name_key, name, {', '.join(columns)}, updated_at) "
            f"VALUES (?, ?, {', '.join('?' for _ in columns)}, ?) "
            f"ON CONFLICT(name_key) DO UPDATE SET {sets}, updated_at = excluded.updated_at",
            (name_key(name), name, *columns.values(), to_utc_iso(clock.now())),
        )

    def remember(self, name: str, product: dict[str, Any]) -> None:
        """A helper's choice: `product` as validated by `check_product`."""
        self._upsert(
            name, product_id=product["id"], product_name=product["name"], size=product["size"]
        )

    def set_search_words(self, name: str, words: str) -> None:
        """Search for these words next time, and pick the product again."""
        self._upsert(
            name,
            search_words=_clean(words, MAX_SEARCH) or None,
            product_id=None,
            product_name=None,
            size=None,
        )

    def forget(self, name: str) -> bool:
        return bool(
            self.db.update("DELETE FROM safeway_products WHERE name_key = ?", (name_key(name),))
        )

    def learn_from_receipt(self, name: str, as_written: str, vendor: str) -> bool:
        """A Safeway receipt line for a grocery item: its words become what to search for.
        A product already picked stays; other stores teach nothing."""
        words = _clean(as_written, MAX_SEARCH)
        if "safeway" not in vendor.lower() or not words or name_key(words) == name_key(name):
            return False
        self._upsert(name, search_words=words)
        return True

    # ----- jobs ---------------------------------------------------------------------------

    def open_job(self) -> Job | None:
        row = self.db.one(
            "SELECT * FROM safeway_jobs WHERE status IN ('queued', 'claimed') ORDER BY id LIMIT 1"
        )
        return _job(row) if row else None

    def job(self, job_id: int) -> Job | None:
        row = self.db.one("SELECT * FROM safeway_jobs WHERE id = ?", (job_id,))
        return _job(row) if row else None

    def list_items(self) -> list[dict[str, Any]]:
        """The grocery list as cart items: a name and a quantity, merged by name."""
        items: dict[str, dict[str, Any]] = {}
        for grocery in self.groceries.needed():
            name, qty = list_entry(grocery.name)
            key = name_key(name)
            if not key:
                continue
            if key in items:
                items[key]["qty"] = min(items[key]["qty"] + qty, MAX_QTY)
            elif len(items) < MAX_ITEMS:
                items[key] = {"name": name, "qty": qty}
        return list(items.values())

    def things_to_buy(
        self, member: Member, taken: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """L2b: the open things to buy that usually come from Safeway, as cart items, and the
        list's name. Ones already among `taken` (the grocery items) aren't offered twice."""
        buying = self.services.maybe(keys.buying)
        found = buying.from_store(member, "Safeway") if buying is not None else None
        if found is None:
            return "", []
        nl, names = found
        taken_keys = {name_key(i["name"]) for i in taken}
        items = []
        for raw in names:
            name, qty = list_entry(raw)
            key = name_key(name)
            if key and key not in taken_keys and len(taken) + len(items) < MAX_ITEMS:
                taken_keys.add(key)
                items.append({"name": name, "qty": qty})
        return nl.name, items

    def queue(self, member: Member, items: list[dict[str, Any]], action_id: int | None) -> Job:
        job_id = self.db.execute(
            "INSERT INTO safeway_jobs (member_id, action_id, items, status, created_at) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (member.id, action_id, json.dumps(items), to_utc_iso(clock.now())),
        )
        job = self.job(job_id)
        assert job is not None
        return job

    def claim(self, helper: Helper) -> dict[str, Any] | None:
        """The oldest queued job for this helper, claimed once; None when there's none."""
        while (job := self._next_queued()) is not None:
            claimed = self.db.update(
                "UPDATE safeway_jobs SET status = 'claimed', helper_id = ?, claimed_at = ? "
                "WHERE id = ? AND status = 'queued'",
                (helper.id, to_utc_iso(clock.now()), job.id),
            )
            if claimed:
                return self.for_helper(job)
        return None

    def _next_queued(self) -> Job | None:
        row = self.db.one("SELECT * FROM safeway_jobs WHERE status = 'queued' ORDER BY id LIMIT 1")
        return _job(row) if row else None

    def for_helper(self, job: Job) -> dict[str, Any]:
        """What the helper gets: each item with what to search for, and the remembered product."""
        items = []
        for item in job.items:
            known = self.product(item["name"])
            product = None
            if known and known.product_id:
                product = {"id": known.product_id, "name": known.product_name, "size": known.size}
            search = known.search_words if known and known.search_words else item["name"]
            items.append(
                {"name": item["name"], "qty": item["qty"], "search": search, "product": product}
            )
        return {"id": job.id, "items": items}

    async def finish(self, job_id: int, helper: Helper, raw: Any) -> str:
        """A helper's answer: validated, recorded, remembered, and told to the person.
        Returns the message sent."""
        row = self.db.one(
            "SELECT * FROM safeway_jobs WHERE id = ? AND helper_id = ? AND status = 'claimed'",
            (job_id, helper.id),
        )
        if row is None:
            raise InvalidResults("no such job waiting on this helper")
        job = _job(row)
        results = check_results(raw, job)
        done = self.db.update(
            "UPDATE safeway_jobs SET status = 'done', results = ?, finished_at = ? "
            "WHERE id = ? AND status = 'claimed'",
            (json.dumps(results), to_utc_iso(clock.now()), job.id),
        )
        if not done:
            raise InvalidResults("the job was answered already")
        for line in results["items"]:
            if line["status"] == "added" and line["product"] is not None:
                self.remember(line["name"], line["product"])
        text = result_text(results)
        member = self.services.store.get_member(job.member_id)
        if member is not None:
            await self.services.outbox.send(
                member,
                text,
                priority=Priority.NORMAL,
                kind="safeway",
                dedupe_key=f"safeway-job-{job.id}",
                link_preview=False,
            )
        return text

    async def expire_stale(self) -> int:
        """Scheduler job: a job nobody claimed in 2 hours, or claimed and never answered in
        30 minutes, expires and sends the list with search links instead."""
        now = clock.now()
        rows = self.db.query(
            "SELECT * FROM safeway_jobs WHERE (status = 'queued' AND created_at <= ?) "
            "OR (status = 'claimed' AND claimed_at <= ?)",
            (to_utc_iso(now - UNCLAIMED_FOR), to_utc_iso(now - UNANSWERED_FOR)),
        )
        expired = 0
        for row in rows:
            if not self.db.update(
                "UPDATE safeway_jobs SET status = 'expired', finished_at = ? "
                "WHERE id = ? AND status = ?",
                (to_utc_iso(now), row["id"], row["status"]),
            ):
                continue
            expired += 1
            job = _job(row)
            member = self.services.store.get_member(job.member_id)
            if member is None:
                continue
            why = (
                "The Safeway helper didn't pick up the cart"
                if row["status"] == "queued"
                else "The Safeway helper didn't finish the cart"
            )
            await self.services.outbox.send(
                member,
                f"{why}, so here's the list with Safeway links instead.\n" + links_text(job.items),
                priority=Priority.NORMAL,
                kind="safeway",
                dedupe_key=f"safeway-job-{job.id}",
                link_preview=False,
            )
        return expired

    async def _execute(self, payload: dict[str, Any], ctx: ExecutionContext) -> str:
        items = [
            {"name": _clean(i["name"], MAX_NAME), "qty": int(i["qty"])} for i in payload["items"]
        ]
        existing = self.db.one(
            "SELECT * FROM safeway_jobs WHERE action_id = ?", (ctx.action_id,)
        )  # a retry: the job is there already
        if existing is None and not self.helpers():
            return "The Safeway helper isn't connected, so here's the list with links.\n" + (
                links_text(items)
            )
        if existing is None:
            self.queue(ctx.member, items, ctx.action_id)
        return (
            f"I'll have the Safeway helper fill the cart with {_things(len(items))} next time "
            "Safeway is open in Chrome. If it hasn't in 2 hours, I'll send the list instead."
        )


# ----- what the helper sends -------------------------------------------------------------


def check_product(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InvalidResults("a product must be an object")
    pid = raw.get("id")
    if not isinstance(pid, str) or not re.fullmatch(r"\d{1,20}", pid):
        raise InvalidResults("a product id is Safeway's digits")
    name, size = raw.get("name"), raw.get("size", "")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_PRODUCT_NAME:
        raise InvalidResults("a product needs a name of at most 200 characters")
    if not isinstance(size, str) or len(size) > MAX_SIZE:
        raise InvalidResults("a product's size is at most 40 characters")
    price = raw.get("price")
    if price is not None and (
        isinstance(price, bool) or not isinstance(price, int | float) or not 0 <= price < 10000
    ):
        raise InvalidResults("a price is a number")
    return {"id": pid, "name": _clean(name, MAX_PRODUCT_NAME), "size": _clean(size, MAX_SIZE)}


def check_results(raw: Any, job: Job) -> dict[str, Any]:
    """The helper's answer for `job`, checked: only the job's items, each once, with a
    known status, a sane quantity and a well-formed product."""
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise InvalidResults("results need a list of items")
    if len(raw["items"]) > len(job.items):
        raise InvalidResults("more results than items")
    wanted = {name_key(i["name"]): i["name"] for i in job.items}
    seen: set[str] = set()
    lines = []
    for line in raw["items"]:
        if not isinstance(line, dict):
            raise InvalidResults("each result must be an object")
        name = line.get("name")
        key = name_key(name) if isinstance(name, str) and len(name) <= MAX_NAME else ""
        if key not in wanted:
            raise InvalidResults("a result for an item that isn't in the job")
        if key in seen:
            raise InvalidResults("an item answered twice")
        seen.add(key)
        status = line.get("status")
        if status not in RESULT_STATUSES:
            raise InvalidResults("unknown status")
        qty = line.get("qty", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
            raise InvalidResults("a quantity is 1 to 20")
        product = line.get("product")
        lines.append(
            {
                "name": wanted[key],
                "status": status,
                "qty": qty,
                "product": None if product is None else check_product(product),
            }
        )
    stopped = raw.get("stopped")
    if stopped is not None and not isinstance(stopped, bool):
        raise InvalidResults("stopped is true or false")
    return {"items": lines, "stopped": bool(stopped)}


# ----- messages ---------------------------------------------------------------------------


def links_text(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        qty = f" ({item['qty']})" if item["qty"] > 1 else ""
        lines.append(f"- {item['name']}{qty}: {search_link(item['name'])}")
    return "\n".join(lines)


def result_text(results: dict[str, Any]) -> str:
    """ "9 things in the Safeway cart; oat milk was out of stock. Ready when you are." The
    family's own item names only."""
    by: dict[str, list[str]] = {s: [] for s in RESULT_STATUSES}
    for line in results["items"]:
        by[line["status"]].append(line["name"])
    parts = []
    if by["out_of_stock"]:
        parts.append(f"{_was(by['out_of_stock'])} out of stock")
    if by["not_found"]:
        parts.append(f"I couldn't find {and_list(by['not_found'])}")
    if by["failed"]:
        parts.append(f"{_was(by['failed'])} not added")
    added = len(by["added"])
    head = f"{_things(added)} in the Safeway cart" if added else "Nothing went in the Safeway cart"
    text = head + ("; " + "; ".join(parts) if parts else "") + "."
    if results["stopped"]:
        return text + " The helper stopped partway: Safeway wants a sign-in in Chrome first."
    return text + (" Ready when you are." if added else "")


# ----- the tool ---------------------------------------------------------------------------


@staged_tool(
    "fill_safeway_cart",
    "Fill the family's Safeway cart from the grocery list ('fill the Safeway cart', 'do the "
    "weekly shop on Safeway'). The Safeway helper in their Chrome adds the items; a person "
    "always checks out. Takes the whole grocery list, plus the things to buy that usually "
    "come from Safeway; waits for their yes.",
    {},
)
async def fill_safeway_cart(ctx: ToolContext, args: dict[str, Any]) -> Proposal:
    safeway = ctx.services.maybe(keys.safeway)
    if safeway is None:
        raise ToolFailed("The Safeway cart isn't set up.")
    if safeway.open_job() is not None:
        raise ToolDeclined("A Safeway cart is already waiting for the helper. Nothing was staged.")
    groceries = safeway.list_items()
    list_name, extras = safeway.things_to_buy(ctx.member, groceries)
    if not groceries and not extras:
        raise ToolDeclined(
            "The grocery list is empty and nothing to buy usually comes from Safeway, so "
            "there's nothing for the cart."
        )
    summary = f"{_named(groceries)} for the Safeway cart" if groceries else ""
    if extras:
        summary += (
            f", plus {_named(extras)} from {list_name}"
            if groceries
            else f"{_named(extras)} from {list_name} for the Safeway cart"
        )
    return Proposal(
        CATEGORY, summary[:1].upper() + summary[1:], EXECUTOR, {"items": groceries + extras}
    )


def _named(items: list[dict[str, Any]]) -> str:
    return and_list([f"{i['qty']} {i['name']}" if i["qty"] > 1 else i["name"] for i in items])


class SafewayModule(Module):
    """35c: the Safeway cart, filled by the helper extension."""

    name = "safeway"
    tool_groups = (home_groups.PANTRY,)
    requires = ("groceries",)

    def install(self, ctx: ModuleContext) -> None:
        from themi.modules.web import MenuEntry
        from themi.web import icons
        from themi_home.groceries import (
            GroceryList,  # at install: at the top it would be an import cycle
        )
        from themi_home.web import safeway_pages

        ctx.web(
            safeway_pages.routes,
            MenuEntry(
                "/safeway",
                "Safeway",
                "The cart helper and remembered products",
                "Household",
                70,
                icon=icons.SAFEWAY,
            ),
        )

        cart = ctx.provide(SafewayCart(ctx.services, ctx.get(GroceryList)))
        cart.install()
        ctx.periodic("safeway.expire", timedelta(minutes=5), cart.expire_stale)
