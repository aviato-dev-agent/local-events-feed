"""SMCAS Crestview Park star party schedule.

The San Mateo County Astronomical Society publishes their full annual schedule
as a plain-text block on their Crestview page. We parse it directly.

Setup begins at sunset; observing starts 1 hour after sunset. We use sunset as
the event start and add 3 hours (typical duration).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx

from ..event import Event

log = logging.getLogger(__name__)

URL = "https://smcas.net/events/star-parties/crestview-park/"
LOCATION = "Crestview Park, 1000 Crestview Dr, San Carlos, CA"
TZ = "America/Los_Angeles"

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def fetch(city_tag: str = "SC", lookahead_days: int = 90) -> list[Event]:
    r = httpx.get(
        URL,
        headers={"User-Agent": "local-events-sync (personal, timmermerican@gmail.com)"},
        timeout=30,
    )
    r.raise_for_status()
    text = r.text
    events: list[Event] = []
    horizon = datetime.now() + timedelta(days=lookahead_days)

    # Each line format: "2026 Aug 8  - 8:09 PM" optionally "(Observe the Moon Night)"
    pattern = re.compile(
        r"(\d{4})\s+([A-Z][a-z]{2})\s+(\d{1,2})\s*-\s*(\d{1,2}):(\d{2})\s*(AM|PM)"
        r"\s*(\([^)]+\))?"
    )
    for m in pattern.finditer(text):
        year = int(m.group(1))
        month = MONTHS.get(m.group(2))
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        if m.group(6) == "PM" and hour != 12:
            hour += 12
        if m.group(6) == "AM" and hour == 12:
            hour = 0
        if not month:
            continue

        try:
            start = datetime(year, month, day, hour, minute)
        except ValueError:
            continue
        if start > horizon:
            continue
        if start < datetime.now() - timedelta(hours=6):
            continue

        annotation = (m.group(7) or "").strip("()")
        title = "SMCAS Crestview Star Party"
        if annotation:
            title = f"{title} — {annotation}"

        description = (
            "SMCAS hosts a free public star party at Crestview Park in San Carlos. "
            "All ages welcome. Members set up telescopes for public viewing of "
            "planets, nebulae, star clusters and galaxies. "
            f"Setup begins at sunset ({hour:02d}:{minute:02d}); observing starts "
            "one hour after sunset. Free.\n\n"
            "Cancels in rain, clouds, fog, or high wind — no official cancellation "
            "notice is issued."
        )
        if annotation:
            description = f"{annotation}. " + description

        # 3-hour block: sunset -> ~3h after
        end = start + timedelta(hours=3)

        events.append(
            Event(
                source="smcas",
                source_id=f"crestview-{year}{month:02d}{day:02d}",
                city_tag=city_tag,
                title=title,
                start=start,
                end=end,
                location=LOCATION,
                description=description,
                ages="All ages / family",
                registration=False,
                url=URL,
                tz=TZ,
            )
        )

    log.info("smcas: %d events after filter", len(events))
    return events
