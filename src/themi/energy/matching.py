"""Who takes a task: the usual person, unless the other partner clearly has more room.

    cost(person)  = effort x 8 x their cost for this kind x recovery factor
    spare(person) = capacity now - cost(person)

The task goes to the default owner for its kind (family setting) unless the
partner's spare room, minus the cost of handing it over, still beats the
default owner's. The recovery factor makes draining work cost a little more
for someone who recovers slowly (half-life above 6 hours) and a little less
for a fast recoverer.

The reason is recorded in words; no numbers leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from themi import clock
from themi.accounts import AccountStore, Member
from themi.energy.model import SOURCE_INPUT, EnergyModel

POINTS_PER_EFFORT = 8.0
KIND_WORDS = {"text": "texting", "call": "calls", "physical": "hands-on jobs", "errand": "errands"}


@dataclass(frozen=True)
class Assignment:
    assignee: Member
    default_owner: Member
    reason: str

    @property
    def swapped(self) -> bool:
        return self.assignee.id != self.default_owner.id


def recovery_factor(recovery_hours: float) -> float:
    return max(0.75, min(1.5, 1 + (recovery_hours - 6) / 24))


def task_cost(member: Member, kind: str, effort: int) -> float:
    return (
        effort * POINTS_PER_EFFORT * member.kind_cost(kind) * recovery_factor(member.recovery_hours)
    )


def _tracked(member: Member) -> bool:
    return any(member.tracks(toggle) for toggle in SOURCE_INPUT.values())


class Matcher:
    def __init__(self, store: AccountStore, model: EnergyModel) -> None:
        self.store = store
        self.model = model

    def default_owner(self, kind: str, requester: Member) -> Member:
        family = self.store.get_family()
        owner_id = family.task_owners.get(kind) if family else None
        if owner_id is not None:
            try:
                return self.store.get_member(owner_id)
            except Exception:  # the owner was removed; fall back to the requester
                pass
        return requester

    def spare(self, member: Member, kind: str, effort: int, at: datetime | None = None) -> float:
        return self.model.capacity(member, at) - task_cost(member, kind, effort)

    def assign(
        self, kind: str, effort: int, requester: Member, at: datetime | None = None
    ) -> Assignment:
        now = at or clock.now()
        default = self.default_owner(kind, requester)
        others = [m for m in self.store.list_members() if m.id != default.id]
        usual = f"Usually {default.name}'s ({KIND_WORDS.get(kind, kind)})"
        if not others:
            return Assignment(default, default, f"{usual}.")
        if not _tracked(default):
            return Assignment(default, default, f"{usual}; no energy read to weigh it against.")
        family = self.store.get_family()
        handover = family.handover_cost if family else 10.0
        default_spare = self.spare(default, kind, effort, now)
        best, best_spare = None, default_spare + handover
        for other in others:
            if not _tracked(other):
                continue
            other_spare = self.spare(other, kind, effort, now)
            if other_spare > best_spare:
                best, best_spare = other, other_spare
        if best is None:
            return Assignment(default, default, f"{usual}.")
        return Assignment(
            best, default, f"{usual}, but {best.name} seems to have more room right now."
        )
