"""SL1/SL3/SL4: Themi's words, buttons and emoji as Slack sees them."""

from __future__ import annotations

from themi.channels import slack_blocks as sb
from themi.channels.events import Button
from themi.logs import redact


def test_only_slacks_three_characters_are_escaped() -> None:
    assert sb.escape("a & b <c> *d* _e_") == "a &amp; b &lt;c&gt; *d* _e_"
    assert sb.unescape(sb.escape("x < y & z > w")) == "x < y & z > w"


def test_long_text_is_split_into_sections_at_line_breaks() -> None:
    text = ("line " * 100 + "\n") * 10  # about 5000 characters
    blocks = sb.sections(text)
    assert len(blocks) == 2
    assert all(len(b["text"]["text"]) <= sb.SECTION_LIMIT for b in blocks)
    assert "".join(b["text"]["text"] for b in blocks).replace("\n", "") == text.replace("\n", "")


def test_buttons_are_rows_of_actions_and_a_link_opens_its_page() -> None:
    buttons = [Button("Yes", "k"), Button("No", "k"), Button("Later", "k"),
               Button("Open the page", "", web_app="https://themi.test/session")]  # fmt: skip
    blocks = sb.button_blocks(buttons, ["t1", "t2", "t3", None])
    assert [b["type"] for b in blocks] == ["actions", "actions"]
    first, second = (b["elements"] for b in blocks)
    assert [e["value"] for e in first] == ["t1", "t2"]  # a long label makes rows of two
    assert second[-1]["url"] == "https://themi.test/session" and "value" not in second[-1]
    assert sb.button_blocks([], []) == []


def test_a_long_label_is_cut_to_slacks_limit() -> None:
    [block] = sb.button_blocks([Button("x" * 100, "k")], ["t"])
    assert len(block["elements"][0]["text"]["text"]) == sb.LABEL_LIMIT


def test_emoji_go_by_slacks_names_both_ways() -> None:
    assert sb.emoji_name("👀") == "eyes"
    assert sb.emoji_name("✍") == "writing_hand"
    assert sb.emoji_name("❤️") == sb.emoji_name("❤") == "heart"
    assert sb.emoji_for("+1") == sb.emoji_for("thumbsup") == "👍"
    assert sb.emoji_for("+1::skin-tone-3") == "👍"
    assert sb.emoji_for("zzz") == "💤"
    assert sb.emoji_for("partyparrot") == ":partyparrot:"
    assert sb.emoji_name("🦜") is None


def test_slack_tokens_never_reach_the_logs() -> None:
    line = "using xoxb-1234-5678-abcdEFGH and xapp-1-A0-123-abc and xoxp-99-88-77-xyz"
    assert "xoxb-1234" not in redact(line) and "xapp-1" not in redact(line)
    assert "xoxp-99" not in redact(line)
