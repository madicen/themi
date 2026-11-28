"""F65c (Michael's bug #283, a photo of the Together column: "It says there are 2 more, but
that's just a lie"): to-dos just ticked, still struck through, that don't fit go into "✓ N
done", and "+N more" counts only open ones. The real page at the frame's 1080 x 1920 in a
headless Chrome, fitted by wall-fit.js. Skipped where Chrome isn't installed."""

from __future__ import annotations

import json

import pytest

from tests.integration.test_session_page_browser import CHROME, page_in_chrome
from tests.integration.test_wall_fold import ticked
from tests.integration.test_wall_screen import screen, task, wall
from tests.integration.test_wall_top_browser import the_wall
from tests.scenarios.harness import Scenario
from themi import clock

__all__ = ["wall"]  # the fixture
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome or Chromium")


async def test_bug_283_struck_through_todos_cut_are_done_not_more(wall: Scenario) -> None:
    open_ones = [
        await task(wall, "Erin", f"Family to-do number {n} with a longer name", both="shared")
        for n in range(16)
    ]
    for t in open_ones[:4]:
        await ticked(wall, f"task-{t.id}", by=str(wall.member("Erin").id))  # just done
    page = await screen(wall)
    clock.unfreeze()
    async with page_in_chrome(wall, wall.member("Erin"), "body", width=1080, height=1920) as tab:
        await the_wall(tab, page, date="Sunday, May 3")
        got = json.loads(
            await tab.value(
                "(() => { const c = document.querySelector('#col-together');"
                "const shown = [...c.querySelectorAll('.wall-entry:not(.wall-cut)')];"
                "const cut = [...c.querySelectorAll('.wall-entry.wall-cut')];"
                "const more = [...c.querySelectorAll('.wall-more:not([hidden])')]"
                ".map(b => b.textContent);"
                "const fold = [...c.querySelectorAll('.wall-fold:not([hidden])')]"
                ".map(p => p.textContent.trim());"
                "return JSON.stringify({openCut: cut.filter(e => !e.querySelector('.done')).length,"
                "doneCut: cut.filter(e => e.querySelector('.done')).length,"
                "shown: shown.length, more, fold}); })()"
            )
        )
    assert got["doneCut"] > 0, got
    says_more = sum(int(m.strip("+ more")) for m in got["more"])
    assert says_more == got["openCut"]
    assert any(f.endswith(f"{got['doneCut']} done") for f in got["fold"])
