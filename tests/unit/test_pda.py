from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.fixtures.family import SeededFamily
from themi.accounts import SYSTEM, Member
from themi.ai import PermanentError
from themi.ai.types import CallKind
from themi.channels.events import Button
from themi.channels.pda import (
    REWRITE_SCHEMA,
    AIRewriter,
    Flag,
    PdaShield,
    Rewrite,
    find_demands,
    soften,
)

CORPORA = Path(__file__).parents[1] / "fixtures" / "pda"


def corpus(name: str) -> list[str]:
    lines = (CORPORA / name).read_text().splitlines()
    return [line for line in lines if line.strip() and not line.startswith("#")]


DEMANDING = corpus("demanding.txt")
ACCEPTABLE = corpus("acceptable.txt")


def test_corpora_are_big_enough() -> None:
    assert len(DEMANDING) >= 60 and len(ACCEPTABLE) >= 60


@pytest.mark.parametrize("line", DEMANDING)
def test_every_demanding_line_is_flagged_at_default_strength(line: str) -> None:
    assert find_demands(line, 2), line


@pytest.mark.parametrize("line", ACCEPTABLE)
def test_no_acceptable_line_is_flagged_at_default_strength(line: str) -> None:
    assert find_demands(line, 2) == [], line


@pytest.mark.parametrize("line", DEMANDING)
def test_softened_lines_pass_even_the_strictest_check(line: str) -> None:
    softened = soften(line)
    assert find_demands(softened, 3) == [], (line, softened)
    assert softened[:1].isupper()


@pytest.mark.parametrize(
    ("text", "lowest_level"),
    [
        ("You need to call the vet.", 0),
        ("Reply ASAP.", 0),
        ("Don't forget the vet.", 1),
        ("Make sure the door is locked.", 1),
        ("Move the laundry.", 2),
        ("The cat needs to be fed.", 3),
        ("A signature is required.", 3),
    ],
)
def test_rules_build_on_each_other(text: str, lowest_level: int) -> None:
    for strength in range(4):
        flagged = bool(find_demands(text, strength))
        assert flagged == (strength >= lowest_level), (text, strength)


def test_questions_and_offers_are_not_commands() -> None:
    for text in ("Do you want rice too?", "Call me crazy, but it's sunny.", "Move it later?"):
        assert find_demands(text, 2) == [], text


def test_softener_keeps_the_information() -> None:
    assert soften("Don't forget to take your meds at 9pm!") == (
        "Whenever it suits, you could take your meds at 9pm."
    )
    assert soften("Please call the vet about Luna right away.") == (
        "If you're up for it, you could call the vet about Luna whenever it suits."
    )


# ----- the shield -------------------------------------------------------------


class FakeRewriter:
    def __init__(self, result: Rewrite | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, list[Flag], CallKind]] = []

    async def rewrite(
        self, text: str, member: Member, flags: Sequence[Flag], kind: CallKind
    ) -> Rewrite:
        self.calls.append((text, list(flags), kind))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_clean_text_skips_the_rewriter(family: SeededFamily) -> None:
    rewriter = FakeRewriter(Rewrite("unused"))
    result = await PdaShield(rewriter).apply("The washer finished.", family.erin)
    assert (result.text, result.changed, result.method) == (
        "The washer finished.",
        False,
        "unchanged",
    )
    assert rewriter.calls == []


async def test_flagged_text_is_rewritten(family: SeededFamily) -> None:
    rewriter = FakeRewriter(Rewrite("Whenever you have a moment, the washer's done."))
    result = await PdaShield(rewriter).apply(
        "Move the laundry now.", family.erin, kind=CallKind.BACKGROUND
    )
    assert result.text == "Whenever you have a moment, the washer's done."
    assert result.method == "rewritten" and result.changed
    (call,) = rewriter.calls
    assert call[2] is CallKind.BACKGROUND and call[1][0].rule == "imperative"


