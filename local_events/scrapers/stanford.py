"""Stanford Athletics home-game ICS ingest.

Source: WMT Digital's public calendar API used by gostanford.com. The URL
below is Tim's category selection covering the sports he wants; category IDs
are per-sport filters — don't try to enumerate.

Home vs away detection: SUMMARY contains " vs. " for home, " at " for away.
Filter is a single-token check on SUMMARY. LOCATION is a redundant confirm.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from ..event import Event

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"

STANFORD_ICS_URL = (
    "https://api.calendar.wmt.digital/api/calendar/calendar.ics"
    "?username=stanford"
    "&category[]=407&category[]=410&category[]=411&category[]=412"
    "&category[]=413&category[]=416&category[]=417&category[]=418"
    "&category[]=420&category[]=421&category[]=425&category[]=426"
    "&category[]=430&category[]=431&category[]=432&category[]=433"
    "&category[]=434"
)

# Sport -> Stanford venue. Sport key is lowercased raw string from SUMMARY
# before the " - " separator (e.g. "women's soccer", "football"). Unknown
# sports fall back to "Stanford, CA".
_VENUES = {
    "football": "Stanford Stadium, Stanford, CA",
    "men's basketball": "Maples Pavilion, Stanford, CA",
    "women's basketball": "Maples Pavilion, Stanford, CA",
    "men's soccer": "Laird Q. Cagan Stadium, Stanford, CA",
    "women's soccer": "Laird Q. Cagan Stadium, Stanford, CA",
    "men's water polo": "Avery Aquatic Center, Stanford, CA",
    "women's water polo": "Avery Aquatic Center, Stanford, CA",
    "women's volleyball": "Maples Pavilion, Stanford, CA",
    "men's volleyball": "Maples Pavilion, Stanford, CA",
    "field hockey": "Varsity Turf (Maloney Field), Stanford, CA",
    "baseball": "Sunken Diamond, Stanford, CA",
    "softball": "Smith Family Stadium, Stanford, CA",
    "men's swimming": "Avery Aquatic Center, Stanford, CA",
    "women's swimming": "Avery Aquatic Center, Stanford, CA",
    "wrestling": "Maples Pavilion, Stanford, CA",
    "men's gymnastics": "Burnham Pavilion, Stanford, CA",
    "women's gymnastics": "Burnham Pavilion, Stanford, CA",
    "men's tennis": "Taube Family Tennis Center, Stanford, CA",
    "women's tennis": "Taube Family Tennis Center, Stanford, CA",
    "men's lacrosse": "Laird Q. Cagan Stadium, Stanford, CA",
    "women's lacrosse": "Laird Q. Cagan Stadium, Stanford, CA",
}

_BOXSCORE_RE = re.compile(r"https?://\S+")


def fetch(city_tag: str = "", lookahead_days: int = 90) -> list[Event]:
    now = datetime.now(ZoneInfo(TZ))
    horizon = now + timedelta(days=lookahead_days)

    with httpx.Client(
        headers={"User-Agent": "local-events-sync (personal, timmermerican@gmail.com)"},
        timeout=30,
    ) as client:
        r = client.get(STANFORD_ICS_URL)
        r.raise_for_status()
        cal = Calendar.from_ical(r.content)

    events: list[Event] = []
    for comp in cal.walk("VEVENT"):
        summary = str(comp.get("SUMMARY", ""))
        if " vs. " not in summary:
            continue

        start = comp.decoded("DTSTART")
        if not isinstance(start, datetime):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=ZoneInfo(TZ))
        start_local = start.astimezone(ZoneInfo(TZ))
        if start_local < now - timedelta(hours=6):
            continue
        if start_local > horizon:
            continue

        end_prop = comp.get("DTEND")
        end_local = None
        if end_prop is not None:
            end = end_prop.dt
            if isinstance(end, datetime):
                if end.tzinfo is None:
                    end = end.replace(tzinfo=ZoneInfo(TZ))
                end_local = end.astimezone(ZoneInfo(TZ))

        sport, opponent = _parse_summary(summary)
        title = _format_title(sport, opponent)
        location = _VENUES.get(sport.lower(), "Stanford, CA")

        raw_desc = str(comp.get("DESCRIPTION", "")).strip()
        boxscore_url = _extract_url(raw_desc)

        uid = str(comp.get("UID", "")).split("@")[0]
        events.append(
            Event(
                source="stanford",
                source_id=uid or f"{title}-{start_local.isoformat()}",
                city_tag=city_tag,
                title=title,
                start=start_local.replace(tzinfo=None),
                end=end_local.replace(tzinfo=None) if end_local else None,
                location=location,
                description=raw_desc,
                ages="All ages",
                registration=None,
                url=boxscore_url,
                tz=TZ,
            )
        )
    log.info("stanford: %d home-game events after filter", len(events))
    return events


def _parse_summary(summary: str) -> tuple[str, str]:
    """Split 'Women's Soccer -  Stanford vs. Pacific' -> ('Women's Soccer', 'Pacific')."""
    s = re.sub(r"\s+", " ", summary).strip()
    if " - " in s:
        sport, rest = s.split(" - ", 1)
        sport = sport.strip()
    else:
        sport, rest = "", s
    m = re.search(r"Stanford\s+vs\.\s+(.+)$", rest)
    opponent = m.group(1).strip() if m else rest.strip()
    return sport, opponent


def _format_title(sport: str, opponent: str) -> str:
    if sport:
        return f"Stanford vs. {opponent} [{sport}]"
    return f"Stanford vs. {opponent}"


def _extract_url(description: str) -> str:
    m = _BOXSCORE_RE.search(description)
    return m.group(0) if m else ""
