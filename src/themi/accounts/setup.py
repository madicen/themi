"""First-run setup (`themi init`) and adding members (`themi invite`).

The prompts are plain functions over `ask`/`say` callables, so tests drive
them without a terminal.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from themi.accounts.models import Member, Role
from themi.accounts.store import SYSTEM, AccountsError, AccountStore, InvalidValue

Ask = Callable[[str, str | None], str]  # (question, default) -> answer
Say = Callable[[str], None]

DEFAULT_TIMEZONE = "America/Los_Angeles"


def parse_money_to_cents(text: str) -> int:
    cleaned = text.strip().replace("$", "").replace(",", "")
    try:
        amount = Decimal(cleaned or "0")
    except InvalidOperation as exc:
        raise InvalidValue(f"{text!r} isn't an amount like 200 or 150.50") from exc
    if amount < 0:
        raise InvalidValue("the amount can't be negative")
    return int((amount * 100).quantize(Decimal("1")))


def _ask_until_valid[T](
    ask: Ask, say: Say, question: str, default: str | None, convert: Callable[[str], T]
) -> T:
    while True:
        answer = ask(question, default).strip() or (default or "")
        try:
            return convert(answer)
        except InvalidValue as exc:
            say(f"  {exc}")


def start_link(bot_username: str, code: str) -> str:
    """A t.me link that opens the bot with a Start button which sends `/start <code>`."""
    return f"https://t.me/{bot_username.lstrip('@')}?start={code}"


def pairing_instructions(member: Member, code: str, bot_username: str | None = None) -> str:
    lines = [
        f"Invite code for {member.name}: {code}",
        f"Open the Themi bot in Telegram and send:  /start {code}",
    ]
    if bot_username:
        lines.append(
            f"Or tap this link on their phone and press Start:  {start_link(bot_username, code)}"
        )
    lines.append("The code works once and expires in 24 hours.")
    return "\n".join(lines)


def run_init(
    store: AccountStore, ask: Ask, say: Say, bot_username: str | None = None
) -> tuple[Member, str]:
    """Create the family and its first admin. Returns the admin and their invite code."""
    if store.get_family() is not None:
        raise AccountsError("this server already has a family; use `themi invite` to add people")

    say("Setting up Themi for your family.")
    family_name = _ask_until_valid(ask, say, "Family name", None, _non_empty("a family name"))
    timezone = _ask_until_valid(ask, say, "Timezone", DEFAULT_TIMEZONE, _timezone)
    budget = _ask_until_valid(
        ask,
        say,
        "Monthly takeout budget in dollars (changeable later)",
        "0",
        parse_money_to_cents,
    )
    admin_name = _ask_until_valid(
        ask, say, "Your first name (you'll be the admin)", None, _non_empty("a name")
    )

    with store.db.transaction():
        store.create_family(family_name, timezone, takeout_budget_cents=budget)
        admin = store.create_member(SYSTEM, admin_name, Role.ADMIN)
        code = store.create_invite(SYSTEM, admin.id)
    say(pairing_instructions(admin, code, bot_username))
    return admin, code


def run_invite(store: AccountStore, name: str, role: Role = Role.MEMBER) -> tuple[Member, str]:
    """Invite a new member, or issue a fresh code to an existing one who hasn't paired yet."""
    existing = store.member_by_name(name)
    if existing is not None:
        if existing.telegram_user_id is not None:
            raise AccountsError(f"{existing.name} is already paired with Telegram")
        member = existing
    else:
        member = store.create_member(SYSTEM, name, role)
    return member, store.create_invite(SYSTEM, member.id)


def _non_empty(what: str) -> Callable[[str], str]:
    def convert(answer: str) -> str:
        if not answer.strip():
            raise InvalidValue(f"please enter {what}")
        return answer.strip()

    return convert


def _timezone(answer: str) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(answer)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidValue(f"{answer!r} isn't a timezone name like America/Los_Angeles") from exc
    return answer