async def test_rewrite_options_become_reply_buttons(family: SeededFamily) -> None:
    rewriter = FakeRewriter(Rewrite("The washer's done.", ("Dryer now", "Later tonight")))
    result = await PdaShield(rewriter).apply("Move the laundry.", family.erin)
    assert [(b.label, b.kind, b.payload) for b in result.buttons] == [
        ("Dryer now", "reply", {"text": "Dryer now"}),
        ("Later tonight", "reply", {"text": "Later tonight"}),
    ]


async def test_callers_buttons_win_over_suggested_options(family: SeededFamily) -> None:
    rewriter = FakeRewriter(Rewrite("The washer's done.", ("A", "B")))
    mine = (Button("Go ahead", "approval", {"id": 1}),)
    result = await PdaShield(rewriter).apply("Move the laundry.", family.erin, buttons=mine)
    assert result.buttons == mine


async def test_a_rewrite_that_still_demands_is_softened(family: SeededFamily) -> None:
    rewriter = FakeRewriter(Rewrite("You need to move the laundry."))
    result = await PdaShield(rewriter).apply("Move the laundry.", family.erin)
    assert result.method == "softened"
    assert result.text == "If you're up for it, you could move the laundry."


async def test_ai_failure_falls_back_to_the_softener(family: SeededFamily) -> None:
    result = await PdaShield(FakeRewriter(PermanentError("no key"))).apply(
        "Don't forget the vet at 3.", family.erin
    )
    assert result.method == "softened" and find_demands(result.text, 3) == []


async def test_no_rewriter_means_softener_only(family: SeededFamily) -> None:
    result = await PdaShield(None).apply("You must reply to the landlord.", family.erin)
    assert result.text == "You might reply to the landlord."


async def test_shielding_follows_each_members_settings(family: SeededFamily) -> None:
    shield = PdaShield(None)
    husband = family.store.update_settings(SYSTEM, family.husband.id, pda_strength=1)
    assert (await shield.apply("Move the laundry.", husband)).changed is False
    erin_off = family.store.update_settings(SYSTEM, family.erin.id, pda_enabled=False)
    assert (await shield.apply("You need to move it.", erin_off)).changed is False


async def test_ai_rewriter_uses_the_members_pda_task(family: SeededFamily) -> None:
    from tests.fakes.scripted_provider import ScriptedProvider
    from themi.ai.router import AIRouter
    from themi.ai.settings import AISettingsStore, AITask, RouteEntry
    from themi.storage.secrets import Cipher, Secret, generate_key

    provider = ScriptedProvider()
    provider.queue_structured({"text": "The washer's done.", "options": ["Dryer now", "Later"]})
    ai = AISettingsStore(family.db, Cipher(generate_key()))
    backend = ai.add_backend(
        family.erin, family.erin.id, "Local", "ollama", model="m", api_key=Secret("x")
    )
    ai.set_chain(family.erin, family.erin.id, AITask.PDA_REWRITE, [RouteEntry(backend.id)])
    router = AIRouter(ai, factory=lambda config: provider)

    rewrite = await AIRewriter(router).rewrite(
        "Move the laundry.", family.erin, [Flag("imperative", 2, "move")], CallKind.INTERACTIVE
    )
    assert rewrite == Rewrite("The washer's done.", ("Dryer now", "Later"))
    request = provider.last_request
    assert request.schema == REWRITE_SCHEMA
    assert "<message>\nMove the laundry.\n</message>" in request.prompt
    assert '"move"' in request.prompt


def test_a_leading_label_isnt_an_opening_command() -> None:
    """ "Check-in:" (Erin's rules 7 and 8) and "Due today:" label a message; they aren't orders."""
    assert find_demands("Check-in: A glass of water might feel good about now.") == []
    assert find_demands("Due today: Call the plumber. Done already, or later?") == []
    assert [f.rule for f in find_demands("Check in with the vet.")] == ["imperative"]
