"""Hidden Villa (Los Altos Hills) — family programs.

Hidden Villa runs an Arlo-backed program catalog. Each program's detail page
lists all upcoming session dates as plain text rows like "Sep 11 7:30pm - 9:30pm".

We fetch the family calendar index at /calendar/individuals-families/region-HV/,
extract each program URL, and parse dated sessions from every detail page.
Star Party is included via the general crawl; it also has a shortcut fallback
in case the index changes structure.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from ..event import Event

log = logging.getLogger(__name__)

FAMILY_INDEX_URL = "https://www.hiddenvilla.org/calendar/individuals-families/region-HV/"
STAR_PARTY_URL = "https://www.hiddenvilla.org/programs/catalog/555-star-party/region-HV/"
LOCATION = "Hidden Villa, 26870 Moody Road, Los Altos Hills, CA 94022"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_DATE_RE = re.compile(
    r"([A-Za-z]{3,4})\s+(\d{1,2})\s+"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"\s*(?:-|–|—|to)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
    re.IGNORECASE,
)

_PROGRAM_URL_RE = re.compile(
    r'href="(https?://www\.hiddenvilla\.org/programs/catalog/(\d+)-([a-z0-9-]+)/region-HV/)"',
    re.IGNORECASE,
)

# URL slug tokens that indicate non-family programs / staff-only content
_SKIP_URL_TOKENS = (
    "private", "custom", "board-meeting", "donor-circle", "admin",
    "database", "-test", "training-pt", "board-of-directors",
)


def fetch(city_tag: str = "LAH", lookahead_days: int = 90) -> list[Event]:
    horizon = datetime.now() + timedelta(days=lookahead_days)
    today = datetime.now()
    events: list[Event] = []
    seen: set[tuple[str, datetime]] = set()

    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        program_urls = _discover_program_urls(client)
        # Always include Star Party as a fallback in case the index breaks.
        program_urls.setdefault("555", (STAR_PARTY_URL, "star-party"))

        for program_id, (url, slug) in program_urls.items():
            if any(t in url.lower() for t in _SKIP_URL_TOKENS):
                continue
            try:
                page = client.get(url)
                page.raise_for_status()
            except Exception as exc:
                log.warning("hiddenvilla: fetch failed for %s: %s", url, exc)
                continue

            title = _extract_title(page.text, slug)
            text = re.sub(r"\s+", " ", BeautifulSoup(page.text, "html.parser").get_text(" ", strip=True))

            for start, end in _iter_sessions(text, today, horizon):
                key = (program_id, start)
                if key in seen:
                    continue
                seen.add(key)
                events.append(
                    Event(
                        source="hiddenvilla",
                        source_id=f"{program_id}-{start.strftime('%Y%m%d%H%M')}",
                        city_tag=city_tag,
                        title=title,
                        start=start,
                        end=end,
                        location=LOCATION,
                        description=f"Hidden Villa program.\n\nSource: {url}",
                        ages="Family / all ages",
                        registration=True,
                        url=url,
                        tz=TZ,
                    )
                )

            time.sleep(0.3)

    log.info("hiddenvilla: %d events after filter", len(events))
    return events


def _discover_program_urls(client: httpx.Client) -> dict[str, tuple[str, str]]:
    """Return {program_id: (url, slug)} for every distinct program on the index."""
    try:
        r = client.get(FAMILY_INDEX_URL)
        r.raise_for_status()
    except Exception as exc:
        log.warning("hiddenvilla: index fetch failed: %s", exc)
        return {}

    urls: dict[str, tuple[str, str]] = {}
    for m in _PROGRAM_URL_RE.finditer(r.text):
        url, pid, slug = m.group(1), m.group(2), m.group(3)
        urls.setdefault(pid, (url, slug))
    return urls


def _extract_title(html_text: str, slug: str) -> str:
    """Prefer <h1> from the page; fall back to slug titleized."""
    soup = BeautifulSoup(html_text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)
        if 3 < len(title) < 120:
            return title
    return slug.replace("-", " ").title()


def _iter_sessions(text: str, today: datetime, horizon: datetime):
    for m in _DATE_RE.finditer(text):
        raw_month = m.group(1).lower()
        month_key = "sept" if raw_month == "sept" else raw_month[:3]
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

        yield start, end


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
