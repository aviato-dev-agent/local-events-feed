"""Static/recurring volunteer events with known cadences.

Emits deterministic events for sources that don't have a scrapable calendar
but publish a fixed schedule (e.g. "2nd & 4th Saturday, 10a–3p" or "3rd
Saturday of September"). Expanded across the lookahead window and routed
to the volunteer feed via is_volunteer_source=True in config.yaml.

Sources included:
  - Silicon Valley Bicycle Exchange (Palo Alto) — 2nd + 4th Saturdays
  - Coastal Cleanup Day (statewide, celebrated locally) — 3rd Saturday of September
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from ..event import Event

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"


def fetch(city_tag: str = "PA", lookahead_days: int = 90) -> list[Event]:
    now = datetime.now()
    horizon = (now + timedelta(days=lookahead_days)).date()
    events: list[Event] = []
    events.extend(_bike_exchange(now.date(), horizon))
    events.extend(_coastal_cleanup_day(now.date(), horizon))
    log.info("static_recurring: %d events after filter", len(events))
    return events


# ---------- SV Bicycle Exchange ----------

_BIKEX_LOCATION = "Silicon Valley Bicycle Exchange, 3961 E Bayshore Rd, Palo Alto, CA 94303"
_BIKEX_URL = "https://bikex.org/"
_BIKEX_DESC = (
    "Open workshop day at Silicon Valley Bicycle Exchange. Volunteers wipe "
    "down donated bikes, fix flats, and adjust brakes/derailleurs under "
    "mentor guidance. Refurbished bikes go to low-income families and kids.\n\n"
    "Kids welcome with a parent — bike-shop tools involved, use judgment. "
    "No prior mechanical experience needed. Bikex mission: reduce "
    "transportation barriers by putting affordable bikes in the hands of "
    "people who need them."
)


def _bike_exchange(start: date, end: date) -> list[Event]:
    events: list[Event] = []
    for d in _every_nth_weekday(start, end, weekday=5, nths=(2, 4)):
        s = datetime.combine(d, time(10, 0))
        e = datetime.combine(d, time(15, 0))
        events.append(Event(
            source="static_recurring",
            source_id=f"bikex-{d.isoformat()}",
            city_tag="PA",
            title="SV Bicycle Exchange Open Workshop Day",
            start=s,
            end=e,
            location=_BIKEX_LOCATION,
            description=_BIKEX_DESC,
            ages="All ages (kids with parent)",
            registration=False,
            url=_BIKEX_URL,
            tz=TZ,
        ))
    return events


# ---------- Coastal Cleanup Day ----------

_CCD_URL = "https://www.smchealth.org/ccd"
_CCD_DESC = (
    "Annual California Coastal Cleanup Day — the state's largest volunteer "
    "event. Cleanup sites all over San Mateo County beaches, creeks, and "
    "parks; check smchealth.org/ccd for the sign-up map closer to the date.\n\n"
    "All ages welcome with a parent. Gloves, bags, and pickers provided at "
    "most sites."
)


def _coastal_cleanup_day(start: date, end: date) -> list[Event]:
    events: list[Event] = []
    year = start.year
    while True:
        d = _nth_weekday_of_month(year, 9, weekday=5, nth=3)
        if d > end:
            break
        if d >= start:
            s = datetime.combine(d, time(9, 0))
            e = datetime.combine(d, time(12, 0))
            events.append(Event(
                source="static_recurring",
                source_id=f"coastal-cleanup-day-{d.isoformat()}",
                city_tag="SM",
                title="California Coastal Cleanup Day (countywide)",
                start=s,
                end=e,
                location="San Mateo County (multiple sites — see smchealth.org/ccd)",
                description=_CCD_DESC,
                ages="All ages (with parent)",
                registration=True,
                url=_CCD_URL,
                tz=TZ,
            ))
        year += 1
    return events


# ---------- helpers ----------

def _every_nth_weekday(start: date, end: date, weekday: int, nths: tuple[int, ...]) -> list[date]:
    """Return every date in [start, end] that is the Nth given weekday of its month,
    where N ∈ nths (1=first, 2=second, …). weekday: Mon=0..Sun=6."""
    out: list[date] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        for nth in nths:
            d = _nth_weekday_of_month(y, m, weekday, nth)
            if d and start <= d <= end:
                out.append(d)
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return sorted(out)


def _nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> date:
    """Return the date of the nth given weekday of month, or a sentinel very-far date if it doesn't exist."""
    d = date(year, month, 1)
    # advance to first target weekday
    offset = (weekday - d.weekday()) % 7
    first = d + timedelta(days=offset)
    candidate = first + timedelta(weeks=nth - 1)
    if candidate.month != month:
        return date(9999, 12, 31)
    return candidate
