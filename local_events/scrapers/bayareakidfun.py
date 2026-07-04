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

    # Enrich each event by visiting its source URL for a real description +
    # actual times (replacing the 10am placeholder). Cache by URL to avoid
    # refetching when several events point to the same page.
    _enrich_all(unique)

    log.info("bayareakidfun: %d events after filter", len(unique))
    return unique


def _enrich_all(events: list[Event]) -> None:
    """Visit each event's source URL and augment description + times."""
    from bs4 import BeautifulSoup

    cache: dict[str, tuple] = {}
    enrich_headers = dict(HEADERS)
    with httpx.Client(headers=enrich_headers, timeout=10, follow_redirects=True) as client:
        for e in events:
            if e.url in cache:
                real_desc, start_hm, end_hm = cache[e.url]
            else:
                real_desc, start_hm, end_hm = _enrich_one(e.url, client, BeautifulSoup)
                cache[e.url] = (real_desc, start_hm, end_hm)

            if real_desc:
                e.description = f"{real_desc}\n\n{e.description}"
            if start_hm is not None:
                sh, sm = start_hm
                e.start = e.start.replace(hour=sh, minute=sm)
                if end_hm is not None:
                    eh, em = end_hm
                    end_dt = e.start.replace(hour=eh, minute=em)
                    if end_dt <= e.start:
                        end_dt = end_dt + timedelta(days=1)
                    e.end = end_dt
                else:
                    e.end = e.start + timedelta(hours=1)


def _enrich_one(url: str, client, BeautifulSoup):
    """Fetch one source URL. Returns (description, start_hm, end_hm) — any may be None.

    All failures return (None, None, None) so callers keep the placeholders.
    """
    try:
        r = client.get(url)
        r.raise_for_status()
        if "html" not in r.headers.get("content-type", "").lower():
            return None, None, None
        html = r.text
    except Exception as exc:
        log.debug("bayareakidfun enrich failed for %s: %s", url, exc)
        return None, None, None

    soup = BeautifulSoup(html, "html.parser")

    # --- Description: try meta first, then og:, then first substantial <p>
    desc = None
    for name, attr in (("description", "name"), ("og:description", "property")):
        tag = soup.find("meta", attrs={attr: name})
        if tag and tag.get("content"):
            desc = tag["content"].strip()
            if desc:
                break
    if not desc:
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 60:
                desc = t
                break

    if desc:
        # Trim to a reasonable length
        desc = re.sub(r"\s+", " ", desc).strip()
        if len(desc) > 800:
            desc = desc[:800].rsplit(" ", 1)[0] + "…"

    # --- Times: search description + any event-time-ish tags + a slice of body
    time_hay_parts: list[str] = []
    if desc:
        time_hay_parts.append(desc)
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []) or []).lower()
        idstr = (tag.get("id") or "").lower()
        if any(kw in classes or kw in idstr for kw in ("time", "when", "hours", "schedule")):
            time_hay_parts.append(tag.get_text(" ", strip=True))
            if sum(len(x) for x in time_hay_parts) > 4000:
                break
    if not time_hay_parts:
        time_hay_parts.append(soup.get_text(" ", strip=True)[:3000])

    hay = " | ".join(time_hay_parts)
    start_hm, end_hm = _parse_time(hay)
    return desc, start_hm, end_hm


# Time patterns, tried in order of specificity
_TIME_RANGE_FULL = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)"
    r"\s*(?:-|–|—|to)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|noon|midnight)",
    re.IGNORECASE,
)
_TIME_RANGE_TO_NOON = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)"
    r"\s*(?:-|–|—|to)\s*"
    r"(noon|midnight)",
    re.IGNORECASE,
)
_TIME_RANGE_SHARED_AMPM = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(?:-|–|—|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)",
    re.IGNORECASE,
)
_TIME_SINGLE = re.compile(
    r"(?:at|from|starts?\s+at|begins?\s+at|@)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)",
    re.IGNORECASE,
)


def _parse_time(text: str):
    """Return ((start_h, start_m), (end_h, end_m)) or (start, None) or (None, None)."""
    m = _TIME_RANGE_FULL.search(text)
    if m:
        s_h = _to_24(int(m.group(1)), m.group(3))
        s_m = int(m.group(2) or 0)
        end_marker = m.group(6).lower()
        if end_marker in ("noon", "midnight"):
            e_h, e_m = (12, 0) if end_marker == "noon" else (0, 0)
        else:
            e_h = _to_24(int(m.group(4)), m.group(6))
            e_m = int(m.group(5) or 0)
        return (s_h, s_m), (e_h, e_m)

    m = _TIME_RANGE_TO_NOON.search(text)
    if m:
        s_h = _to_24(int(m.group(1)), m.group(3))
        s_m = int(m.group(2) or 0)
        end = m.group(4).lower()
        e_h, e_m = (12, 0) if end == "noon" else (0, 0)
        return (s_h, s_m), (e_h, e_m)

    m = _TIME_RANGE_SHARED_AMPM.search(text)
    if m:
        ampm = m.group(5)
        s_h = _to_24(int(m.group(1)), ampm)
        s_m = int(m.group(2) or 0)
        e_h = _to_24(int(m.group(3)), ampm)
        e_m = int(m.group(4) or 0)
        # If end hour <= start hour in same-ampm context, likely PM (e.g. "10-2 pm")
        if e_h < s_h and ampm.lower().startswith("p"):
            e_h += 12
        return (s_h, s_m), (e_h, e_m)

    m = _TIME_SINGLE.search(text)
    if m:
        s_h = _to_24(int(m.group(1)), m.group(3))
        s_m = int(m.group(2) or 0)
        return (s_h, s_m), None

    return None, None


def _to_24(hour: int, ampm: str) -> int:
    ampm = ampm.replace(".", "").lower()
    if ampm.startswith("p") and hour != 12:
        return hour + 12
    if ampm.startswith("a") and hour == 12:
        return 0
    return hour


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
