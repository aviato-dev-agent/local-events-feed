"""Hidden Villa (Los Altos Hills) — Star Party program dates.

Hidden Villa runs an Arlo-backed program catalog rather than a REST API.
The Star Party page lists all upcoming session dates as plain text rows
like "Sep 11 7:30pm - 9:30pm". We parse those directly.

Farm tour events aren't covered here — bayareakidfun already delivers those
with venue address intact.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from ..event import Event

log = logging.getLogger(__name__)

STAR_PARTY_URL = "https://www.hiddenvilla.org/programs/catalog/555-star-party/region-HV/"
LOCATION = "Hidden Villa, 26870 Moody Road, Los Altos Hills, CA 94022"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Sep 11 7:30pm - 9:30pm" or "Oct 04 7:30pm - 9:30pm"
_DATE_RE = re.compile(
    r"([A-Za-z]{3,4})\s+(\d{1,2})\s+"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"\s*(?:-|–|—|to)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
    re.IGNORECASE,
)


def fetch(city_tag: str = "LAH", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    horizon = datetime.now() + timedelta(days=lookahead_days)
    today = datetime.now()

    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
            r = client.get(STAR_PARTY_URL)
            r.raise_for_status()
            html_text = r.text
    except Exception as exc:
        log.warning("hiddenvilla: fetch failed: %s", exc)
        return events

    text = re.sub(r"\s+", " ", BeautifulSoup(html_text, "html.parser").get_text(" ", strip=True))

    for m in _DATE_RE.finditer(text):
        month_key = m.group(1).lower()[:3]
        if month_key == "sep" and m.group(1).lower() == "sept":
            month_key = "sept"
        month = _MONTHS.get(month_key)
        if not month:
            continue

        day = int(m.group(2))
        sh = _to24(int(m.group(3)), m.group(5))
        sm = int(m.group(4) or 0)
        eh = _to24(int(m.group(6)), m.group(8))
        em = int(m.group(7) or 0)

        year = _pick_year(month, day, today)
        try:
            start = datetime(year, month, day, sh, sm)
            end = datetime(year, month, day, eh, em)
        except ValueError:
            continue
        if end <= start:
            end += timedelta(days=1)

        if start < today - timedelta(hours=6) or start > horizon:
            continue

        events.append(
            Event(
                source="hiddenvilla",
                source_id=f"star-party-{start.strftime('%Y%m%d')}",
                city_tag=city_tag,
                title="Star Party at Hidden Villa",
                start=start,
                end=end,
                location=LOCATION,
                description=(
                    "Hidden Villa's Star Party program — view planets and deep-sky "
                    "objects through telescopes on the farm.\n\n"
                    f"Source: {STAR_PARTY_URL}"
                ),
                ages="All ages",
                registration=True,
                url=STAR_PARTY_URL,
                tz=TZ,
            )
        )

    log.info("hiddenvilla: %d events after filter", len(events))
    return events


def _to24(hour: int, ampm: str) -> int:
    ampm = ampm.lower()
    if ampm.startswith("p") and hour != 12:
        return hour + 12
    if ampm.startswith("a") and hour == 12:
        return 0
    return hour


def _pick_year(month: int, day: int, ref: datetime) -> int:
    candidate = datetime(ref.year, month, day) if _valid(ref.year, month, day) else None
    if candidate and candidate >= ref - timedelta(days=30):
        return ref.year
    return ref.year + 1


def _valid(y: int, m: int, d: int) -> bool:
    try:
        datetime(y, m, d)
        return True
    except ValueError:
        return False
