"""Flows To Bay (SMCWPPP) — county-wide creek/watershed events aggregator.

flowstobay.org runs The Events Calendar plugin which exposes a native
ICS export at /events/?ical=1. One-shot passthrough — parse ICS, convert
to our Event schema, and rely on the volunteer classifier + per-source
override to route to the volunteer feed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from icalendar import Calendar

from ..event import Event

log = logging.getLogger(__name__)

ICS_URL = "https://www.flowstobay.org/events/?ical=1"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

# Best-effort city tagging by keyword match on title/location.
_CITY_KEYWORDS = (
    ("redwood city", "RWC"),
    ("menlo park", "MP"),
    ("palo alto", "PA"),
    ("san carlos", "SC"),
    ("belmont", "B"),
    ("san mateo", "SM"),
    ("burlingame", "BUR"),
    ("half moon bay", "HMB"),
    ("pacifica", "PAC"),
    ("east palo alto", "EPA"),
    ("atherton", "ATH"),
    ("foster city", "FC"),
    ("millbrae", "MIL"),
    ("brisbane", "BRIS"),
    ("colma", "COL"),
    ("daly city", "DC"),
    ("hillsborough", "HIL"),
    ("portola valley", "PV"),
    ("woodside", "WS"),
    ("south san francisco", "SSF"),
)


def fetch(city_tag: str = "SM", lookahead_days: int = 90) -> list[Event]:
    horizon = datetime.now(timezone.utc) + timedelta(days=lookahead_days)
    now = datetime.now(timezone.utc)
    events: list[Event] = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        r = client.get(ICS_URL)
        r.raise_for_status()
        cal = Calendar.from_ical(r.text)

    for comp in cal.walk("VEVENT"):
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        start = dtstart.dt
        if isinstance(start, datetime):
            start_dt = start
        else:
            start_dt = datetime.combine(start, datetime.min.time())

        start_utc = start_dt.astimezone(timezone.utc) if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)
        if start_utc > horizon or start_utc < now - timedelta(hours=6):
            continue

        end_prop = comp.get("DTEND")
        end_dt = None
        if end_prop is not None:
            end_raw = end_prop.dt
            end_dt = end_raw if isinstance(end_raw, datetime) else datetime.combine(end_raw, datetime.min.time())

        title = str(comp.get("SUMMARY", "")).strip()
        if not title:
            continue
        location = str(comp.get("LOCATION", "")).strip()
        description = str(comp.get("DESCRIPTION", "")).strip()
        url = str(comp.get("URL", "")) if comp.get("URL") else ""

        tag = _tag_for(f"{title} {location} {description}".lower(), city_tag)

        events.append(Event(
            source="flowstobay",
            source_id=str(comp.get("UID", f"{title}-{start_dt.isoformat()}")),
            city_tag=tag,
            title=title,
            start=start_dt.replace(tzinfo=None) if isinstance(start_dt, datetime) else start_dt,
            end=end_dt.replace(tzinfo=None) if isinstance(end_dt, datetime) else None,
            location=location,
            description=description,
            ages="Varies per event — many family-friendly. Confirm with event host.",
            registration=None,
            url=url,
            tz=TZ,
        ))
    log.info("flowstobay: %d events after filter", len(events))
    return events


def _tag_for(haystack: str, default: str) -> str:
    for kw, tag in _CITY_KEYWORDS:
        if kw in haystack:
            return tag
    return default
