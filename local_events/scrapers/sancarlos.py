"""San Carlos city events via Revize calendar JSON API.

The calendar page (cityofsancarlos.org/calendar.php) uses FullCalendar.js
which loads events from a data handler endpoint. That endpoint returns a flat
JSON array of all events — no pagination, full date range.

API endpoint (discovered from index.js):
  GET /_{assets}_/plugins/revizeCalendar/calendar_data_handler.php
      ?webspace=sancarlos&relative_revize_url=//cms3.revize.com/&protocol=https:
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import datetime, timedelta

import httpx

from ..event import Event
from .sanmateopl import _is_under_six

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"
UA = "Mozilla/5.0 (compatible; local-events-sync/1.0; +https://github.com/aviato-dev-agent/local-events-feed)"

API_URL = (
    "https://www.cityofsancarlos.org/_assets_/plugins/revizeCalendar/"
    "calendar_data_handler.php"
    "?webspace=sancarlos&relative_revize_url=//cms3.revize.com/&protocol=https:"
)

# Calendar IDs to include (from calendarProps in the page JS)
INCLUDE_CALENDAR_IDS = {"1", "2", "29"}  # City Events, Parks & Rec, City Centennial
EXCLUDE_CALENDAR_NAMES = {"meetings", "intranet"}

ADULT_TOKENS = ("adult", " 18+", " 21+", "seniors only", "grown-up")
ADULT_ALLOW = ("family", "all ages", "kids", "children")
CLOSURE_TOKENS = ("offices closed", "closed:", "holiday", "library closed")
MEETING_TOKENS = ("city council", "planning commission", "board of", "commission meeting", "public hearing")


def fetch(city_tag: str = "SC", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    now = datetime.now()
    horizon = now + timedelta(days=lookahead_days)

    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        try:
            r = client.get(API_URL)
            r.raise_for_status()
            raw = r.json()
        except Exception as exc:
            log.warning("sancarlos: API fetch failed: %s", exc)
            return events

    if not isinstance(raw, list):
        log.warning("sancarlos: unexpected API response type: %s", type(raw))
        return events

    for item in raw:
        cal_ids = set(item.get("calendar_displays") or [])
        cal_name = (item.get("primary_calendar_name") or "").strip().lower()

        if not cal_ids.intersection(INCLUDE_CALENDAR_IDS):
            continue
        if cal_name in EXCLUDE_CALENDAR_NAMES:
            continue

        title = (item.get("title") or "").strip()
        if not title:
            continue

        start_str = item.get("start") or ""
        end_str = item.get("end") or ""
        try:
            start = datetime.fromisoformat(start_str)
        except (ValueError, TypeError):
            continue

        if start < now - timedelta(hours=6) or start > horizon:
            continue

        end = None
        if end_str:
            try:
                end = datetime.fromisoformat(end_str)
            except (ValueError, TypeError):
                pass

        desc_raw = item.get("desc") or ""
        desc = _clean_desc(desc_raw)
        location = (item.get("location") or "San Carlos").strip()
        url = (item.get("url") or "https://www.cityofsancarlos.org/calendar.php").strip()
        source_id = str(item.get("id") or item.get("rid") or "")

        if _is_meeting(title):
            continue
        if _is_closure(title):
            continue
        if _is_under_six(title, desc, ""):
            continue
        if _is_adult_only(title, desc):
            continue

        events.append(
            Event(
                source="sancarlos",
                source_id=source_id,
                city_tag=city_tag,
                title=title,
                start=start,
                end=end,
                location=location or "San Carlos",
                description=desc,
                ages="All ages",
                registration=None,
                url=url,
                tz=TZ,
            )
        )

    log.info("sancarlos: %d events after filter", len(events))
    return events


def _clean_desc(raw: str) -> str:
    if not raw:
        return ""
    try:
        text = urllib.parse.unquote(raw)
    except Exception:
        text = raw
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800]


def _is_meeting(title: str) -> bool:
    low = title.lower()
    return any(t in low for t in MEETING_TOKENS)


def _is_closure(title: str) -> bool:
    return any(t in title.lower() for t in CLOSURE_TOKENS)


def _is_adult_only(title: str, desc: str) -> bool:
    hay = f"{title} {desc}".lower()
    if any(t in hay for t in ADULT_TOKENS):
        return not any(x in hay for x in ADULT_ALLOW)
    return False
