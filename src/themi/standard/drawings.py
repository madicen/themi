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
from typing import TYPE_CHECKING, Any

from themi.drawing.render import Renderer
from themi.drawing.svg import write_svg
from themi.modules import Module

if TYPE_CHECKING:
    from themi.core.services import Services
    from themi.modules.context import ModuleContext

NAME = "drawings"


class Drawings:
    """The renderer, for whichever feature draws."""

    def __init__(self, services: Services, renderer: Renderer | None = None) -> None:
        self.services = services
        self.renderer = renderer or Renderer()

    def install(self) -> None:
        pass

    def svg(self, template: str, extra: Sequence[Path] = (), **values: Any) -> str:
        return write_svg(template, extra, **values)

    async def png(self, svg: str, width: int | None = None) -> bytes | None:
        return await self.renderer.png(svg, width)


class DrawingsModule(Module):
    """DC1: pictures drawn from Themi's own data, as SVG and PNG."""

    name = NAME
    title = "Drawings"
    summary = "A picture of the day with the morning message, drawn from the calendar and weather."
    cost = "Free, no account"

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
        ctx.provide(Drawings(ctx.services, self.renderer)).install()
