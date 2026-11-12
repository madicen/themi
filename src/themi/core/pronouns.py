"""Themi's pronouns, chosen by the family (F35a, Erin's idea #176).

One household choice, since Themi is the same assistant to both: it/its (the default, as
before), she/her, he/him, they/them, or just the name ("Themi" every time, no pronoun).
The list is the prompt's stand-in until Erin gives hers. Themi speaks of itself in the first
person, so the choice shows where Themi is talked about in the third person: a line in both
system prompts (the model's own words, relays included), and the few fixed texts that say
"its own" or "it's back". Set on My settings or in chat (`set_themi_pronouns`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from themi.accounts.household import HouseholdSettings
from themi.core.tools import ToolContext, ToolFailed, tool

if TYPE_CHECKING:
    from themi.accounts.store import AccountStore

Choice = Literal["it", "she", "he", "they", "name"]
CHOICES: dict[str, str] = {
    "it": "it/its",
    "she": "she/her",
    "he": "he/him",
    "they": "they/them",
    "name": "just the name",
}
DONE_TEXT = "Done. I'll go by {label}."
NAME_DONE_TEXT = "Done. I'll go by just my name."


class PronounSettings(HouseholdSettings):
    module: ClassVar[str] = "themi"
    themi_pronouns: Choice = "it"


@dataclass(frozen=True)
class Pronouns:
    """The words for Themi in the third person."""

    subject: str  # "she"
    possessive: str  # "her"
    on_own: str  # "on her own"
    back: str  # "she's back"
    will: str  # "she'll"


WORDS: dict[str, Pronouns] = {
    "it": Pronouns("it", "its", "on its own", "it's back", "it'll"),
    "she": Pronouns("she", "her", "on her own", "she's back", "she'll"),
    "he": Pronouns("he", "his", "on his own", "he's back", "he'll"),
    "they": Pronouns("they", "their", "on their own", "they're back", "they'll"),
    "name": Pronouns("Themi", "Themi's", "on Themi's own", "Themi's back", "Themi will"),
}


def pronouns(choice: str) -> Pronouns:
    return WORDS.get(choice, WORDS["it"])


def chosen(store: AccountStore) -> str:
    return store.household(PronounSettings).themi_pronouns


def system_line(choice: str) -> str:
    """The system prompts' line for the choice: none for it/its, as before."""
    if choice == "name":
        return (
            "Themi goes by just the name: when anyone, you included, speaks of Themi in the "
            'third person, say "Themi" each time, never "it", "she", "he" or "they".'
        )
    if choice not in CHOICES or choice == "it":
        return ""
    return (
        f"Themi uses {CHOICES[choice]}: when anyone, you included, speaks of Themi in the "
        f'third person, it\'s "{WORDS[choice].subject}", never "it".'
    )


def with_line(system: str, choice: str) -> str:
    line = system_line(choice)
    return f"{system.rstrip()}\n\n{line}\n" if line else system


def label(choice: str) -> str:
    return CHOICES.get(choice, CHOICES["it"])


def done_text(choice: str) -> str:
    return NAME_DONE_TEXT if choice == "name" else DONE_TEXT.format(label=label(choice))


@tool(
    "set_themi_pronouns",
    "Change the pronouns used for Themi itself, when someone asks ('use she/her for "
    "yourself', 'just go by Themi'). pronouns: it, she, he, they, or name (just the name, no "
    "pronoun). One choice for everyone here.",
    {"pronouns": {"type": "string", "enum": list(CHOICES)}},
)
async def set_themi_pronouns(ctx: ToolContext, args: dict[str, Any]) -> str:
    choice = str(args["pronouns"]).strip().lower()
    if choice not in CHOICES:
        raise ToolFailed("Which: it, she, he, they, or just the name?")
    ctx.services.store.set_household_value(PronounSettings.module, "themi_pronouns", choice)
    said = done_text(choice)
    ctx.replies.append(said)
    ctx.asked.append(said)  # done as they asked, and said: the turn ends here (P2b)
    return said
