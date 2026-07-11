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


_VOLUNTEER_KEYWORDS = (
    "volunteer", "planting", "workday", "cleanup", "clean-up", "clean up",
    "stewardship", "restoration", "habitat", "trail work", "community service",
)


def is_volunteer_event(e: Event, source_is_volunteer: bool = False) -> bool:
    if source_is_volunteer:
        return True
    hay = f"{e.title} {e.description or ''}".lower()
    return any(k in hay for k in _VOLUNTEER_KEYWORDS)
