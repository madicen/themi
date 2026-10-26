"""PDA shielding: catch demand phrasing before it reaches someone, and soften it.

The checker is rule-based and runs on every outgoing message for members with
shielding on. Each member has a strictness level from 0 to 3; higher levels
add rule sets on top of the lower ones:

0  hard demands: "you need to", "you must", "right now", "ASAP"
1  + reminders and pressure: "don't forget", "remember to", "make sure", "you should"
2  + commands at the start of a sentence: "Move the laundry." (the default)
3  + pressure verbs whatever the subject: "the cat needs to be fed", "required"

Flagged text is rewritten by the member's `pda_rewrite` AI task into indirect
phrasing or a two-option choice, then checked again. When the AI is down or
its rewrite still fails, a deterministic softener takes over. Its output
always passes the checker, so nothing demanding goes out either way.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from themi.accounts.models import Member
from themi.ai.router import AIRouter
from themi.ai.settings import AITask
from themi.ai.types import CallKind
from themi.channels.events import Button

log = logging.getLogger(__name__)

MIN_STRENGTH, MAX_STRENGTH = 0, 3


@dataclass(frozen=True)
class Flag:
    rule: str
    level: int
    match: str


@dataclass(frozen=True)
class _Rule:
    name: str
    level: int
    pattern: re.Pattern[str]


def _rule(name: str, level: int, pattern: str) -> _Rule:
    return _Rule(name, level, re.compile(pattern, re.IGNORECASE))


PHRASE_RULES = [
    _rule(
        "you-need-to", 0, r"\byou(?:'ll| will)? (?:really |just |still )?(?:need|have|must) to\b"
    ),
    _rule("you-must", 0, r"\byou(?:'d| really| just)? must\b"),
    _rule("youve-got-to", 0, r"\byou(?:'ve| have)? got to\b|\byou gotta\b"),
    _rule("right-now", 0, r"\b(?:right now|immediately|asap|right away|straight away|at once)\b"),
    _rule("dont-forget", 1, r"\b(?:don'?t|do not) forget\b"),
    _rule("remember-to", 1, r"\bremember to\b"),
    _rule("make-sure", 1, r"\bmake sure\b"),
    _rule("you-should", 1, r"\byou(?:'d| really| still)? should\b|\byou(?:'d| had) better\b"),
    _rule(
        "pressure-verb",
        3,
        r"\b(?:must|have to|has to|need to|needs to|should|required|mandatory)\b",
    ),
]

# Verbs that make a command when they open a sentence ("Move the laundry.").
IMPERATIVE_VERBS = frozenset(
    """
    add answer book bring buy call cancel change check clean clear do drop email empty feed
    fill finish fix get go grab hang hurry load make move order pay pick plan put read
    refill remove renew reply respond run schedule send sign start stop submit switch take
    text throw tidy turn unload update wash water wipe write
    """.split()
)
# "Do you…", "Call me…" and friends are questions or offers, not commands.
_NOT_A_COMMAND_NEXT = frozenset({"you", "we", "i", "they", "it", "me", "us", "anything"})
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")
_WORD = re.compile(r"[a-z']+")


def find_demands(text: str, strength: int = 2) -> list[Flag]:
    """Every demand in `text` at or below `strength`."""
    flags: list[Flag] = []
    for rule in PHRASE_RULES:
        if rule.level <= strength:
            flags.extend(
                Flag(rule.name, rule.level, m.group(0)) for m in rule.pattern.finditer(text)
            )
    if strength >= 2:
        for sentence in _SENTENCE.findall(text):
            command = _opening_command(sentence)
            if command:
                flags.append(Flag("imperative", 2, command))
    return flags


_LABEL = re.compile(r"^\s*[\w'-]+(?:\s+[\w'-]+){0,2}:")


def _opening_command(sentence: str) -> str | None:
    if sentence.rstrip().endswith("?"):
        return None  # "Dryer now, or later?" offers a choice; it isn't a command
    if _LABEL.match(sentence):
        return None  # "Check-in: ..." or "Due today: ..." labels the message
    words = _WORD.findall(sentence.lower())
    if not words:
        return None
    if words[0] == "please" and len(words) > 1:
        words = words[1:]
    if words[0] not in IMPERATIVE_VERBS:
        return None
    if len(words) > 1 and words[1] in _NOT_A_COMMAND_NEXT:
        return None
    return words[0]


# ----- deterministic softener -------------------------------------------------

_SOFTENERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), r)
    for p, r in [
        (r"\byou(?:'ll| will)? (?:really |just |still )?(?:need|have|must) to\b", "you could"),
        (r"\byou(?:'d| really| just)? must\b", "you might"),
        (r"\byou(?:'ve| have)? got to\b|\byou gotta\b", "you could"),
        (
            r"\b(?:right now|immediately|asap|right away|straight away|at once)\b",
            "whenever it suits",
        ),
        (r"\b(?:don'?t|do not) forget to\b", "whenever it suits, you could"),
        (r"\b(?:don'?t|do not) forget\b", "in case it's handy, there's"),
        (r"\bremember to\b", "if it's useful, you could"),
        (r"\bmake sure (?:to|that you)\b", "it might help to"),
        (r"\bmake sure\b", "it might help if"),
        (r"\byou(?:'d| really| still)? should\b|\byou(?:'d| had) better\b", "you could"),
        (r"\bmust\b", "could"),
        (r"\bhave to\b", "could"),
        (r"\bhas to\b", "can"),
        (r"\bneeds to\b", "can"),
        (r"\bneed to\b", "could"),
        (r"\bshould\b", "could"),
        (r"\bmandatory\b", "optional"),
        (r"\brequired\b", "helpful"),
    ]
]


def soften(text: str) -> str:
    """Rephrase demands without the AI. The result always passes `find_demands`."""
    for pattern, replacement in _SOFTENERS:
        text = pattern.sub(replacement, text)
    text = "".join(_soften_sentence(s) for s in re.split(r"(?<=[.!?\n])", text))
    text = re.sub(r"!+", ".", text)
    # Substitutions can leave a sentence starting in lower case.
    return re.sub(r"(^|[.?]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)


def _soften_sentence(sentence: str) -> str:
    if _opening_command(sentence) is None:
        return sentence
    leading = sentence[: len(sentence) - len(sentence.lstrip())]
    body = sentence.lstrip()
    if body.lower().startswith("please "):
        body = body[len("please ") :]
    return f"{leading}If you're up for it, you could {body[:1].lower()}{body[1:]}"


# ----- the shield -------------------------------------------------------------


@dataclass(frozen=True)
class Rewrite:
    text: str
    options: tuple[str, ...] = ()  # two short choices, when the message implies a decision


class Rewriter(Protocol):
    async def rewrite(
        self, text: str, member: Member, flags: Sequence[Flag], kind: CallKind
    ) -> Rewrite: ...


@dataclass(frozen=True)
class Shielded:
    text: str
    buttons: tuple[Button, ...] = ()
    changed: bool = False
    method: str = "unchanged"  # unchanged | rewritten | softened
    flags: tuple[Flag, ...] = field(default=())


class PdaShield:
    def __init__(self, rewriter: Rewriter | None) -> None:
        self.rewriter = rewriter

    async def apply(
        self,
        text: str,
        member: Member,
        *,
        buttons: Sequence[Button] = (),
        kind: CallKind = CallKind.INTERACTIVE,
    ) -> Shielded:
        if not member.pda_enabled:
            return Shielded(text, tuple(buttons))
        strength = member.pda_strength
        own, quotes = split_quotes(text)
        flags = find_demands(own, strength)
        if not flags:
            return Shielded(text, tuple(buttons))
        if self.rewriter is not None:
            try:
                rewrite = await self.rewriter.rewrite(own, member, flags, kind)
            except Exception as exc:  # the AI being down must never block a message
                log.info("PDA rewrite unavailable (%s); softening instead", type(exc).__name__)
            else:
                rewritten = join_quotes(rewrite.text, quotes)
                if rewrite.text.strip() and not find_demands(rewrite.text, strength) and rewritten:
                    extra = () if buttons else _option_buttons(rewrite.options)
                    return Shielded(
                        rewritten, tuple(buttons) or extra, True, "rewritten", tuple(flags)
                    )
                log.info("PDA rewrite still read as a demand; softening instead")
        softened = soften(own)
        if find_demands(softened, strength):  # pragma: no cover - soften() guarantees this
            log.warning("softener left a demand in place: %s", find_demands(softened, strength))
        restored = join_quotes(softened, quotes) or softened
        return Shielded(restored, tuple(buttons), True, "softened", tuple(flags))


# ----- quotes -----------------------------------------------------------------
#
# Lines starting with "> " quote someone else's words verbatim (an email draft
# awaiting approval, say). They're not Themi asking anything of the reader, so
# they're never checked or rewritten; the text around them still is.

QUOTE_PREFIX = "> "
_PLACEHOLDER = "⟦quote {n}⟧"


def split_quotes(text: str) -> tuple[str, list[str]]:
    """The text with each run of quote lines replaced by a placeholder, and the runs."""
    out: list[str] = []
    quotes: list[str] = []
    run: list[str] = []
    for line in text.split("\n"):
        if line.startswith(QUOTE_PREFIX) or line == ">":
            run.append(line)
            continue
        if run:
            quotes.append("\n".join(run))
            out.append(_PLACEHOLDER.format(n=len(quotes)))
            run = []
        out.append(line)
    if run:
        quotes.append("\n".join(run))
        out.append(_PLACEHOLDER.format(n=len(quotes)))
    return "\n".join(out), quotes


def join_quotes(text: str, quotes: Sequence[str]) -> str | None:
    """Put the quotes back. None if a placeholder went missing (so the caller can fall back)."""
    for n, quote in enumerate(quotes, start=1):
        marker = _PLACEHOLDER.format(n=n)
        if marker not in text:
            return None
        text = text.replace(marker, quote)
    return text


def _option_buttons(options: Sequence[str]) -> tuple[Button, ...]:
    """Two-option choices become buttons that answer as if the person typed them."""
    cleaned = [o.strip() for o in options if o.strip()]
    if len(cleaned) != 2:
        return ()
    return tuple(Button(o[:40], "reply", {"text": o}) for o in cleaned)


REWRITE_SYSTEM = """\
You rephrase messages from a household assistant for someone who experiences
direct requests as pressure (a pathological demand avoidance profile).

