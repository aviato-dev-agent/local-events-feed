"""Menlo Park citywide events calendar (OpenCities/Granicus CMS).

Scrapes the Citywide-calendar page which aggregates events from all city
departments. Times are embedded inline in the listing — no detail-page
enrichment needed for dates/times. Description is fetched from the detail page.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..event import Event
from .sanmateopl import _is_under_six

log = logging.getLogger(__name__)

BASE = "https://www.menlopark.gov"
URL = "https://www.menlopark.gov/Citywide-calendar/Events"
TZ = "America/Los_Angeles"
UA = "Mozilla/5.0 (compatible; local-events-sync/1.0; +https://github.com/aviato-dev-agent/local-events-feed)"

MEETING_TOKENS = (
    "city council", "planning commission", "board of", "commission meeting",
    "public hearing", "city manager", "parks & recreation commission",
    "zoning hearing",
)
ADULT_TOKENS = ("adult book club", "grown-up", " 18+", " 21+", "seniors only")
CLOSURE_TOKENS = ("offices closed", "closure:", "closed:", "holiday - administrative", "library closed")

DATE_PATTERNS = [
    (re.compile(r"([A-Z][a-z]+),\s+([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})"), "%B %d %Y"),
    (re.compile(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})"), "%d %b %Y"),
    (re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})"), "%B %d %Y"),
]

_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2})\s*(AM|PM)\s+to\s+(\d{1,2}:\d{2})\s*(AM|PM)",
    re.IGNORECASE,
)


def fetch(city_tag: str = "MP", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    seen_hrefs: set[str] = set()
    horizon = datetime.now() + timedelta(days=lookahead_days)

    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        try:
            r = client.get(URL)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("menlopark_city: fetch failed: %s", exc)
            return events

        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".list-item-container"):
            title_el = item.select_one(".list-item-title")
            date_el = item.select_one(".event-date")
            addr_el = item.select_one(".list-item-address")
            a = item.find("a", href=True)
            if not title_el or not date_el or not a:
                continue

            title = title_el.get_text(strip=True)
            href = urljoin(BASE, a["href"])
            if href in seen_hrefs:
                continue

            date_text = date_el.get_text(" ", strip=True)
            start, end = _parse_date_time(date_text)
            if not start:
                continue
            if start > horizon or start < datetime.now() - timedelta(days=1):
                continue

            location = addr_el.get_text(" ", strip=True) if addr_el else "Menlo Park"

            if _is_closure(title):
                continue
            if _is_meeting(title):
                continue
            if _is_under_six(title, "", ""):
                continue
            if _is_adult_only(title):
                continue

            desc = _fetch_description(href, client)
            seen_hrefs.add(href)
            events.append(
                Event(
                    source="menlopark_city",
                    source_id=_uid(href),
                    city_tag=city_tag,
                    title=title,
                    start=start,
                    end=end,
                    location=location,
                    description=desc,
                    ages=_infer_ages(title, desc, href),
                    registration=None,
                    url=href,
                    tz=TZ,
                )
            )

    log.info("menlopark_city: %d events", len(events))
    return events


def _parse_date_time(text: str):
    """Parse 'Wednesday, July 08, 2026 | 03:30 PM to 05:30 PM' → (start, end)."""
    if "|" in text:
        date_part, time_part = text.split("|", 1)
    else:
        date_part, time_part = text, ""

    start_date = _parse_date(date_part.strip())
    if not start_date:
        return None, None

    m = _TIME_RANGE_RE.search(time_part)
    if m:
        try:
            st = datetime.strptime(f"{m.group(1)} {m.group(2).upper()}", "%I:%M %p").time()
            et = datetime.strptime(f"{m.group(3)} {m.group(4).upper()}", "%I:%M %p").time()
            start = start_date.replace(hour=st.hour, minute=st.minute)
            end = start_date.replace(hour=et.hour, minute=et.minute)
            if end <= start:
                end += timedelta(days=1)
            return start, end
        except ValueError:
            pass

    return start_date, None


def _parse_date(text: str):
    for pattern, fmt in DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if fmt == "%B %d %Y" and len(m.groups()) == 4:
                return datetime.strptime(f"{m.group(2)} {m.group(3)} {m.group(4)}", fmt)
            if fmt == "%d %b %Y":
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
        except (ValueError, IndexError):
            continue
    return None


def _fetch_description(url: str, client: httpx.Client) -> str:
    try:
        r = client.get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for name, attr in (("description", "name"), ("og:description", "property")):
            tag = soup.find("meta", attrs={attr: name})
            if tag and tag.get("content", "").strip():
                return re.sub(r"\s+", " ", tag["content"].strip())[:800]
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 60:
                return re.sub(r"\s+", " ", t)[:800]
    except Exception as exc:
        log.debug("menlopark_city desc fetch failed for %s: %s", url, exc)
    return ""


def _uid(href: str) -> str:
    return href.rstrip("/").rsplit("/", 1)[-1] or href


def _is_meeting(title: str) -> bool:
    low = title.lower()
    return any(t in low for t in MEETING_TOKENS)


def _is_closure(title: str) -> bool:
    return any(t in title.lower() for t in CLOSURE_TOKENS)


def _is_adult_only(title: str) -> bool:
    low = title.lower()
    if any(t in low for t in ADULT_TOKENS):
        return not any(x in low for x in ("family", "kids", "children", "all ages"))
    return False


def _infer_ages(title: str, description: str, href: str) -> str:
    hay = f"{title} {description} {href}".lower()
    if "children" in hay or "kids" in hay:
        return "children"
    if "teen" in hay:
        return "teens"
    if "family" in hay or "community" in hay or "all ages" in hay:
        return "All ages / family"
    return "All ages"
