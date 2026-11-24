"""F61c (bug #267): a backend's model the provider says isn't found. The router skips it
from then on; this says so, once, to whoever owns the backend and to the admins, with where
to pick another."""

from __future__ import annotations

from typing import TYPE_CHECKING

from themi.channels.outbox import Priority

if TYPE_CHECKING:
    from themi.ai.settings import ResolvedEntry
    from themi.core.services import Services

GONE_TEXT = (
    "{whose} {label} model{model} isn't there any more (the provider says it isn't found), "
    "so Themi skips it. Another model can be chosen on the website: {link}"
)


class ModelGone:
    def __init__(self, services: Services) -> None:
        self.services = services

    async def __call__(self, member_id: int, entry: ResolvedEntry) -> None:
        store = self.services.store
        owner = store.get_member(self.services.ai_settings.get_backend(entry.backend_id).member_id)
        model = entry.config.model or ""
        link = f"{self.services.site_url}/ai" if self.services.site_url else "the AI page"
        told = [owner, *(m for m in store.list_members() if m.is_admin and m.id != owner.id)]
        for member in told:
            whose = "Your" if member.id == owner.id else f"{owner.name}'s"
            await self.services.outbox.send(
                member,
                GONE_TEXT.format(
                    whose=whose, label=entry.label, model=f" {model}" if model else "", link=link
                ),
                priority=Priority.NORMAL,
                kind="system",
                dedupe_key=f"ai-model-gone:{entry.backend_id}:{model}",
            )
