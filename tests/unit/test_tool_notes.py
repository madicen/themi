"""Bug #110: each tool call's arguments and result are kept with the reply, redacted and cut
short."""

from __future__ import annotations

from themi.core.timing import KEPT_CHARS, ToolNote


def test_a_tool_note_is_redacted_and_cut_short() -> None:
    note = ToolNote()
    note.said({"text": "sign in at https://themi.example/login/abc123def456ghi789jkl"}, "x" * 2000)
    assert note.arguments is not None and "abc123def456ghi789jkl" not in note.arguments
    assert note.result is not None and len(note.result) == KEPT_CHARS
    assert note.result.endswith("…")


def test_a_short_result_is_kept_whole() -> None:
    note = ToolNote()
    note.said({"task_id": 3}, "Task 3 is done.")
    assert (note.arguments, note.result) == ('{"task_id": 3}', "Task 3 is done.")
