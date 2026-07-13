"""Canopy — Palo Alto / EPA / Menlo Park tree-planting & care events.

canopy.org/event-calendar embeds the Simple Calendar (simcal) WP plugin.
Each event carries schema.org/Event microdata with ISO startDate/endDate
in the `content="..."` attributes.

Ages: family-friendly framing; kids w/parent welcome per canopy.org. Confirm
per-event details before registering.
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

CALENDAR_URL = "https://canopy.org/event-calendar/"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_AGE_NOTE = (
    "Canopy events are family-friendly; children welcome with a parent. "
    "Wear closed-toe shoes and bring water. Confirm per-event details "
    "when registering."
)

_CITY_KEYWORDS = (
    ("east palo alto", "EPA"),
    ("menlo park", "MP"),
    ("palo alto", "PA"),
    ("zoom", "PA"),
    ("virtual", "PA"),
)


def fetch(city_tag: str = "PA", lookahead_days: int = 90) -> list[Event]:
    horizon = datetime.now() + timedelta(days=lookahead_days)
    now = datetime.now() - timedelta(hours=6)
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        r = client.get(CALENDAR_URL)
        r.raise_for_status()
        html_text = r.text

    events: list[Event] = []
    seen: set[str] = set()
    for m in re.finditer(r'<li class="simcal-event[^"]*"[^>]*data-start="(\d+)".*?</li>', html_text, flags=re.DOTALL):
        block = m.group(0)
        ev = _parse_block(block, city_tag)
        if not ev:
            continue
        if ev.source_id in seen:
            continue
        seen.add(ev.source_id)
        if now <= ev.start <= horizon:
            events.append(ev)
    log.info("canopy: %d events after filter", len(events))
    return events


def _parse_block(block: str, default_city_tag: str) -> Event | None:
    title_m = re.search(r'<span class="simcal-event-title"[^>]*>([^<]+)</span>', block)
    if not title_m:
        return None
    title = html.unescape(title_m.group(1)).strip()

    start_m = re.search(
        r'itemprop="startDate" content="([^"]+)"',
        block,
    )
    end_m = re.search(
        r'itemprop="endDate" content="([^"]+)"',
        block,
    )
    if not start_m:
        return None
    try:
        start = dtparse.parse(start_m.group(1)).replace(tzinfo=None)
        end = dtparse.parse(end_m.group(1)).replace(tzinfo=None) if end_m else None
    except ValueError:
        return None

    # Location: multiple <meta itemprop="address"> or plain text
    addr_m = re.search(r'<meta itemprop="address" content="([^"]+)"', block)
    location = html.unescape(addr_m.group(1)).strip() if addr_m else ""

    # Description (may contain HTML)
    desc_m = re.search(
        r'<div class="simcal-event-description"[^>]*>(.*?)</div>',
        block, flags=re.DOTALL,
    )
    excerpt = ""
    if desc_m:
        excerpt = _clean_html(desc_m.group(1))

    description = f"{excerpt}\n\n{_AGE_NOTE}".strip() if excerpt else _AGE_NOTE

    tag = _tag_for(f"{title} {location}".lower(), default_city_tag)

    # Stable source_id: unix start + slugified title
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
    source_id = f"{int(start.timestamp())}-{slug}"

    return Event(
        source="canopy",
        source_id=source_id,
        city_tag=tag,
        title=title,
        start=start,
        end=end,
        location=location,
        description=description,
        ages="Family-friendly (kids w/parent)",
        registration=True,
        url=CALENDAR_URL,
        tz=TZ,
    )


def _clean_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).strip()
    if len(s) > 600:
        s = s[:600].rsplit(" ", 1)[0] + "…"
    return s


def _tag_for(haystack: str, default: str) -> str:
    for kw, tag in _CITY_KEYWORDS:
        if kw in haystack:
            return tag
    return default
