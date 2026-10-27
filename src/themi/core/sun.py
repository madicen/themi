"""When the sun sets at home (F9b), worked out offline.

The standard sunrise equation (as on Wikipedia's "Sunrise equation"), good to about a
minute, which is plenty for "an hour before sunset". No library and no network: the home's
coordinates come from the Family page (K4's `family_home`).
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, tzinfo

J2000 = 2451545.0
UNIX_EPOCH_JD = 2440587.5
TILT = math.radians(23.4397)
HORIZON = math.radians(-0.833)  # the sun's disc, and the air bending its light


def _jd(day: date) -> float:
    """The Julian date at midnight UTC that starts `day`."""
    return day.toordinal() + 1721424.5


def sunset(day: date, lat: float, lon: float, tz: tzinfo) -> datetime | None:
    """The sun goes down on `day` at this place (east longitude positive), in `tz`; None
    when it doesn't set at all (polar summer or winter)."""
    n = math.ceil(_jd(day) - J2000 + 0.0008)
    mean = n - lon / 360.0  # mean solar time
    anomaly = math.radians((357.5291 + 0.98560028 * mean) % 360)
    centre = (
        1.9148 * math.sin(anomaly) + 0.0200 * math.sin(2 * anomaly) + 0.0003 * math.sin(3 * anomaly)
    )
    longitude = math.radians((math.degrees(anomaly) + centre + 180 + 102.9372) % 360)
    transit = J2000 + mean + 0.0053 * math.sin(anomaly) - 0.0069 * math.sin(2 * longitude)
    declination = math.asin(math.sin(longitude) * math.sin(TILT))
    phi = math.radians(lat)
    cos_hour = (math.sin(HORIZON) - math.sin(phi) * math.sin(declination)) / (
        math.cos(phi) * math.cos(declination)
    )
    if not -1 <= cos_hour <= 1:
        return None
    set_jd = transit + math.degrees(math.acos(cos_hour)) / 360.0
    moment = datetime.fromtimestamp((set_jd - UNIX_EPOCH_JD) * 86400, tz=UTC)
    return moment.astimezone(tz)