Rewrite the message so it carries the same information with no commands,
deadlines or pressure. Use indirect, low-key phrasing ("whenever you have a
moment", "if it helps"). When the message implies a decision, you may offer
exactly two short options instead of an instruction. Keep facts, names,
numbers and times exactly as given. Add nothing new. Keep it as short as the
original or shorter. Keep placeholders such as ⟦quote 1⟧ exactly as they are, on
their own line. Never use "you need to", "you must", "you should",
"don't forget", "remember to", "make sure", "right now" or a sentence that
starts with a command verb.
"""

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "The rewritten message."},
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Two short choices if the message implies a decision, else empty.",
        },
    },
    "required": ["text", "options"],
    "additionalProperties": False,
}


class AIRewriter:
    """Rewrites through the member's own `pda_rewrite` backend."""

    def __init__(self, router: AIRouter) -> None:
        self._router = router

    async def rewrite(
        self, text: str, member: Member, flags: Sequence[Flag], kind: CallKind
    ) -> Rewrite:
        found = ", ".join(sorted({f'"{f.match}"' for f in flags}))
        prompt = f"Message:\n<message>\n{text}\n</message>\n\nPhrases that read as demands: {found}"
        result = await self._router.client_for(member.id, AITask.PDA_REWRITE).structured(
            REWRITE_SYSTEM, prompt, REWRITE_SCHEMA, max_tokens=2000, kind=kind
        )
        options = result.data.get("options") or []
        return Rewrite(str(result.data.get("text", "")), tuple(str(o) for o in options))
