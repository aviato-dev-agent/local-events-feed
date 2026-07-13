"""Pacific Beach Coalition — monthly Adopt-A-Beach cleanups.

pacificbeachcoalition.org publishes per-beach "next cleanup" pages, each
containing a bulleted schedule of dates for the year. We fetch the 4 known
beach pages and extract "Month Dth, YYYY" date patterns.

Ages: under 14 must be adult-supervised; families explicitly welcome.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta

import httpx
from dateutil import parser as dtparse

from ..event import Event

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_AGE_NOTE = (
    "Pacific Beach Coalition cleanups are family-friendly; under-14 must "
    "be adult-supervised. Gloves and buckets available on-site — bring "
    "your own reusable ones if you can."
)

# (url_slug, event_title, city_tag, default_time_range_display)
_BEACHES = (
    ("next-esplanade-beach-cleanup", "Esplanade Beach Cleanup, Pacifica", "PAC", "9am–11am"),
    ("next-beach-cleanup-linda-mar", "Linda Mar Beach Cleanup, Pacifica", "PAC", "9am–11am"),
    ("next-cleanup-foster-city", "Foster City Cleanup", "FC", "9am–11am"),
    ("next-beach-cleanup-montara", "Montara Beach Cleanup", "HMB", "9am–11am"),
)

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_RE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(20\d{{2}})", re.IGNORECASE)
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[-–to]{1,3}\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.IGNORECASE)


def fetch(city_tag: str = "PAC", lookahead_days: int = 180) -> list[Event]:
    horizon = datetime.now() + timedelta(days=lookahead_days)
    now = datetime.now() - timedelta(hours=6)
    events: list[Event] = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for slug, title, tag, default_time in _BEACHES:
            url = f"https://www.pacificbeachcoalition.org/{slug}/"
            try:
                r = client.get(url)
                r.raise_for_status()
            except Exception as exc:
                log.warning("pacificbeach: %s failed: %s", slug, exc)
                continue

            # Try to extract a start/end time from the page (may be in a subhead)
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = html.unescape(re.sub(r"\s+", " ", text))
            start_h, start_m, end_h, end_m = _extract_time(text)
            time_note = default_time

            seen: set[str] = set()
            for month, day, year in _DATE_RE.findall(text):
                try:
                    d = dtparse.parse(f"{month} {day} {year}").date()
                except ValueError:
                    continue
                start = datetime.combine(d, datetime.min.time()).replace(hour=start_h, minute=start_m)
                end = datetime.combine(d, datetime.min.time()).replace(hour=end_h, minute=end_m)
                if not (now <= start <= horizon):
                    continue
                source_id = f"{slug}-{d.isoformat()}"
                if source_id in seen:
                    continue
                seen.add(source_id)
                events.append(Event(
                    source="pacificbeach",
                    source_id=source_id,
                    city_tag=tag,
                    title=title,
                    start=start,
                    end=end,
                    location=f"{title.split(',')[-1].strip() if ',' in title else 'Pacifica, CA'}",
                    description=f"Monthly Adopt-A-Beach cleanup ({time_note}).\n\n{_AGE_NOTE}",
                    ages="All ages (under-14 with adult)",
                    registration=False,
                    url=url,
                    tz=TZ,
                ))
    log.info("pacificbeach: %d events after filter", len(events))
    return events


def _extract_time(text: str) -> tuple[int, int, int, int]:
    m = _TIME_RE.search(text)
    if not m:
        return (9, 0, 11, 0)
    sh = int(m.group(1)) % 12
    if m.group(3).lower() == "pm":
        sh += 12
    sm = int(m.group(2) or 0)
    eh = int(m.group(4)) % 12
    if m.group(6).lower() == "pm":
        eh += 12
    em = int(m.group(5) or 0)
    return (sh, sm, eh, em)
