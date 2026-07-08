"""Redwood City events via FetchRSS.

redwoodcity.org is Akamai-blocked to all automated HTTP requests. FetchRSS
scrapes it from a residential IP and republishes as RSS.

Feed shape (as configured):
  <item> = one calendar day
  <title>  = day of month, e.g. "1", "8"
  <description> CDATA = HTML with multiple .calendar_item divs, each:
      <span class="calendar_eventtime">6:00 PM</span>
      <a class="calendar_eventlink" href="..." title="Music in the Park...">...</a>

The feed does not include month/year — the RWC calendar view is always the
current month. We assume any day number is either this month (if >= today)
or next month (if < today).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from ..event import Event
from .sanmateopl import _is_under_six

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"
UA = "Mozilla/5.0 (compatible; local-events-sync/1.0; +https://github.com/aviato-dev-agent/local-events-feed)"

_ADULT_TOKENS = ("adult", " 18+", " 21+", "seniors only")
_ADULT_ALLOW = ("family", "all ages", "kids", "children")
_CLOSURE_TOKENS = ("offices closed", "closed:", "holiday", "cancelled", "canceled")
_SKIP_TITLE_TOKENS = ("no music", "no movies")  # "NO Music on the Square" is an anti-event


def fetch(rss_url: str, city_tag: str = "RWC", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    now = datetime.now()
    horizon = now + timedelta(days=lookahead_days)

    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
            r = client.get(rss_url)
            r.raise_for_status()
            root = ElementTree.fromstring(r.content)
    except Exception as exc:
        log.warning("rwc_rss: fetch/parse failed for %s: %s", rss_url, exc)
        return events

    channel = root.find("channel")
    if channel is None:
        log.warning("rwc_rss: no <channel> element")
        return events

    for item in channel.findall("item"):
        day_text = (item.findtext("title") or "").strip()
        try:
            day = int(day_text)
        except ValueError:
            continue

        event_date = _resolve_date(day, now.date())
        desc_html = item.findtext("description") or ""

        for time_str, title, url in _parse_events(desc_html):
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
                    source="rwc_rss",
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

    log.info("rwc_rss: %d events after filter", len(events))
    return events


def _resolve_date(day: int, today: date) -> date:
    """FetchRSS mirrors the RWC 'current month' view. Assume the day is this month.
    Past-month days fall out via the horizon filter downstream.
    For next-month coverage, set up a second FetchRSS feed pointed at ?curm=N+1.
    """
    try:
        return date(today.year, today.month, day)
    except ValueError:
        return today  # invalid day-of-month; horizon filter will drop it


def _parse_events(html: str):
    """Yield (time_str, title, url) for each .calendar_item in the description."""
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select(".calendar_item"):
        time_el = item.select_one(".calendar_eventtime")
        link_el = item.select_one(".calendar_eventlink")
        if not link_el:
            continue
        time_str = time_el.get_text(strip=True) if time_el else ""
        title = link_el.get_text(strip=True) or link_el.get("title", "").strip()
        url = link_el.get("href", "").strip()
        if not title or not url:
            continue
        yield time_str, title, url


def _combine(d: date, time_str: str) -> datetime:
    """Combine a date with '1:00 PM' → datetime. Default to 10am if unparseable."""
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
    low = title.lower()
    return any(t in low for t in _SKIP_TITLE_TOKENS)


def _is_closure(title: str) -> bool:
    return any(t in title.lower() for t in _CLOSURE_TOKENS)


def _is_adult_only(title: str) -> bool:
    low = title.lower()
    if any(t in low for t in _ADULT_TOKENS):
        return not any(x in low for x in _ADULT_ALLOW)
    return False
