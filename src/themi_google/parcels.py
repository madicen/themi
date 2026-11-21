"""PT3: the Parcels module (the Themi Package Tracking Plan).

Parcels themselves come from email triage (`Deliveries`, WL8 and PT2), which works without
this module. Turning it on adds the carriers' alert emails to what Themi reads (its setup
guide, `setup/parcels.md`: USPS Informed Delivery, UPS My Choice, FedEx Delivery Manager),
and, from PT4 on, asking the carriers themselves.
"""

from __future__ import annotations

from themi.modules import Module, ModuleContext
from themi_google.groups import EMAIL

NAME = "parcels"


class ParcelsModule(Module):
    """Parcels by tracking number, from shipping emails and the carriers' own alerts."""

    name = NAME
    title = "Parcels"
    group = EMAIL
    summary = (
        "Follows parcels coming to the family by tracking number, from shipping emails and "
        "the carriers' own alerts."
    )
    cost = "Free"
    requires = ("email_triage",)
    website = "Sign up for the carriers' alert emails (this page's guide)."

    def install(self, ctx: ModuleContext) -> None:
        pass  # PT4: the carriers' keys and Test; PT5: asking them on a schedule
