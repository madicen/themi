from collections.abc import Iterator

import pytest

from themi.accounts import AccountsError, AccountStore, InvalidValue, Role
from themi.accounts.setup import parse_money_to_cents, run_init, run_invite


def make_io(answers: list[str]):
    asked: list[str] = []
    said: list[str] = []
    feed: Iterator[str] = iter(answers)

    def ask(question: str, default: str | None) -> str:
        asked.append(question)
        return next(feed)

    return ask, said.append, asked, said


@pytest.mark.parametrize(
    ("text", "cents"), [("200", 200_00), ("$150.50", 150_50), ("1,250", 1250_00), ("", 0)]
)
def test_parse_money(text: str, cents: int) -> None:
    assert parse_money_to_cents(text) == cents


@pytest.mark.parametrize("text", ["lots", "-5"])
def test_parse_money_rejects_nonsense(text: str) -> None:
    with pytest.raises(InvalidValue):
        parse_money_to_cents(text)


def test_init_creates_family_admin_and_invite(store: AccountStore) -> None:
    ask, say, _asked, said = make_io(["The Household", "", "$200", "Erin"])
    admin, code = run_init(store, ask, say)
    family = store.get_family()
    assert family is not None
    assert (family.name, family.timezone, family.takeout_budget_cents) == (
        "The Household",
        "America/Los_Angeles",
        200_00,
    )
    assert admin.name == "Erin" and admin.role is Role.ADMIN
    assert any(f"/start {code}" in line for line in said)
    assert store.redeem_invite(code, 1001).id == admin.id


def test_init_re_asks_until_answers_are_valid(store: AccountStore) -> None:
    ask, say, asked, said = make_io(["", "Household", "Nowhere/Land", "UTC", "lots", "50", "Erin"])
    run_init(store, ask, say)
    assert asked.count("Family name") == 2
    assert asked.count("Timezone") == 2
    assert any("isn't a timezone" in line for line in said)
    assert store.get_family().timezone == "UTC"  # type: ignore[union-attr]


def test_init_refuses_when_family_exists(store: AccountStore) -> None:
    ask, say, *_ = make_io(["Household", "UTC", "0", "Erin"])
    run_init(store, ask, say)
    with pytest.raises(AccountsError, match="already has a family"):
        run_init(store, ask, say)


def test_cancelled_init_saves_nothing(store: AccountStore) -> None:
    def ask(question: str, default: str | None) -> str:
        if question.startswith("Your first name"):
            raise EOFError
        return {"Family name": "Household"}.get(question, "")

    with pytest.raises(EOFError):
        run_init(store, ask, lambda _: None)
    assert store.get_family() is None


def test_invite_new_and_unpaired_members(store: AccountStore) -> None:
    ask, say, *_ = make_io(["Household", "UTC", "0", "Erin"])
    run_init(store, ask, say)
    husband, first_code = run_invite(store, "Husband")
    assert husband.role is Role.MEMBER
    again, second_code = run_invite(store, "husband")
    assert again.id == husband.id and second_code != first_code
    store.redeem_invite(second_code, 1002)
    with pytest.raises(AccountsError, match="already paired"):
        run_invite(store, "Husband")
    helper, _ = run_invite(store, "Helper", Role.ADMIN)
    assert helper.is_admin
