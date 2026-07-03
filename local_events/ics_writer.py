"""Generate a subscribable ICS feed from normalized events."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from icalendar import Calendar, Event as ICalEvent, Timezone, TimezoneStandard, TimezoneDaylight
from zoneinfo import ZoneInfo

from .event import Event as MyEvent

PACIFIC = ZoneInfo("America/Los_Angeles")


def build_calendar(events: Iterable[MyEvent], name: str = "Local Events") -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//local-events-sync//tim//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", name)
    cal.add("x-wr-timezone", "America/Los_Angeles")
    cal.add("x-wr-caldesc", "Family & kids events on the mid-Peninsula. Auto-synced daily.")
    cal.add("x-published-ttl", "PT1H")

    now_utc = datetime.now(timezone.utc)
    for e in events:
        ev = ICalEvent()
        ev.add("uid", e.uid())
        ev.add("summary", e.title)
        # Localize naive times to Pacific
        start = e.start if e.start.tzinfo else e.start.replace(tzinfo=PACIFIC)
        end = e.end if e.end.tzinfo else e.end.replace(tzinfo=PACIFIC)
        ev.add("dtstart", start)
        ev.add("dtend", end)
        ev.add("dtstamp", now_utc)
        if e.location:
            ev.add("location", e.location)
        if e.url:
            ev.add("url", e.url)
        ev.add("description", _format_notes(e))
        cal.add_component(ev)

    return cal.to_ical()


def _format_notes(e: MyEvent) -> str:
    lines = []
    if e.description:
        lines.append(e.description.strip())
        lines.append("")
    lines.append(f"Ages: {e.ages}")
    if e.registration is True:
        lines.append("Registration: required")
    elif e.registration is False:
        lines.append("Registration: none")
    if e.url:
        lines.append(f"Source: {e.url}")
    lines.append(f"Last synced: {datetime.now(PACIFIC).strftime('%Y-%m-%d %H:%M %Z')}")
    return "\n".join(lines)
