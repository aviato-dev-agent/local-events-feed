"""San Mateo Public Library (city library) LibCal ICS ingest.

LibCal exposes a native ICS subscribe URL. We fetch, parse with `icalendar`, and
convert to our internal Event schema.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx
from icalendar import Calendar

from ..event import Event

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"


def fetch(ics_urls: list[str], city_tag: str, lookahead_days: int = 90) -> list[Event]:
    horizon = datetime.now(timezone.utc) + timedelta(days=lookahead_days)
    events: list[Event] = []
    with httpx.Client(
        headers={"User-Agent": "local-events-sync (personal, timmermerican@gmail.com)"},
        timeout=30,
    ) as client:
        for url in ics_urls:
            r = client.get(url)
            r.raise_for_status()
            cal = Calendar.from_ical(r.text)
            for comp in cal.walk("VEVENT"):
                start = comp.get("DTSTART").dt
                if isinstance(start, datetime):
                    start_dt = start
                else:
                    start_dt = datetime.combine(start, datetime.min.time())
                # Normalize to UTC for horizon check
                if start_dt.tzinfo is None:
                    start_dt_utc = start_dt.replace(tzinfo=timezone.utc)
                else:
                    start_dt_utc = start_dt.astimezone(timezone.utc)
                if start_dt_utc > horizon:
                    continue
                if start_dt_utc < datetime.now(timezone.utc) - timedelta(hours=6):
                    continue

                end_prop = comp.get("DTEND")
                end_dt = end_prop.dt if end_prop else None
                if isinstance(end_dt, datetime) is False and end_dt is not None:
                    end_dt = datetime.combine(end_dt, datetime.min.time())

                uid = str(comp.get("UID", ""))
                url_prop = comp.get("URL")
                categories = comp.get("CATEGORIES")
                cat_text = str(categories) if categories else ""

                title = str(comp.get("SUMMARY", "")).strip()
                desc = str(comp.get("DESCRIPTION", ""))
                if _is_adult_only(title, cat_text):
                    continue
                if _is_under_six(title, desc, cat_text):
                    continue

                events.append(
                    Event(
                        source="sanmateopl",
                        source_id=uid or f"{title}-{start_dt.isoformat()}",
                        city_tag=city_tag,
                        title=title,
                        start=start_dt,
                        end=end_dt if isinstance(end_dt, datetime) else None,
                        location=str(comp.get("LOCATION", "")).strip(),
                        description=str(comp.get("DESCRIPTION", "")).strip(),
                        ages=_extract_ages(title, str(comp.get("DESCRIPTION", ""))),
                        registration=None,
                        url=str(url_prop) if url_prop else "",
                        tz=TZ,
                    )
                )
    log.info("sanmateopl: %d events after filter", len(events))
    return events


ADULT_TOKENS = ("adult", "18+", "21+", "seniors only", "grown-up book club")

# Tokens that strongly imply the event's audience minimum is <6 years old.
UNDER_SIX_TOKENS = (
    "baby",
    "babies",
    "lapsit",
    "toddler",
    "preschool",         # covers "preschooler", "preschoolers"
    "pre-school",
    "prek",
    "pre-k",
    "0-5",
    "0 to 5",
    "birth to",
    "under 5",
    "under 6",
)


def _is_adult_only(title: str, categories: str) -> bool:
    hay = f"{title} {categories}".lower()
    if any(t in hay for t in ADULT_TOKENS):
        # allow "family" or "all ages" to override
        if "family" in hay or "all ages" in hay or "kids" in hay or "children" in hay:
            return False
        return True
    return False


def _is_under_six(title: str, description: str, categories: str) -> bool:
    """Exclude events whose minimum audience age is <6.

    Uses token match against title/description/categories AND explicit
    numeric-age patterns like "Ages 0-5", "ages 3-5", "ages 4 and up".
    """
    import re
    hay = f"{title}\n{description}\n{categories}".lower()

    # Token-based match (baby, toddler, preschool, etc.)
    if any(t in hay for t in UNDER_SIX_TOKENS):
        return True

    # Numeric age range "Ages 0-5" / "ages 2-5" — exclude if lower bound <6
    m = re.search(r"ages?\s+(\d+)\s*[-–]\s*(\d+)", hay)
    if m and int(m.group(1)) < 6:
        return True

    # "Ages 3 and up" / "ages 4+" — exclude if starting age <6
    m = re.search(r"ages?\s+(\d+)\s*(?:and up|\+)", hay)
    if m and int(m.group(1)) < 6:
        return True

    # Grades starting at K or PreK
    if re.search(r"grades?\s+(prek|pre-k|k)\b", hay):
        return True

    return False


def _extract_ages(title: str, description: str) -> str:
    import re
    hay = f"{title}\n{description}"
    # Common patterns: "Ages 6-10", "for ages 4 and up", "Grades K-5"
    m = re.search(r"[Aa]ges?\s+(\d+)\s*[-–]\s*(\d+)", hay)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"[Aa]ges?\s+(\d+)\s*(?:and up|\+)", hay)
    if m:
        return f"{m.group(1)}+"
    m = re.search(r"[Gg]rades?\s+([Kk0-9]+)\s*[-–]\s*(\d+)", hay)
    if m:
        return f"grades {m.group(1)}-{m.group(2)}"
    if "all ages" in hay.lower() or "family" in hay.lower():
        return "All ages / family"
    return "unspecified"
