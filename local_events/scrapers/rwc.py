"""Redwood City events via scrape.do.

redwoodcity.org is Akamai-blocked to all automated HTTP requests. We route
through scrape.do (residential proxy + headless Chrome) to fetch the CivicPlus
calendar HTML directly.

Each run scrapes current month + next month so we have ~60 days of coverage.
Cost: 5 scrape.do credits per request × 2 requests/run = 10 credits/run.
At 1 run/day: ~300 credits/month against a 1,000-credit free tier.

Calendar HTML shape (CivicPlus):
  <td class="calendar_day_with_items">
    ...day number in text or child element...
    <div class="calendar_item">
      <span class="calendar_eventtime">6:00 PM</span>
      <a class="calendar_eventlink" href="..." title="Event Title">...</a>
    </div>
    ...
  </td>
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from ..event import Event
from .sanmateopl import _is_under_six

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"
UA = "Mozilla/5.0 (compatible; local-events-sync/1.0; +https://github.com/aviato-dev-agent/local-events-feed)"
_BASE_CAL_URL = "https://www.redwoodcity.org/residents/redwood-city-events/city-events-calendar"
_SCRAPE_DO_URL = "https://api.scrape.do"

_ADULT_TOKENS = ("adult", " 18+", " 21+", "seniors only")
_ADULT_ALLOW = ("family", "all ages", "kids", "children")
_CLOSURE_TOKENS = ("offices closed", "closed:", "holiday", "cancelled", "canceled")
_SKIP_TITLE_TOKENS = ("no music", "no movies")


def fetch(
    token: str,
    city_tag: str = "RWC",
    lookahead_days: int = 90,
    months_ahead: int = 2,
) -> list[Event]:
    now = datetime.now()
    horizon = now + timedelta(days=lookahead_days)
    events: list[Event] = []

    for year, month in _months_to_scrape(now.date(), months_ahead):
        html = _fetch_page(token, year, month)
        if html:
            events.extend(_parse_month(html, year, month, city_tag, now, horizon))

    log.info("rwc: %d events after filter", len(events))
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
        log.warning("rwc: scrape.do fetch failed for %d-%02d: %s", year, month, exc)
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

            if _skip_title(title):
                continue
            start = _combine(event_date, time_str)
            if start < now - timedelta(hours=6) or start > horizon:
                continue
            if _is_closure(title):
                continue
            if _is_under_six(title, "", ""):
                continue
            if _is_adult_only(title):
                continue

            events.append(
                Event(
                    source="rwc",
                    source_id=_source_id(url),
                    city_tag=city_tag,
                    title=title,
                    start=start,
                    end=None,
                    location=_infer_location(title),
                    description=f"See event page: {url}",
                    ages="All ages",
                    registration=None,
                    url=url,
                    tz=TZ,
                )
            )

    return events


def _extract_day(td) -> int | None:
    # CivicPlus puts the day number in various places depending on version.
    # Try data attribute first, then common child selectors, then regex on all text.
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

    # Last resort: first standalone 1-2 digit number in the td's direct text nodes
    for text in td.find_all(string=True, recursive=False):
        m = re.search(r"\b(\d{1,2})\b", text)
        if m:
            return int(m.group(1))

    # Fallback: first number anywhere in the td
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
    return f"event-{m.group(1)}" if m else url


_LOCATION_HINTS = (
    ("courthouse square", "Courthouse Square, Redwood City"),
    ("on the square", "Courthouse Square, Redwood City"),
    ("red morton", "Red Morton Park, Redwood City"),
    ("magical bridge", "Magical Bridge Playground, Redwood City"),
    ("stafford park", "Stafford Park, Redwood City"),
    ("music in the park", "Stafford Park, Redwood City"),
    ("pub in the park", "Red Morton Park, Redwood City"),
    ("parcade", "Red Morton Park, Redwood City"),
    ("sounds of the shores", "Marina Shores, Redwood City"),
)


def _infer_location(title: str) -> str:
    low = title.lower()
    for hint, loc in _LOCATION_HINTS:
        if hint in low:
            return loc
    return "Redwood City"


def _skip_title(title: str) -> bool:
    return any(t in title.lower() for t in _SKIP_TITLE_TOKENS)


def _is_closure(title: str) -> bool:
    return any(t in title.lower() for t in _CLOSURE_TOKENS)


def _is_adult_only(title: str) -> bool:
    low = title.lower()
    if any(t in low for t in _ADULT_TOKENS):
        return not any(x in low for x in _ADULT_ALLOW)
    return False
