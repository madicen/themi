"""PT3, PT4: the Parcels module (the Themi Package Tracking Plan).

Parcels themselves come from email triage (`Deliveries`, WL8 and PT2), which works without
this module. Turning it on adds:

- the carriers' alert emails, through its setup guide (`setup/parcels.md`: USPS Informed
  Delivery, UPS My Choice, FedEx Delivery Manager), PT3;
- asking UPS and USPS themselves, with a free developer app's keys for each (PT4), on a
  schedule (PT5). Without keys, or with "Ask the carriers" off, it asks no one.

Each carrier's requests are counted on the usage card (UC3): UPS publishes no limit for
its free Tracking API; USPS's new apps reportedly start at 60 an hour (a vendor's figure;
USPS shows the real one in the app's portal).
"""

from __future__ import annotations

from themi.connectors.carriers import Carrier, CarrierError, UpsClient, UspsClient
from themi.connectors.carriers.ups import UPS_URL
from themi.connectors.carriers.usps import USPS_URL
from themi.modules import Module, ModuleContext, ModuleSetup
from themi.usage import Limits, Meter
from themi_google.deliveries import Deliveries
from themi_google.google_settings import ParcelsSettings
from themi_google.groups import EMAIL
from themi_google.parcel_checks import EVERY, ParcelChecks

NAME = "parcels"
UPS_METER = Meter("ups.calls", "UPS tracking", "calls", group="Web", order=40)
USPS_METER = Meter(
    "usps.calls",
    "USPS tracking",
    "calls",
    group="Web",
    order=41,
    limits=Limits(
        per_day=60 * 24,
        resets="UTC",
        source="USPS's default for a new app, 60 an hour (reported; the app's portal has it)",
        checked="2026-11",
    ),
)
NAMES = {"ups": "UPS", "usps": "USPS"}


class ParcelsModule(Module):
    """Parcels by tracking number, from shipping emails, the carriers' own alerts and (with
    their keys) the carriers themselves."""

    name = NAME
    title = "Parcels"
    group = EMAIL
    summary = (
        "Follows parcels coming to the family by tracking number, from shipping emails and "
        "the carriers' own alerts, and asks UPS and USPS when it has their keys."
    )
    cost = "Free"
    requires = ("email_triage",)
    settings = ParcelsSettings
    website = "Sign up for the carriers' alert emails (this page's guide)."

    def __init__(
        self, carriers: dict[str, Carrier] | None = None, settings: ParcelsSettings | None = None
    ) -> None:
        self.carriers: dict[str, Carrier] = dict(carriers or {})
        self.parcel_settings = settings or ParcelsSettings()

    @classmethod
    def build(cls, setup: ModuleSetup) -> Module | None:
        s = setup.read(ParcelsSettings)
        return cls(carriers_from(s), s)

    async def check(self) -> str | None:
        """Test: a token from each carrier with keys. None when every one works."""
        if not self.carriers:
            return (
                "No carrier keys yet: add UPS's or USPS's to ask them "
                "(parcels from email work without)."
            )
        problems = []
        for name, carrier in self.carriers.items():
            try:
                await carrier.check()
            except CarrierError as exc:
                problems.append(f"{NAMES.get(name, name)}: {exc}")
        return "; ".join(problems) or None

    def install(self, ctx: ModuleContext) -> None:
        meters = {"ups": UPS_METER, "usps": USPS_METER}
        for name, carrier in self.carriers.items():
            if name in meters and hasattr(carrier, "tally"):
                carrier.tally = ctx.usage_meter(meters[name])  # type: ignore[attr-defined]
        checks = ctx.provide(ParcelChecks(ctx.get(Deliveries), self.carriers))
        if self.carriers and self.parcel_settings.ask_carriers:  # PT5: on a schedule
            ctx.periodic("parcels.check", EVERY, checks.run)


def carriers_from(s: ParcelsSettings) -> dict[str, Carrier]:
    """The carriers the settings have keys for."""
    carriers: dict[str, Carrier] = {}
    if s.ups_client_id and s.ups_client_secret is not None:
        carriers["ups"] = UpsClient(
            s.ups_client_id, s.ups_client_secret, base_url=s.ups_url or UPS_URL
        )
    if s.usps_consumer_key and s.usps_consumer_secret is not None:
        carriers["usps"] = UspsClient(
            s.usps_consumer_key, s.usps_consumer_secret, base_url=s.usps_url or USPS_URL
        )
    return carriers
