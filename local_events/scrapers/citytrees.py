"""CityTrees Redwood City — tree-planting volunteer events.

Planting events are held on Saturdays, October–April. Between seasons the
volunteer page has no dated events; the scraper returns an empty list.
Once the org publishes dates for the new season (typically September), they
appear automatically on the next daily run.

Kids 14+ welcome. Ages 14–16 must be accompanied by a guardian; ages 16–18
require a signed guardian waiver. Youth-age rules are baked into every event
description since they're load-bearing information for us.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from ..event import Event

log = logging.getLogger(__name__)

INDEX_URL = "https://citytrees.org/volunteer/"
LOCATION = "Redwood City (venue varies by event)"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_YOUTH_RULES = (
    "Ages 14+ welcome. Ages 14–16 must be accompanied by a guardian for the "
    "entire event. Ages 16–18 require a signed guardian waiver. Bring "
    "closed-toe shoes; safety vest provided by CityTrees."
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "October 12, 2026" or "Oct 12, 2026" or "October 12 2026"
_DATE_RE = re.compile(
    r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
    re.IGNORECASE,
)

# Times, optional. Planting events typically 8am–noon.
_TIME_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)"
    r"(?:\s*(?:-|–|—|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|noon))?",
    re.IGNORECASE,
)


def fetch(city_tag: str = "RWC", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    today = datetime.now()
    horizon = today + timedelta(days=lookahead_days)

    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
            r = client.get(INDEX_URL)
            r.raise_for_status()
            html_text = r.text
    except Exception as exc:
        log.warning("citytrees: fetch failed: %s", exc)
        return events

    soup = BeautifulSoup(html_text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    for m in _DATE_RE.finditer(text):
        month = _MONTHS.get(m.group(1).lower())
        if not month:
            continue
        try:
            day = int(m.group(2))
            year = int(m.group(3))
            start = datetime(year, month, day, 8, 0)  # default 8am
        except ValueError:
            continue
        if start < today - timedelta(hours=6) or start > horizon:
            continue

        # Try to extract a real time from the 200 chars surrounding the date
        window = text[max(0, m.start() - 100):m.end() + 200]
        tm = _TIME_RE.search(window)
        end = start + timedelta(hours=4)
        if tm:
            sh = _to24(int(tm.group(1)), tm.group(3))
            sm_min = int(tm.group(2) or 0)
            start = start.replace(hour=sh, minute=sm_min)
            if tm.group(4):
                eh_raw = tm.group(6).lower()
                if "noon" in eh_raw:
                    end = start.replace(hour=12, minute=0)
                else:
                    eh = _to24(int(tm.group(4)), tm.group(6))
                    em = int(tm.group(5) or 0)
                    end = start.replace(hour=eh, minute=em)
                if end <= start:
                    end = start + timedelta(hours=4)

        events.append(
            Event(
                source="citytrees",
                source_id=f"planting-{start.strftime('%Y%m%d')}",
                city_tag=city_tag,
                title="CityTrees Planting Event",
                start=start,
                end=end,
                location=LOCATION,
                description=(
                    "CityTrees Redwood City volunteer tree planting.\n\n"
                    f"{_YOUTH_RULES}\n\n"
                    f"Source: {INDEX_URL}"
                ),
                ages="14+ (with guardian/waiver)",
                registration=True,
                url=INDEX_URL,
                tz=TZ,
            )
        )

    log.info("citytrees: %d events after filter", len(events))
    return events


def _to24(hour: int, ampm: str) -> int:
    ampm = ampm.lower().replace(".", "")
    if ampm.startswith("p") and hour != 12:
        return hour + 12
    if ampm.startswith("a") and hour == 12:
        return 0
    return hour
