"""SL1/SL3/SL4: Themi's words and buttons as Slack sees them, with nothing sent anywhere.

- Text: Themi writes plain text, so only `&`, `<` and `>` are escaped for Slack's mrkdwn
  (anything else, like `*`, shows the way Slack shows it).
- Buttons: one `actions` block a row (rows as on Telegram), each button's `value` the
  callback token; a link button opens its page and calls nothing back.
- Emoji: Slack names reactions (`eyes`); Themi's code works with the emoji itself (👀).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from themi.channels.buttons import button_rows
from themi.channels.events import Button

SECTION_LIMIT = 3000  # characters of text in one section block
LABEL_LIMIT = 75  # characters of a button's label
FALLBACK_LIMIT = 4000  # the plain `text` shown in notifications


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unescape(text: str) -> str:
    """What someone wrote, as they wrote it (Slack escapes the same three)."""
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]*))?>")
_MENTION = re.compile(r"<[@#!]([^|>]+)(?:\|([^>]*))?>")


def plain(text: str) -> str:
    """A message's mrkdwn as words: links as their address (`mailto:` dropped), mentions as
    their label (or the bare id), then unescaped."""
    text = _LINK.sub(lambda m: m.group(1).removeprefix("mailto:"), text)
    text = _MENTION.sub(lambda m: m.group(2) or m.group(1), text)
    return unescape(text)


def sections(text: str) -> list[dict[str, Any]]:
    """The text as section blocks, split on line breaks where it's too long for one."""
    escaped = escape(text) or " "
    chunks: list[str] = []
    while len(escaped) > SECTION_LIMIT:
        cut = escaped.rfind("\n", 0, SECTION_LIMIT)
        if cut <= 0:
            cut = escaped.rfind(" ", 0, SECTION_LIMIT)
        if cut <= 0:
            cut = SECTION_LIMIT
        chunks.append(escaped[:cut])
        escaped = escaped[cut:].lstrip("\n")
    chunks.append(escaped)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in chunks if c]


def button_blocks(buttons: Sequence[Button], tokens: Sequence[str | None]) -> list[dict[str, Any]]:
    """The buttons as `actions` blocks, a row each. `tokens[i]` is button i's callback
    token, or None for a link button (`web_app`)."""
    if not buttons:
        return []
    blocks: list[dict[str, Any]] = []
    for row_number, row in enumerate(button_rows([b.label for b in buttons])):
        elements: list[dict[str, Any]] = []
        for i in row:
            button, token = buttons[i], tokens[i]
            element: dict[str, Any] = {
                "type": "button",
                "text": {"type": "plain_text", "text": button.label[:LABEL_LIMIT], "emoji": True},
                "action_id": f"themi-{i}",
            }
            if token is None:
                element["url"] = button.web_app
            else:
                element["value"] = token
            elements.append(element)
        blocks.append(
            {"type": "actions", "block_id": f"themi-row-{row_number}", "elements": elements}
        )
    return blocks


def message_blocks(
    text: str, buttons: Sequence[Button], tokens: Sequence[str | None]
) -> list[dict[str, Any]]:
    return [*sections(text), *button_blocks(buttons, tokens)]


def fallback(text: str) -> str:
    """The plain text Slack shows in notifications and where blocks can't be shown."""
    escaped = escape(text)
    return escaped if len(escaped) <= FALLBACK_LIMIT else escaped[: FALLBACK_LIMIT - 1] + "…"


# The reactions Themi's features look for (approvals, reactions, calibration, wrong replies)
# and the ones it sends (the sidecar's ✍, 👀), by Slack's names. Slack has more than one
# name for some; the first is the one sent.
EMOJI_NAMES: dict[str, tuple[str, ...]] = {
    "👍": ("+1", "thumbsup"),
    "👎": ("-1", "thumbsdown"),
    "✅": ("white_check_mark",),
    "✔️": ("heavy_check_mark",),
    "👌": ("ok_hand",),
    "💤": ("zzz",),
    "⏰": ("alarm_clock",),
    "❤️": ("heart",),
    "🙏": ("pray",),
    "😕": ("confused",),
    "😠": ("angry",),
    "😡": ("rage",),
    "😤": ("triumph",),
    "😣": ("persevere",),
    "🙄": ("face_with_rolling_eyes", "roll_eyes"),
    "✍": ("writing_hand",),
    "👀": ("eyes",),
    "🎉": ("tada",),
    "🔥": ("fire",),
    "😂": ("joy",),
    "🙂": ("slightly_smiling_face",),
    "😄": ("smile",),
    "🤔": ("thinking_face",),
    "👏": ("clap",),
    "💪": ("muscle",),
    "❌": ("x",),
    "⭐": ("star",),
}
_BY_NAME = {name: emoji for emoji, names in EMOJI_NAMES.items() for name in names}


def _bare(emoji: str) -> str:
    return emoji.replace("️", "")


_BY_BARE = {_bare(emoji): names[0] for emoji, names in EMOJI_NAMES.items()}


def emoji_name(emoji: str) -> str | None:
    """Slack's name for an emoji Themi sends, or None when it has none here."""
    return _BY_BARE.get(_bare(emoji))


def emoji_for(name: str) -> str:
    """The emoji for a reaction's name (skin tones dropped); `:name:` when it isn't one
    Themi knows, so it still reads as a reaction and matches nothing."""
    base = name.split("::", 1)[0]
    return _BY_NAME.get(base, f":{base}:")
