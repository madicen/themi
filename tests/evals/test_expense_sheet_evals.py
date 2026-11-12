"""EX1b: expense sheets with a real model. Opt-in, like the other evals:

    make evals EVAL_ARGS='-k expense_sheet'

- `expense_sheet_fields`: ten sheet requests, each passing when the proposal has the mode it
  should, an Amount (money) and Date (date) when it's spending, the fields the request names,
  and nothing counted as spending that isn't money (mileage, income).
- Estimates: "pretty sure" and "maybe" end as the person's estimate, never as checked.
- Receipts (EX2a, `receipt_cases.json`, written fresh): each becomes an entry with its total,
  and every value filled from it is quoted from the receipt word for word.
- Questions (EX2b): shielded for the strictest, gentlest person, they stay offers.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from tests.evals.pacing import PacedFactory
from tests.evals.providers import EvalBackend
from tests.evals.runner import use_backend
from tests.fakes.telegram_api import FakeTelegram
from tests.fixtures.family import SeededFamily
from tests.scenarios.harness import Scenario
from themi import clock
from themi.accounts.store import SYSTEM
from themi.channels.pda import find_demands
from themi.core import keys
from themi.localtime import to_utc_iso
from themi.storage.secrets import Secret
from themi_home.expense_matching import quoted
from themi_home.expenses import FieldDef

# (the request, its mode, whether it counts as spending, words some field label must have)
REQUESTS: list[tuple[str, str, bool, tuple[str, ...]]] = [
    ("start a sheet for business travel", "business", True, ("purpose",)),
    ("track what we spend on the kitchen project", "custom", True, ()),
    ("a sheet for the kids' school costs, with which kid", "personal", True, ("kid",)),
    ("keep track of my mileage for work", "business", False, ("mile",)),
    ("track the dog's vet bills and what each visit was for", "personal", True, ("vet", "for")),
    ("a sheet for client lunches with who came", "business", True, ("who",)),
    ("track our holiday spending, by person", "personal", True, ("person",)),
    ("log the freelance income I get, by client", "business", False, ("client",)),
    ("track gifts we buy this year and who they're for", "personal", True, ("for",)),
    ("a budget sheet for the garden makeover, with the store", "custom", True, ("store",)),
]
NEEDED = 8


def problems(data: dict, mode: str, spending: bool, words: tuple[str, ...]) -> list[str]:
    found = []
    sheets = data["sheets"]
    if len(sheets) != 1:
        return [f"{len(sheets)} sheets"]
    sheet = sheets[0]
    labels = [f["label"].lower() for f in sheet["fields"]]
    types = {f["label"].lower(): f["type"] for f in sheet["fields"]}
    if sheet["mode"] != mode and not (
        mode in ("personal", "custom") and sheet["mode"] != "business"
    ):
        found.append(f"mode {sheet['mode']}")
    if spending and (types.get("amount") != "money" or types.get("date") != "date"):
        found.append(f"no amount and date: {labels}")
    if sheet["counts_as_spending"] != spending:
        found.append(f"counts as spending: {sheet['counts_as_spending']}")
    for word in words:
        if not any(word in label for label in labels):
            found.append(f"no field with {word!r}: {labels}")
    return found


async def test_expense_sheet_fields(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
) -> None:
    scenario = Scenario(family, fake_telegram, real_models=True, provider_factory=eval_factory)
    use_backend(scenario, eval_backend)
    await scenario.start()
    misses = []
    try:
        sheets = scenario.app.services.maybe(keys.expense_sheets)
        assert sheets is not None
        erin = scenario.member("Erin")
        for request, mode, spending, words in REQUESTS:
            data = await sheets._ask(erin, request, None, None, "")
            if data is None:
                misses.append(f"{request}: no proposal")
            elif found := problems(data, mode, spending, words):
                misses.append(f"{request}: {'; '.join(found)}")
            if eval_backend.pace:
                await asyncio.sleep(eval_backend.pace)
    finally:
        await scenario.stop()
    print(f"\nexpense sheet fields: {len(REQUESTS) - len(misses)}/{len(REQUESTS)}")
    for miss in misses:
        print("  missed", miss)
    assert len(REQUESTS) - len(misses) >= NEEDED, "; ".join(misses)


ESTIMATES = [
    ("About $40 on paint for the kitchen project, pretty sure", 0.8),
    ("Maybe $25 on brushes for the kitchen project", 0.5),
]


async def test_expense_sheet_estimates(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
) -> None:
    scenario = Scenario(family, fake_telegram, real_models=True, provider_factory=eval_factory)
    use_backend(scenario, eval_backend)
    await scenario.start()
    misses = []
    try:
        expenses = scenario.app.services.maybe(keys.expenses)
        assert expenses is not None
        sheet = expenses.make_sheet(
            expenses.make_book("Kitchen project", None), "Kitchen project", "custom",
            [FieldDef("amount", "Amount", "money", critical=True),
             FieldDef("date", "Date", "date", critical=True), FieldDef("what", "What", "text")],
            keywords=("kitchen", "paint", "brushes"),
        )  # fmt: skip
        for said, sure in ESTIMATES:
            before = {e.id for e in expenses.entries([sheet.id])}
            await scenario.say("Erin", said)
            new = [e for e in expenses.entries([sheet.id]) if e.id not in before]
            amount = new[0].values.get("amount") if new else None
            if amount is None or amount.status != "user_estimate" or amount.confidence != sure:
                misses.append(f"{said}: {amount}")
            if eval_backend.pace:
                await asyncio.sleep(eval_backend.pace)
    finally:
        await scenario.stop()
    print(f"\nexpense sheet estimates: {len(ESTIMATES) - len(misses)}/{len(ESTIMATES)}")
    assert not misses, "; ".join(misses)


# EX2a: receipts read by a real model, each one's filled values quoted from the receipt.
RECEIPTS = json.loads((Path(__file__).parent / "receipt_cases.json").read_text())


async def test_expense_sheet_receipts(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
) -> None:
    scenario = Scenario(family, fake_telegram, real_models=True, provider_factory=eval_factory)
    use_backend(scenario, eval_backend)
    await scenario.start()
    misses = []
    try:
        db = scenario.app.db
        pantry = scenario.app.services.maybe(keys.pantry)
        expenses = scenario.app.services.maybe(keys.expenses)
        assert pantry is not None and expenses is not None
        erin = scenario.member("Erin")
        account = scenario.app.store.add_linked_account(
            SYSTEM, erin.id, "gmail", "erin@example.com", Secret("1//eval")
        )
        expenses.make_sheet(
            expenses.make_book("Kitchen project", None), "Kitchen project", "custom",
            [FieldDef("amount", "Amount", "money", critical=True),
             FieldDef("date", "Date", "date", critical=True), FieldDef("vendor", "Vendor", "text")],
            keywords=("paint", "brush"),
        )  # fmt: skip
        for n, case in enumerate(RECEIPTS):
            name, _, address = case["sender"].partition(" <")
            now = to_utc_iso(clock.now())
            email_id = db.execute(
                "INSERT INTO emails (account_id, gmail_id, thread_id, from_name, from_address, "
                "subject, body_text, category, received_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'receipt', ?, ?)",
                (account.id, f"g{n}", f"t{n}", name, address.rstrip(">"), case["subject"],
                 case["text"], now, now),
            )  # fmt: skip
            await pantry.read_receipt(email_id)
            entry = expenses.entry_for_email(email_id)
            source = f"{name}\n{case['subject']}\n{case['text']}"
            if entry is None:
                misses.append(f"{case['subject']}: no entry")
                continue
            if entry.get("amount") != case["total"]:
                misses.append(f"{case['subject']}: amount {entry.get('amount')}")
            for key, value in entry.values.items():
                if key in ("date", "category") or value.value is None:
                    continue
                if not quoted(value.evidence, source):
                    misses.append(f"{case['subject']}: {key} quoted {value.evidence!r}")
            if eval_backend.pace:
                await asyncio.sleep(eval_backend.pace)
    finally:
        await scenario.stop()
    print(f"\nexpense sheet receipts: {len(RECEIPTS) - len(misses)}/{len(RECEIPTS)}")
    for miss in misses:
        print("  missed", miss)
    assert len(misses) <= 1, "; ".join(misses)


# EX2b: Themi's questions about expense sheets, as a person at the strictest shielding with
# gentle phrasing gets them: offers, never "you need to".
QUESTIONS = [
    "What did eating out at Merit on Tue 20 Oct come to?",
    "For the $40.00 one on Kitchen project on Tue 20 Oct: what was the vendor?",
    "Business expenses with something still empty, whenever suits:\n"
    "- Merit on Wed 21 Oct (Business): no amount yet",
]
NEED_TO = re.compile(r"\byou (?:need|have|must|should)\b|\bmake sure\b|\bdon'?t forget\b", re.I)


async def test_expense_sheet_questions(
    family: SeededFamily,
    fake_telegram: FakeTelegram,
    eval_backend: EvalBackend,
    eval_factory: PacedFactory,
) -> None:
    scenario = Scenario(family, fake_telegram, real_models=True, provider_factory=eval_factory)
    use_backend(scenario, eval_backend)
    await scenario.start()
    misses = []
    try:
        erin = scenario.app.store.update_settings(
            SYSTEM, scenario.member("Erin").id, pda_enabled=True, pda_strength=3, phrasing="gentle"
        )
        for text in QUESTIONS:
            shielded = await scenario.app.outbox.shield.apply(text, erin)
            if NEED_TO.search(shielded.text) or find_demands(shielded.text, 3):
                misses.append(f"{text!r} -> {shielded.text!r}")
    finally:
        await scenario.stop()
    assert not misses, "; ".join(misses)
