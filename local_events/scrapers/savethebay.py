"""Save The Bay (San Francisco Bay chapter) — habitat restoration workdays.

savesfbay.org runs The Events Calendar (Tribe) plugin at
/wp-json/tribe/events/v1/events. Same shape as filoli.py / hiller.py.

Filters to Peninsula-relevant sites; skips East Bay / North Bay unless
they show up in a title tag we care about. Adds a per-event age note.

Ages: STB recommends 8+; under-16 with parent + waiver. 6yo eligibility
varies per event — see description note.
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

API_URL = "https://savesfbay.org/wp-json/tribe/events/v1/events"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

# Only emit events at these Peninsula-facing site names (matched in title
# or venue). Case-insensitive substring match.
_PENINSULA_SITES = (
    "palo alto",
    "baylands",
    "ravenswood",
    "bair island",
    "bedwell",
    "menlo park",
    "redwood city",
    "horizontal levee",
    "eden landing",  # borderline (Hayward) but often family-friendly
)

_AGE_NOTE = (
    "Save The Bay recommends ages 8+; under-16 must be accompanied by a "
    "parent/guardian and sign a waiver. 6-year-old eligibility varies per "
    "event — confirm with STB before registering."
)


def fetch(city_tag: str = "PA", lookahead_days: int = 90) -> list[Event]:
    horizon = (datetime.now() + timedelta(days=lookahead_days)).date()
    events: list[Event] = []
    page = 1
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        while True:
            r = client.get(
                API_URL,
                params={
                    "per_page": 50,
                    "page": page,
                    "start_date": datetime.now().strftime("%Y-%m-%d"),
                    "end_date": horizon.strftime("%Y-%m-%d"),
                },
            )
            if r.status_code == 400:
                break
            r.raise_for_status()
            data = r.json()
            for ev in data.get("events", []):
                event = _to_event(ev, city_tag)
                if event:
                    events.append(event)
            if page >= data.get("total_pages", 1):
                break
            page += 1
    log.info("savethebay: %d events after filter", len(events))
    return events


def _to_event(ev: dict, default_city_tag: str) -> Event | None:
    title = html.unescape((ev.get("title") or "").strip())
    if not title:
        return None

    venue = ev.get("venue") or {}
    venue_name = html.unescape(venue.get("venue", "") or "")
    haystack = f"{title} {venue_name} {venue.get('address','')} {venue.get('city','')}".lower()
    if not any(site in haystack for site in _PENINSULA_SITES):
        return None

    try:
        start = dtparse.parse(ev["start_date"])
        end = dtparse.parse(ev["end_date"]) if ev.get("end_date") else None
    except (KeyError, ValueError):
        return None

    parts = [venue_name, venue.get("address"), venue.get("city")]
    location = ", ".join(p for p in parts if p) or "San Francisco Bay Area"

    tag = _tag_for(haystack, default_city_tag)
    description = _clean_html(ev.get("description") or ev.get("excerpt") or "")
    description = f"{description}\n\n{_AGE_NOTE}".strip()

    return Event(
        source="savethebay",
        source_id=str(ev.get("id") or ev.get("slug") or ev["url"]),
        city_tag=tag,
        title=title,
        start=start.replace(tzinfo=None),
        end=end.replace(tzinfo=None) if end else None,
        location=location,
        description=description,
        ages="8+ recommended (6+ with parent, per-event confirmation)",
        registration=True,
        url=ev.get("url", ""),
        tz=TZ,
    )


def _tag_for(haystack: str, default: str) -> str:
    if "ravenswood" in haystack or "menlo park" in haystack or "bedwell" in haystack:
        return "MP"
    if "redwood city" in haystack or "bair island" in haystack:
        return "RWC"
    if "palo alto" in haystack or "baylands" in haystack or "horizontal levee" in haystack:
        return "PA"
    return default


def _clean_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).strip()
    if len(s) > 800:
        s = s[:800].rsplit(" ", 1)[0] + "…"
    return s
