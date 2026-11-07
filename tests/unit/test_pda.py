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
    result = await PdaShield(rewriter).apply("Move the laundry. Now, or later?", family.erin)
    assert [(b.label, b.kind, b.payload) for b in result.buttons] == [
        ("Dryer now", "reply", {"text": "Dryer now"}),
        ("Later tonight", "reply", {"text": "Later tonight"}),
    ]


async def test_a_message_that_asks_nothing_gets_no_choices(family: SeededFamily) -> None:
    """Bug #111: a report of what was done became a choice; its buttons ran the request
    again."""
    rewriter = FakeRewriter(Rewrite("The laundry is next.", ("Add", "Skip")))
    result = await PdaShield(rewriter).apply("Move the laundry.", family.erin)
    assert result.method == "rewritten" and result.buttons == ()


async def test_only_the_flagged_lines_are_rewritten(family: SeededFamily) -> None:
    """Bug #112: the rewrite got the whole reply and dropped both "Marked done" lines."""
    rewriter = FakeRewriter(Rewrite("Up next: the sheets, back tonight."))
    text = (
        'Marked done: "Vacuum upstairs bedroom". Nice work.\n'
        'Marked done: "Change sheets". Lovely.\n\nMove the sheets back tonight.'
    )
    result = await PdaShield(rewriter).apply(text, family.erin)
    assert result.text == (
        'Marked done: "Vacuum upstairs bedroom". Nice work.\n'
        'Marked done: "Change sheets". Lovely.\n\nUp next: the sheets, back tonight.'
    )
    assert [call[0] for call in rewriter.calls] == ["Move the sheets back tonight."]


async def test_each_flagged_run_is_softened_alone(family: SeededFamily) -> None:
    result = await PdaShield(None).apply(
        "Call the vet.\nIt's on Friday.\nBook a time.", family.erin
    )
    assert result.text == "Up next: call the vet.\nIt's on Friday.\nUp next: book a time."


async def test_callers_buttons_win_over_suggested_options(family: SeededFamily) -> None:
    rewriter = FakeRewriter(Rewrite("The washer's done.", ("A", "B")))
    mine = (Button("Go ahead", "approval", {"id": 1}),)
    result = await PdaShield(rewriter).apply("Move the laundry.", family.erin, buttons=mine)
    assert result.buttons == mine


async def test_a_rewrite_that_still_demands_is_softened(family: SeededFamily) -> None:
    rewriter = FakeRewriter(Rewrite("You need to move the laundry."))
    result = await PdaShield(rewriter).apply("Move the laundry.", family.erin)
    assert result.method == "softened"
    assert result.text == "Up next: move the laundry."


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


def test_right_now_describing_how_things_are_isnt_a_demand() -> None:
    """Prompt 28's open question, decided 2026-10-25: "right now" is only flagged as urging."""
    assert (
        find_demands("The grocery list is empty right now. Would you like to add anything?") == []
    )
    assert find_demands("We're out of eggs right now.") == []
    assert "right-now" in {f.rule for f in find_demands("Call the plumber right now.")}
    assert "right-now" in {f.rule for f in find_demands("You could start right now.")}
    assert "right-now" in {f.rule for f in find_demands("Do it immediately, the list is long.")}


def test_a_bulleted_list_is_a_list_not_orders() -> None:
    """Idea #19: a day's summary as "Tue 27 Oct:" and a bulleted list of what's on. "- Call
    the vet" lists a task; it isn't telling anyone to do it."""
    text = "Tue 27 Oct:\n- 10-11 am: Dentist\n- Call the vet\n- Clean the bird cage"
    assert find_demands(text, 3) == []
    assert find_demands("Call the vet now.", 3)  # a plain sentence still is


def test_putting_a_task_somewhere_is_a_report() -> None:
    # Bug #111: 'Put "Put sheets back on bed" on Michael's list for tonight.' said what was
    # done, and the shield took it for an order.
    assert find_demands('Put "Put sheets back on bed" on Michael\'s list for tonight.', 2) == []
    assert find_demands("Moved \u201cClean kitchen\u201d to Friday.", 2) == []
    assert find_demands("Put the sheets back on the bed.", 2)  # no title: still one


def test_a_quoted_task_name_isnt_an_order() -> None:
    # Bug #71: a task's name in a reply, '"Refill the water" is off the list'.
    assert find_demands('"Refill water and food bowls" is taken off the list.', 3) == []
    assert find_demands("“Call the vet” is due Friday.", 3) == []
    assert find_demands("Refill the water bowls.", 3)  # unquoted, still one


def test_sub_items_and_numbered_lines_arent_commands() -> None:
    """F29g (reply 271): "-- go upstairs" came out as "Up next: -- go upstairs"."""
    from themi.channels.pda import find_demands, soften

    shown = "Service dog tasks\n- body doubling\n-- go upstairs\n--- go downstairs"
    numbered = "Pets\n1. cats\n1.1. feed them\n1.1.1. buy kibble"
    for text in (shown, numbered):
        assert not [f for f in find_demands(text) if f.rule == "imperative"]
        assert soften(text, plain=True) == text
    assert soften("Go upstairs.", plain=True) == "Up next: go upstairs."  # a sentence still is


async def test_bug_161_a_rewrite_that_drops_the_suggestions_is_refused(
    family: SeededFamily,
) -> None:
    """Reply 292, word for word: three places to look became a heading."""
    original = (
        "Check old bank statements or credit card charges for payments to a dental office. "
        "Insurance provider portal logs show past claims and provider names. Email searches "
        "for 'dental', 'dentist', or 'appointment' pull up old confirmations."
    )
    rewriter = FakeRewriter(Rewrite("Options for finding past dental payments."))
    result = await PdaShield(rewriter).apply(original, family.erin)
    assert result.method == "softened"
    for kept in ("bank statements", "Insurance provider portal", "'dentist'"):
        assert kept in result.text


async def test_bug_160_a_rewrite_that_adds_a_name_or_number_is_refused(
    family: SeededFamily,
) -> None:
    from themi.channels.pda import unfaithful

    original = "I don't know their name. You could check old emails from the office."
    assert unfaithful(original, "It's Dr. Evans, at 650-555-0144.") == "added a number"
    assert unfaithful(original, "Maybe Dr. Evans knows; old emails might say.") == "added a name"
    assert unfaithful(original, "I don't know their name; old emails from the office may.") is None


async def test_bug_179_a_short_rewrite_that_drops_the_step_and_the_verb_is_refused(
    family: SeededFamily,
) -> None:
    """F34b, reply 351 (outbox 1482): "Step 1. Remove everything from the top tray." went out
    as "The top tray empty." A short line may be reworded, but not lose its step number."""
    from themi.channels.pda import unfaithful

    original = "Step 1. Remove everything from the top tray."
    assert unfaithful(original, "The top tray empty.") == "dropped a number"
    assert (
        unfaithful(original, "Step 1: everything out of the top tray, when you're ready.") is None
    )
    assert unfaithful("Move the laundry now.", "The washer's done.") is None  # still free
    rewriter = FakeRewriter(Rewrite("The top tray empty."))
    result = await PdaShield(rewriter).apply(original, family.erin)
    assert result.method == "softened" and "remove everything from the top tray" in result.text
