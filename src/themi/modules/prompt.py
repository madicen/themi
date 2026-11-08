"""CR8a: the system prompt, from the template's persona and each part's rules.

The persona (who Themi is, for whom) comes from the template. Every rule line is a
`PromptFragment`: a key, its section, its place in that section, and its words. The core
adds the rules every Themi keeps; a module adds the ones about its own feature. A template
can reword a fragment by its key (`[prompt]` in its TOML).

    How you speak:        (section "speak")
    How you act:          (section "act")
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

Section = Literal["speak", "act"]
SECTIONS: tuple[tuple[Section, str], ...] = (("speak", "How you speak:"), ("act", "How you act:"))


@dataclass(frozen=True)
class PromptFragment:
    key: str  # "tasks.medicines-a-critical-family": stable, for a template's rewording
    section: Section
    order: int  # place in its section, smallest first
    text: str  # one rule, "- ..." with its continuation lines


def compose_system(
    persona: str, fragments: Iterable[PromptFragment], overrides: Mapping[str, str] = {}
) -> str:
    """The persona, then each section's rules in order. An override replaces a fragment's
    words; an empty one leaves the fragment out."""
    chosen = sorted(fragments, key=lambda f: (f.section, f.order))
    keys = [f.key for f in chosen]
    twice = sorted({k for k in keys if keys.count(k) > 1})
    if twice:
        raise ValueError(f"two prompt fragments with the key {', '.join(twice)}")
    parts = [persona.rstrip("\n")]
    for section, title in SECTIONS:
        lines = [overrides.get(f.key, f.text) for f in chosen if f.section == section]
        lines = [line for line in lines if line]
        if lines:
            parts.append(title + "\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"
