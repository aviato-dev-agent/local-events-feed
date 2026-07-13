"""Grassroots Ecology — Peninsula habitat restoration workdays.

grassrootsecology.org/event-calendar is a Squarespace 7.x event list page.
Each event is an <article class="eventlist-event"> with structured
<time class="event-time-localized-start" datetime="..."> tags carrying the
full ISO local time. City tag is inferred from the venue string.

Ages: under-13 must be accompanied by adult; minor waiver required.
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

CALENDAR_URL = "https://www.grassrootsecology.org/event-calendar"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_AGE_NOTE = (
    "Grassroots Ecology has no minimum age; children under 13 must be "
    "accompanied by an adult and a minor waiver is required. Tools and "
    "gloves provided."
)

# Preserve → city tag mapping. First match wins on the venue/title string.
_PRESERVE_TAGS = (
    ("pearson-arastradero", "PA"),
    ("arastradero", "PA"),
    ("foothills nature preserve", "PA"),
    ("foothills preserve", "PA"),
    ("byxbee", "PA"),
    ("esther clark", "PA"),
    ("southgate", "PA"),
    ("bol park", "PA"),
    ("palo alto", "PA"),
    ("redwood grove", "LA"),  # Los Altos
    ("los altos", "LA"),
    ("redwood creek", "RWC"),
    ("stulsaft", "RWC"),
    ("redwood city", "RWC"),
    ("cooley landing", "EPA"),
    ("east palo alto", "EPA"),
    ("edgewood", "RWC"),
    ("menlo park", "MP"),
)


def fetch(city_tag: str = "PA", lookahead_days: int = 90) -> list[Event]:
    now = datetime.now() - timedelta(hours=6)
    horizon = datetime.now() + timedelta(days=lookahead_days)
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        r = client.get(CALENDAR_URL)
        r.raise_for_status()
        html_text = r.text

    events: list[Event] = []
    for block in re.findall(r'<article class="eventlist-event.*?</article>', html_text, flags=re.DOTALL):
        ev = _parse_block(block, city_tag)
        if ev and now <= ev.start <= horizon:
            events.append(ev)
    log.info("grassrootsecology: %d events after filter", len(events))
    return events


def _parse_block(block: str, default_city_tag: str) -> Event | None:
    # Title + URL
    title_m = re.search(
        r'<h[12] class="eventlist-title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>',
        block, flags=re.DOTALL,
    )
    if not title_m:
        return None
    href, title_raw = title_m.group(1), html.unescape(re.sub(r"<[^>]+>", "", title_m.group(2))).strip()
    url = href if href.startswith("http") else f"https://www.grassrootsecology.org{href}"

    # Start/end times (both have datetime attr with full ISO)
    start_m = re.search(
        r'<time class="event-time-localized-start" datetime="([^"]+)"',
        block,
    )
    end_m = re.search(
        r'<time class="event-time-localized-end" datetime="([^"]+)"',
        block,
    )
    if not start_m:
        # No localized-start attribute → time unknown. Skip rather than emit
        # a midnight-start event that clutters the calendar. If this fires
        # often, revisit by crawling the event detail page for a time.
        log.info("grassrootsecology: skipping %r — no start time on listing", title_raw)
        return None
    try:
        start_dt = dtparse.parse(start_m.group(1)).replace(tzinfo=None)
        end_dt = dtparse.parse(end_m.group(1)).replace(tzinfo=None) if end_m else None
    except ValueError:
        return None

    # Location
    loc_m = re.search(
        r'<li class="eventlist-meta-item eventlist-meta-address[^"]*"[^>]*>(.*?)</li>',
        block, flags=re.DOTALL,
    )
    if loc_m:
        location = html.unescape(re.sub(r"<[^>]+>", " ", loc_m.group(1))).strip()
        location = re.sub(r"\s+", " ", location)
    else:
        location = ""

    # Excerpt / description
    excerpt_m = re.search(
        r'<(?:div|p) class="eventlist-excerpt[^"]*"[^>]*>(.*?)</(?:div|p)>',
        block, flags=re.DOTALL,
    )
    excerpt = ""
    if excerpt_m:
        excerpt = html.unescape(re.sub(r"<[^>]+>", " ", excerpt_m.group(1))).strip()
        excerpt = re.sub(r"\s+", " ", excerpt)

    description = f"{excerpt}\n\n{_AGE_NOTE}".strip() if excerpt else _AGE_NOTE

    tag = _tag_for(f"{title_raw} {location}".lower(), default_city_tag)

    # source_id from URL slug is stable
    slug = href.rstrip("/").rsplit("/", 1)[-1]
    return Event(
        source="grassrootsecology",
        source_id=slug or f"{title_raw}-{start_dt.isoformat()}",
        city_tag=tag,
        title=title_raw,
        start=start_dt,
        end=end_dt,
        location=location,
        description=description,
        ages="All ages (under-13 with adult, minor waiver required)",
        registration=True,
        url=url,
        tz=TZ,
    )


def _tag_for(haystack: str, default: str) -> str:
    for kw, tag in _PRESERVE_TAGS:
        if kw in haystack:
            return tag
    return default
