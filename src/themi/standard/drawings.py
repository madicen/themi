"""Pictures drawn by code (DC1-DC11; the Themi Day Card Plan).

The `drawings` module puts the renderer (`themi.drawing`) on `keys.drawings`, for the
pictures that use it: the day card with the morning message, and the others on request.
Named `drawings` because `pictures` is already the capability of looking at pictures
people send.

Nothing here asks a model or the network: a drawing is Themi's own data, drawn.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import field_validator

from themi.accounts.preferences import Preferences
from themi.core import groups, keys
from themi.core.tools import ToolContext, ToolFailed, tool
from themi.drawing.render import Renderer
from themi.drawing.svg import write_svg
from themi.modules import Module

if TYPE_CHECKING:
    from themi.accounts import Member
    from themi.core.services import Services
    from themi.modules.context import ModuleContext

NAME = "drawings"
DAY_CARD = "day_card"  # the morning message's picture (DC5), as the outbox knows it
COUNTS = ("dots", "numbers", "hide")
THEMES = ("light", "dark")


class DrawingsPreferences(Preferences):
    """DC3: each person's pictures. On for everyone (Michael, 2026-11-13)."""

    module: ClassVar[str] = NAME
    picture_morning: bool = True  # the day card with the morning message
    picture_counts: str = "dots"  # what's waiting: dots, numbers, or hidden
    picture_theme: str = "light"

    @classmethod
    def on_form(cls, services: Any, member: Any) -> set[str] | None:
        """Shown in the good-morning message's row: not there without it."""
        return None if services.maybe(keys.day_summary) is not None else set()

    @field_validator("picture_counts")
    @classmethod
    def _counts(cls, value: str) -> str:
        if value not in COUNTS:
            raise ValueError("what's waiting shows as dots, numbers, or not at all")
        return value

    @field_validator("picture_theme")
    @classmethod
    def _theme(cls, value: str) -> str:
        if value not in THEMES:
            raise ValueError("a picture is light or dark")
        return value


class Drawings:
    """The renderer, for whichever feature draws."""

    def __init__(self, services: Services, renderer: Renderer | None = None) -> None:
        from themi.standard.day_card import DayCard  # it reads this module's preferences
        from themi.standard.weather_card import WeatherCard
        from themi.standard.week_card import WeekCard

        self.services = services
        self.renderer = renderer or Renderer()
        self.day_card = DayCard(services)  # DC3
        self.week_card = WeekCard(services, self.day_card)  # DC6
        self.weather_card = WeatherCard(services)  # DC8

    def install(self) -> None:
        pass

    async def morning_picture(self, member: Member, row: dict[str, Any]) -> bytes | None:
        """The outbox's `day_card` (DC5): today's card as the morning message goes, unless
        they turned the picture off while it waited."""
        if not self.services.store.preferences(member.id, DrawingsPreferences).picture_morning:
            return None
        return await self.day_card.png(member, self.day_card.today(member))

    def today_panel(self, member: Member) -> dict[str, Any]:
        """DC7: today's card on their own dashboard, as SVG in the page (no PNG). Drawn
        for the signed-in member only; the dashboard is theirs."""
        from markupsafe import Markup

        svg = self.day_card.svg(member, self.day_card.today(member))
        # The template escaped every word from data; the SVG is Themi's own markup.
        return {"today_card": Markup(svg)}

    async def weather_command(self, member: Member, text: str) -> None:
        """`/weather` (DC8)."""
        await self.weather_card.send(member)

    async def week_command(self, member: Member, text: str) -> None:
        """`/week` (DC6)."""
        await self.week_card.send(member)

    def svg(self, template: str, extra: Sequence[Path] = (), **values: Any) -> str:
        return write_svg(template, extra, **values)

    async def png(self, svg: str, width: int | None = None) -> bytes | None:
        return await self.renderer.png(svg, width)


@tool(
    "show_week",
    "Sends them a picture of their week ahead: the next seven days' events at their times, "
    "and each day's weather. For 'show me my week', 'what does my week look like?'. It's "
    "sent to them as it is: don't describe it; a short line at most. Never mention energy.",
    {},
)
async def show_week(ctx: ToolContext, args: dict[str, Any]) -> str:
    drawings = ctx.services.maybe(keys.drawings)
    if drawings is None:
        raise ToolFailed("Pictures aren't set up.")
    pictured = await drawings.week_card.send(ctx.member)
    ctx.answered.append("show_week")
    return "Sent their week as a picture." if pictured else "Sent their week, in words."


@tool(
    "show_weather",
    "Sends them the weather for today and tomorrow, as a picture: hour by hour, with "
    "anything worth knowing (rain, a storm warning). For 'what's the weather?', 'will it "
    "rain tomorrow?'. It's sent as it is: don't repeat it, and never give advice about it.",
    {},
)
async def show_weather(ctx: ToolContext, args: dict[str, Any]) -> str:
    drawings = ctx.services.maybe(keys.drawings)
    if drawings is None:
        raise ToolFailed("Pictures aren't set up.")
    pictured = await drawings.weather_card.send(ctx.member)
    ctx.answered.append("show_weather")
    return "Sent the weather as a picture." if pictured else "Sent the weather, in words."


class DrawingsModule(Module):
    """DC1: pictures drawn from Themi's own data, as SVG and PNG."""

    name = NAME
    title = "Drawings"
    summary = "A picture of the day with the morning message, drawn from the calendar and weather."
    cost = "Free, no account"
    preferences = DrawingsPreferences
    # show_week (DC6), show_weather (DC8), show_day (F42g); show_step_plan (DC11); the
    # tasks and routines pictures (F42g) are listed beside show_routines, in groups.py
    tool_groups = (groups.CALENDAR, groups.SCHEDULES)

    def __init__(self, renderer: Renderer | None = None) -> None:
        self.renderer = renderer

    async def check(self) -> str | None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
            '<rect width="8" height="8"/></svg>'
        )
        if await Renderer().png(svg) is None:
            return "Pictures can't be drawn here: the resvg library isn't working."
        return None

    def install(self, ctx: ModuleContext) -> None:
        drawings = ctx.provide(Drawings(ctx.services, self.renderer))
        drawings.install()
        ctx.services.outbox.pictures[DAY_CARD] = drawings.morning_picture  # DC5
        ctx.dashboard_panel("dashboard/today.html", 10, values=drawings.today_panel)  # DC7
        ctx.tool(show_week)  # DC6
        ctx.tool(show_weather)  # DC8
        from themi.standard.plan_card import show_step_plan

        ctx.tool(show_step_plan)  # DC11
        from themi.standard.list_card import show_day, show_routines_picture, show_tasks_picture

        ctx.tool(show_tasks_picture)  # F42g
        ctx.tool(show_routines_picture)
        ctx.tool(show_day)
        ctx.command("/weather", drawings.weather_command, "The weather today and tomorrow")
        ctx.command("/week", drawings.week_command, "Your week ahead, as a picture")
