"""Common Event dataclass shared across scrapers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    source: str          # scraper id, e.g. "smcl"
    source_id: str       # stable per-source unique id (used for UID)
    city_tag: str        # e.g. "RWC", "SM", "MP"
    title: str
    start: datetime      # naive local, wall-clock time
    end: Optional[datetime]
    location: str
    description: str
    ages: str            # human-readable age range e.g. "6-11"
    registration: Optional[bool]
    url: str
    tz: str = "America/Los_Angeles"

    def uid(self) -> str:
        return f"{self.source}-{self.source_id}@local-events"


import re as _re

# Word-boundary regexes to avoid substring matches (e.g. "habitat" in
# an educational description about "animal habitats" is NOT a volunteer event).
# Kept intentionally narrow — a source can override with is_volunteer_source=True.
_VOLUNTEER_PATTERNS = tuple(
    _re.compile(rf"\b{p}\b", _re.IGNORECASE) for p in (
        r"volunteers?",
        r"volunteering",
        r"planting",
        r"workday",
        r"clean[- ]?up",
        r"stewardship",
        r"trail\s+(?:work|crew|day)",
        r"community\s+service",
        r"service\s+learning",
    )
)


def is_volunteer_event(e: Event, source_is_volunteer: bool = False) -> bool:
    if source_is_volunteer:
        return True
    hay = f"{e.title} {e.description or ''}"
    return any(p.search(hay) for p in _VOLUNTEER_PATTERNS)


def is_sports_event(e: Event, source_is_sports: bool = False) -> bool:
    return source_is_sports


def is_adult_event(e: Event, source_is_adult: bool = False) -> bool:
    if source_is_adult:
        return True
    if "adult program" in e.ages.lower():
        return True
    return False
