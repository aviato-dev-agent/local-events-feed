"""Redwood City Public Library events via scrape.do.

redwoodcity.org is Akamai-blocked to all automated HTTP requests. We route
through scrape.do (residential proxy + headless Chrome) to fetch the CivicPlus
calendar HTML directly — same pattern as rwc.py.

Cost: 5 scrape.do credits per request × 2 requests/run = 10 credits/run.
At 1 run/day: ~300 credits/month.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from ..event import Event
from .sanmateopl import _is_under_six

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"
_BASE_CAL_URL = "https://www.redwoodcity.org/departments/library/events"
_SCRAPE_DO_URL = "https://api.scrape.do"

_CLOSURE_TOKENS = ("closed", "closure", "holiday", "cancelled", "canceled")
_MEETING_TOKENS = (
    "city council", "planning commission", "board of", "commission meeting",
    "public hearing", "library board",
)
_SKIP_TOKENS = (
    "drop in tech help", "drop-in tech help", "tech help",
    "art salon",
    "friends donation",
    "pajama time stories",
    "tiny tales",
    "stories and songs",
    "malinky",
    "project read",
    # Teen programs — excluded until kids are older
    "teen", "tween", "middle school", "high school",
)

# Events that belong on the adult feed rather than the main family feed.
# Detected by title; ages field is set to signal is_adult_event().
_ADULT_PROGRAM_TOKENS = ("grown-up", "grown-ups", "tai chi", "open sewing")
_ADULT_AGES = "Adult program (kids welcome to tag along, not designed for them)"

# Spanish diacritics and "/" (bilingual separator) both indicate Spanish-language
# or bilingual content — excluded per user preference.
_SPANISH_CHARS = set("ñáéíóúüÁÉÍÓÚÜ¡¿")


def fetch(
    token: str,
    city_tag: str = "RWC",
    lookahead_days: int = 90,
    months_ahead: int = 2,
) -> list[Event]:
    now = datetime.now()
    horizon = now + timedelta(days=lookahead_days)
    events: list[Event] = []

    seen: set[str] = set()
    for year, month in _months_to_scrape(now.date(), months_ahead):
        html = _fetch_page(token, year, month)
        if html:
            for e in _parse_month(html, year, month, city_tag, now, horizon):
                key = f"{e.source_id}-{e.start.isoformat()}"
                if key not in seen:
                    seen.add(key)
                    events.append(e)

    log.info("rwc_library: %d events after filter", len(events))
    return events


def _months_to_scrape(today: date, months_ahead: int) -> list[tuple[int, int]]:
    result = []
    year, month = today.year, today.month
    for _ in range(months_ahead):
        result.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


def _fetch_page(token: str, year: int, month: int) -> str | None:
    cal_url = f"{_BASE_CAL_URL}?curm={month}&cury={year}"
    api_url = f"{_SCRAPE_DO_URL}/?token={token}&url={quote_plus(cal_url)}&render=true"
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            r = client.get(api_url)
            r.raise_for_status()
            return r.text
    except Exception as exc:
        log.warning("rwc_library: scrape.do fetch failed for %d-%02d: %s", year, month, exc)
        return None


def _parse_month(
    html: str, year: int, month: int, city_tag: str, now: datetime, horizon: datetime
) -> list[Event]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[Event] = []

    for td in soup.select("td.calendar_day_with_items"):
        day = _extract_day(td)
        if day is None:
            continue
        try:
            event_date = date(year, month, day)
        except ValueError:
            continue

        for item in td.select(".calendar_item"):
            time_el = item.select_one(".calendar_eventtime")
            link_el = item.select_one(".calendar_eventlink")
            if not link_el:
                continue

            time_str = time_el.get_text(strip=True) if time_el else ""
            title = link_el.get_text(strip=True) or link_el.get("title", "").strip()
            url = link_el.get("href", "").strip()
            if not title or not url:
                continue
            if not url.startswith("http"):
                url = f"https://www.redwoodcity.org{url}"

            if _should_skip(title):
                continue
            if _has_spanish_content(title):
                continue
            if _is_closure(title):
                continue
            if _is_meeting(title):
                continue
            if _is_under_six(title, "", ""):
                continue

            start = _combine(event_date, time_str)
            if start < now - timedelta(hours=6) or start > horizon:
                continue

            ages = _ADULT_AGES if _is_adult_program(title) else "All ages"

            events.append(
                Event(
                    source="rwc_library",
                    source_id=_source_id(url),
                    city_tag=city_tag,
                    title=title,
                    start=start,
                    end=None,
                    location="Redwood City Public Library, 1044 Middlefield Rd, Redwood City, CA 94063",
                    description=f"See event page: {url}",
                    ages=ages,
                    registration=None,
                    url=url,
                    tz=TZ,
                )
            )

    return events


def _extract_day(td) -> int | None:
    for attr in ("data-day", "data-date"):
        val = td.get(attr, "")
        m = re.search(r"\b(\d{1,2})\b", val)
        if m:
            return int(m.group(1))
    for selector in (
        ".calendar_day_number",
        "a.calendar_date",
        ".day-number",
        "td > a:first-child",
    ):
        el = td.select_one(selector)
        if el:
            m = re.search(r"\b(\d{1,2})\b", el.get_text())
            if m:
                return int(m.group(1))
    for text in td.find_all(string=True, recursive=False):
        m = re.search(r"\b(\d{1,2})\b", text)
        if m:
            return int(m.group(1))
    m = re.search(r"\b(\d{1,2})\b", td.get_text())
    return int(m.group(1)) if m else None


def _combine(d: date, time_str: str) -> datetime:
    if time_str:
        try:
            t = datetime.strptime(time_str.upper().replace(".", ""), "%I:%M %p").time()
            return datetime(d.year, d.month, d.day, t.hour, t.minute)
        except ValueError:
            pass
    return datetime(d.year, d.month, d.day, 10, 0)


def _source_id(url: str) -> str:
    m = re.search(r"/Event/(\d+)/", url)
    return f"rwclib-event-{m.group(1)}" if m else url


def _should_skip(title: str) -> bool:
    low = title.lower()
    return any(t in low for t in _SKIP_TOKENS)


def _has_spanish_content(title: str) -> bool:
    if "/" in title:
        return True
    return any(c in _SPANISH_CHARS for c in title)


def _is_closure(title: str) -> bool:
    return any(t in title.lower() for t in _CLOSURE_TOKENS)


def _is_meeting(title: str) -> bool:
    return any(t in title.lower() for t in _MEETING_TOKENS)


def _is_adult_program(title: str) -> bool:
    low = title.lower()
    return any(t in low for t in _ADULT_PROGRAM_TOKENS)
