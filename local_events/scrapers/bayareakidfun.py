"""bayareakidfun.com — Bay Area family events aggregator.

Curated monthly listings. We scrape the current + next-month pages and filter
to peninsula cities within our target radius. Times aren't listed in the
aggregator — we default to 10am with 1-hour duration and note this in the
description.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Iterable

import httpx

from ..event import Event
from .sanmateopl import _is_under_six

log = logging.getLogger(__name__)

URLS = [
    "https://www.bayareakidfun.com/family-friendly-events-in-the-bay-area/",
    "https://www.bayareakidfun.com/more-family-events-bay-area/",
]
TZ = "America/Los_Angeles"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Peninsula cities we keep, mapped to city tag
CITY_MAP = {
    "redwood city": "RWC",
    "san mateo": "SM",
    "belmont": "B",
    "san carlos": "SC",
    "menlo park": "MP",
    "palo alto": "PA",
    "atherton": "ATH",
    "los altos": "LA",
    "los altos hills": "LAH",
    "mountain view": "MV",
    "foster city": "FC",
    "woodside": "WS",
    "portola valley": "PV",
    "half moon bay": "HMB",
    "burlingame": "BUR",
    "millbrae": "MB",
    "east palo alto": "EPA",
    "hillsborough": "H",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Match: <a href="URL" ...>Event Name</a> optional-(Free) – City, DateText<br
EVENT_RE = re.compile(
    r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
    r'\s*(?:\(([^)]+)\)\s*)?'
    r'[–-]\s*'
    r'([A-Z][A-Za-z .]+?),\s*'
    r"([A-Za-z0-9 ,–\-\.]+?)"
    r'(?=<br|</p|<a|$)',
    re.IGNORECASE,
)


def fetch(lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    horizon = datetime.now() + timedelta(days=lookahead_days)
    today = datetime.now()

    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for url in URLS:
            try:
                r = client.get(url)
                r.raise_for_status()
                html = r.text
            except httpx.HTTPError as exc:
                log.warning("bayareakidfun: fetch failed for %s: %s", url, exc)
                continue

            for match in EVENT_RE.finditer(html):
                ev_url = match.group(1).strip()
                name = _clean_text(match.group(2))
                free = match.group(3)  # "Free", "$5", or None
                city_raw = _clean_text(match.group(4)).strip(" .-–")
                date_text = _clean_text(match.group(5))

                city_key = city_raw.lower()
                city_tag = CITY_MAP.get(city_key)
                if not city_tag:
                    continue

                if _is_under_six(name, date_text, ""):
                    continue

                for start in _parse_dates(date_text, ref=today):
                    if start > horizon or start < today - timedelta(hours=6):
                        continue
                    end = start + timedelta(hours=1)
                    events.append(
                        Event(
                            source="bayareakidfun",
                            source_id=_make_id(ev_url, start),
                            city_tag=city_tag,
                            title=name,
                            start=start,
                            end=end,
                            location=city_raw,
                            description=_format_description(name, city_raw, date_text, free, ev_url),
                            ages="Family-friendly (per bayareakidfun.com curation)",
                            registration=None,
                            url=ev_url,
                            tz=TZ,
                        )
                    )

    # Dedupe by (url, start) since some events could appear on both monthly pages
    seen: set[tuple] = set()
    unique: list[Event] = []
    for e in events:
        key = (e.url, e.start)
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)

    log.info("bayareakidfun: %d events after filter", len(unique))
    return unique


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _make_id(url: str, dt: datetime) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", url.rstrip("/").split("/")[-1] or url)[:60]
    return f"{slug}-{dt.strftime('%Y%m%d')}"


def _format_description(name: str, city: str, date_text: str, free, url: str) -> str:
    lines = [
        f"{name} — {city}",
        f"Date listing: {date_text}",
    ]
    if free:
        lines.append(f"Cost: {free}")
    lines.append("Time not listed on aggregator — placeholder shown as 10am/1h block.")
    lines.append("Check source page for the actual time and details.")
    lines.append("")
    lines.append(f"Source: {url}")
    lines.append("Aggregator: bayareakidfun.com")
    return "\n".join(lines)


def _parse_dates(date_text: str, ref: datetime) -> list[datetime]:
    """Parse the date field from an event line.

    Handles: "July 3", "July 1-5", "July 3, 4", "July 24-August 19",
    "July 3, 4, 5". Emits one datetime per calendar day mentioned, but for
    a multi-day range we emit only the first day to avoid calendar clutter.
    Times default to 10:00 local.
    """
    text = date_text.strip().rstrip(".").rstrip(",")
    if not text:
        return []

    # First, split on ranges: if there's a hyphen/en-dash between two dates,
    # only take the first side (start date).
    # Handle month name at start
    m = re.match(r"([A-Za-z]+)\s+([\d,\s\-–]+)", text)
    if not m:
        return []

    month_name = m.group(1).lower()
    if month_name not in MONTHS:
        return []
    month = MONTHS[month_name]
    rest = m.group(2)

    # If rest contains " - August ..." or " – August ...", we handled month name
    # only for the START date. Just take numeric days from the "rest" until we
    # hit a non-digit chunk that's a new month.
    days: list[int] = []

    # Split on "-" or "–" — first chunk is start range or standalone
    left = re.split(r"\s*[-–]\s*", rest, maxsplit=1)[0]
    for token in re.split(r"\s*,\s*", left):
        token = token.strip()
        if token.isdigit():
            days.append(int(token))

    if not days:
        return []

    results: list[datetime] = []
    for day in days:
        year = _pick_year(month, day, ref)
        try:
            results.append(datetime(year, month, day, 10, 0))
        except ValueError:
            continue
    return results


def _pick_year(month: int, day: int, ref: datetime) -> int:
    """If the parsed date would be more than 30 days in the past, roll to next year."""
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
