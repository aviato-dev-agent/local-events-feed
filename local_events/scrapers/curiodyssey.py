"""CuriOdyssey (San Mateo) — First Friday Night events.

Rules-based: First Friday of each month, 5–8pm. Sensory Sundays and other one-offs
would need HTML scraping, but this gives us the reliable monthly signal without
brittleness to their site design.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

from ..event import Event

log = logging.getLogger(__name__)

URL = "https://curiodyssey.org/exhibits-events/"
LOCATION = "CuriOdyssey, 1651 Coyote Point Dr, San Mateo, CA"
TZ = "America/Los_Angeles"


def fetch(city_tag: str = "SM", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    today = datetime.now().date()
    horizon_date = today + timedelta(days=lookahead_days)

    # Walk through months in the lookahead window, find the first Friday of each
    year, month = today.year, today.month
    while True:
        first = datetime(year, month, 1)
        # Monday = 0 ... Friday = 4
        offset = (4 - first.weekday()) % 7
        first_friday = first + timedelta(days=offset)
        friday_date = first_friday.date()

        if friday_date > horizon_date:
            break
        if friday_date >= today:
            start = datetime(friday_date.year, friday_date.month, friday_date.day, 17, 0)
            end = datetime(friday_date.year, friday_date.month, friday_date.day, 20, 0)
            events.append(
                Event(
                    source="curiodyssey",
                    source_id=f"first-friday-{friday_date.isoformat()}",
                    city_tag=city_tag,
                    title="CuriOdyssey First Friday Night",
                    start=start,
                    end=end,
                    location=LOCATION,
                    description=(
                        "Swing into the weekend with music, science, animals and fun! "
                        "First Friday Nights at CuriOdyssey, 5–8pm. Family-friendly. "
                        "Check curiodyssey.org for ticket prices and any theme details."
                    ),
                    ages="All ages / family",
                    registration=None,
                    url=URL,
                    tz=TZ,
                )
            )

        # Advance one month
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    log.info("curiodyssey: %d events after filter", len(events))
    return events
