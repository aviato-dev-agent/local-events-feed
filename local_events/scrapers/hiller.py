"""Hiller Aviation Museum events.

hiller.org runs The Events Calendar (Tribe) WordPress plugin, which exposes a
public REST API at /wp-json/tribe/events/v1/events with full event data
including venue and start/end times. No scraping needed.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta
from typing import Iterable

import httpx
from dateutil import parser as dtparse

from ..event import Event

log = logging.getLogger(__name__)

API_URL = "https://www.hiller.org/wp-json/tribe/events/v1/events"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_KIDS_HINTS = ("kid", "children", "family", "junior", "youth", "all ages", "girls", "boys")
# Titles filtered out. Uses .lower() and normalizes curly apostrophes to ascii
# before matching (Hiller frequently uses U+2019).
_SKIP_TITLE = (
    "today's schedule",
    "closed",
    "member preview",
    "member appreciation",
    "gala",
    "fundraiser",
    "board meeting",
    "museum closes early",
    "private event",
    # Daily rotating exhibits/features that clutter the calendar
    "drone plex",
    "flight sim zone",
    "invention lab",
    "fmx flight sim",
)


def fetch(city_tag: str = "SC", lookahead_days: int = 90) -> list[Event]:
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
                # Tribe returns 400 when the page is past the last one
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

    log.info("hiller: %d events after filter", len(events))
    return events


def _to_event(ev: dict, city_tag: str) -> Event | None:
    title = html.unescape((ev.get("title") or "").strip())
    if not title:
        return None
    if _should_skip(title):
        return None

    try:
        start = dtparse.parse(ev["start_date"])
        end = dtparse.parse(ev["end_date"]) if ev.get("end_date") else None
    except (KeyError, ValueError):
        return None

    venue = ev.get("venue") or {}
    parts = [venue.get("venue"), venue.get("address"), venue.get("city")]
    location = ", ".join(p for p in parts if p) or "Hiller Aviation Museum, 601 Skyway Rd, San Carlos, CA"

    description = _clean_html(ev.get("description") or ev.get("excerpt") or "")

    return Event(
        source="hiller",
        source_id=str(ev.get("id") or ev.get("slug") or ev["url"]),
        city_tag=city_tag,
        title=title,
        start=start.replace(tzinfo=None),
        end=end.replace(tzinfo=None) if end else None,
        location=location,
        description=description,
        ages=_infer_ages(title, description),
        registration=None,
        url=ev.get("url", ""),
        tz=TZ,
    )


def _should_skip(title: str) -> bool:
    low = title.lower().replace("’", "'").replace("‘", "'")
    return any(t in low for t in _SKIP_TITLE)


def _infer_ages(title: str, desc: str) -> str:
    hay = f"{title} {desc}".lower()
    if any(k in hay for k in _KIDS_HINTS):
        return "Family / kids"
    return "All ages"


def _clean_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    # Strip Divi / WP page-builder shortcodes like [et_pb_section ...] [/et_pb_row]
    s = re.sub(r"\[/?[a-z][a-z0-9_]*[^\]]*\]", "", s, flags=re.IGNORECASE)
    s = html.unescape(s).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    if len(s) > 800:
        s = s[:800].rsplit(" ", 1)[0] + "…"
    return s
