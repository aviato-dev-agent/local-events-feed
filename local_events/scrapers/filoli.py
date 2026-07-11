"""Filoli Historic House & Garden — full events calendar.

filoli.org runs The Events Calendar (Tribe) WordPress plugin, exposing a
public REST API at /wp-json/tribe/events/v1/events. Same shape as Hiller
and CuriOdyssey.
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

API_URL = "https://filoli.org/wp-json/tribe/events/v1/events"
DEFAULT_LOCATION = "Filoli, 86 Cañada Rd, Woodside, CA 94062"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_SKIP_TITLE = (
    "closed",
    "closure",
    "member preview",
    "member morning",
    "member appreciation",
    "member only",
    "members only",
    "board meeting",
    "gala",
    "fundraiser",
    "annual meeting",
    "wine tasting",
    "wine dinner",
    "wine club",
    "legacy wine",
    "private event",
    "corporate",
)


def fetch(city_tag: str = "WS", lookahead_days: int = 90) -> list[Event]:
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

    log.info("filoli: %d events after filter", len(events))
    return events


def _to_event(ev: dict, city_tag: str) -> Event | None:
    title = html.unescape((ev.get("title") or "").strip())
    if not title or _should_skip(title):
        return None

    try:
        start = dtparse.parse(ev["start_date"])
        end = dtparse.parse(ev["end_date"]) if ev.get("end_date") else None
    except (KeyError, ValueError):
        return None

    venue = ev.get("venue") or {}
    parts = [
        html.unescape(venue.get("venue", "")),
        venue.get("address"),
        venue.get("city"),
    ]
    location = ", ".join(p for p in parts if p) or DEFAULT_LOCATION

    description = _clean_html(ev.get("description") or ev.get("excerpt") or "")

    return Event(
        source="filoli",
        source_id=str(ev.get("id") or ev.get("slug") or ev["url"]),
        city_tag=city_tag,
        title=title,
        start=start.replace(tzinfo=None),
        end=end.replace(tzinfo=None) if end else None,
        location=location,
        description=description,
        ages="All ages",
        registration=None,
        url=ev.get("url", ""),
        tz=TZ,
    )


def _should_skip(title: str) -> bool:
    low = title.lower().replace("’", "'")
    return any(t in low for t in _SKIP_TITLE)


def _clean_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).strip()
    if len(s) > 800:
        s = s[:800].rsplit(" ", 1)[0] + "…"
    return s
