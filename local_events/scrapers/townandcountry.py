"""Town & Country Village (Palo Alto) events via ma.to venue page.

ma.to is a Next.js discovery aggregator. Events are embedded in server-streamed
HTML payloads (`self.__next_f.push([1, "..."])`), NOT a REST API.

Currently the venue page reports "There are no events currently scheduled".
The scraper detects that message explicitly and returns []. Once events
populate, it extracts them by scanning the streaming payloads for
objects with title/start-time fields.
"""
from __future__ import annotations

import codecs
import logging
import re
from datetime import datetime, timedelta
from typing import Iterable

import httpx
from dateutil import parser as dtparse

from ..event import Event

log = logging.getLogger(__name__)

VENUE_URL = "https://ma.to/venue/townandcountryvillage"
LOCATION = "Town & Country Village, 855 El Camino Real, Palo Alto, CA 94301"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_PAYLOAD_RE = re.compile(
    r'self\.__next_f\.push\(\[1,"(.*?)"\]\)',
    re.DOTALL,
)

_EMPTY_MSG = "no events currently scheduled"


def fetch(city_tag: str = "PA", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    horizon = datetime.now() + timedelta(days=lookahead_days)
    today = datetime.now()

    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
            r = client.get(VENUE_URL)
            r.raise_for_status()
            html_text = r.text
    except Exception as exc:
        log.warning("townandcountry: fetch failed: %s", exc)
        return events

    combined = _combined_payload(html_text)
    if _EMPTY_MSG in combined.lower():
        log.info("townandcountry: venue reports no events currently scheduled")
        return events

    for ev in _extract_events(combined):
        title = (ev.get("title") or ev.get("name") or "").strip()
        raw_start = ev.get("startDate") or ev.get("start_time") or ev.get("date") or ev.get("startTime")
        if not title or not raw_start:
            continue
        try:
            start = dtparse.parse(raw_start)
        except (ValueError, TypeError):
            continue
        if start.tzinfo is not None:
            start = start.astimezone().replace(tzinfo=None)
        if start < today - timedelta(hours=6) or start > horizon:
            continue

        end = None
        raw_end = ev.get("endDate") or ev.get("end_time") or ev.get("endTime")
        if raw_end:
            try:
                end = dtparse.parse(raw_end)
                if end.tzinfo is not None:
                    end = end.astimezone().replace(tzinfo=None)
            except (ValueError, TypeError):
                end = None

        events.append(
            Event(
                source="townandcountry",
                source_id=str(ev.get("id") or ev.get("slug") or f"tc-{start.strftime('%Y%m%d%H%M')}"),
                city_tag=city_tag,
                title=title,
                start=start,
                end=end,
                location=LOCATION,
                description=(ev.get("description") or "").strip() or f"Source: {VENUE_URL}",
                ages="All ages",
                registration=None,
                url=ev.get("url") or VENUE_URL,
                tz=TZ,
            )
        )

    log.info("townandcountry: %d events after filter", len(events))
    return events


def _combined_payload(html_text: str) -> str:
    """Decode all Next.js streaming payloads and concatenate them."""
    out = []
    for m in _PAYLOAD_RE.finditer(html_text):
        raw = m.group(1)
        try:
            decoded = codecs.decode(raw, "unicode_escape", errors="ignore")
        except Exception:
            decoded = raw
        out.append(decoded)
    return "".join(out)


def _extract_events(combined: str) -> Iterable[dict]:
    """Yield event-shaped dicts found in the streamed JSON."""
    import json

    for m in re.finditer(r'\{[^{}]{0,3000}\}', combined):
        blob = m.group()
        if '"title"' not in blob and '"name"' not in blob:
            continue
        if not any(k in blob for k in ('"startDate"', '"start_time"', '"startTime"')):
            continue
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj
