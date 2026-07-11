"""The Hub RWC — event calendar via embedded Google Calendar.

Their event-calendar page renders as a Wix "Google Calendar Connector" widget.
If the venue has configured a public Google Calendar, its iframe src contains
`calendar.google.com/calendar/embed?src=<encoded-calendar-id>`. We extract that
ID and read the public ICS feed at
`https://calendar.google.com/calendar/ical/<id>/public/basic.ics`.

Currently the venue shows a placeholder — no iframe present, no events. The
scraper returns [] until they configure the widget.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from ..event import Event

log = logging.getLogger(__name__)

CALENDAR_PAGE_URL = "https://www.thehubrwc.com/event-calendar"
LOCATION = "The Hub RWC, 2650 Broadway, Redwood City, CA 94063"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_CAL_ID_RE = re.compile(
    r"calendar\.google\.com/calendar/embed[^\"']*[?&]src=([^&\"'<>]+)",
    re.IGNORECASE,
)


def fetch(city_tag: str = "RWC", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    horizon = datetime.now() + timedelta(days=lookahead_days)
    today = datetime.now()

    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
            r = client.get(CALENDAR_PAGE_URL)
            r.raise_for_status()
            page_html = r.text
    except Exception as exc:
        log.warning("thehub: page fetch failed: %s", exc)
        return events

    m = _CAL_ID_RE.search(page_html)
    if not m:
        log.info("thehub: no Google Calendar embed detected (placeholder or unconfigured)")
        return events

    cal_id = unquote(m.group(1))
    ics_url = f"https://calendar.google.com/calendar/ical/{cal_id}/public/basic.ics"

    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
            r = client.get(ics_url)
            r.raise_for_status()
            cal = Calendar.from_ical(r.content)
    except Exception as exc:
        log.warning("thehub: ICS fetch/parse failed: %s", exc)
        return events

    for component in cal.walk("VEVENT"):
        start = _to_local(component.get("dtstart").dt) if component.get("dtstart") else None
        if not start:
            continue
        if start < today - timedelta(hours=6) or start > horizon:
            continue

        end_prop = component.get("dtend")
        end = _to_local(end_prop.dt) if end_prop else None

        title = str(component.get("summary") or "").strip()
        if not title:
            continue

        events.append(
            Event(
                source="thehub",
                source_id=str(component.get("uid") or f"thehub-{start.strftime('%Y%m%d%H%M')}"),
                city_tag=city_tag,
                title=title,
                start=start,
                end=end,
                location=str(component.get("location") or LOCATION).strip() or LOCATION,
                description=str(component.get("description") or "").strip() or f"Source: {CALENDAR_PAGE_URL}",
                ages="All ages",
                registration=None,
                url=CALENDAR_PAGE_URL,
                tz=TZ,
            )
        )

    log.info("thehub: %d events after filter", len(events))
    return events


_PT = ZoneInfo("America/Los_Angeles")


def _to_local(dt):
    """Convert an ICS datetime/date to naive local America/Los_Angeles wall time."""
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(_PT).replace(tzinfo=None)
        return dt
    return datetime(dt.year, dt.month, dt.day, 9, 0)
