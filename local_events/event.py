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


def is_stanford_event(e: Event, source_is_stanford: bool = False) -> bool:
    return source_is_stanford


_INTERNAL_ONLY_PATTERNS = tuple(
    _re.compile(rf"\b{p}\b", _re.IGNORECASE) for p in (
        r"m\s*&\s*m",  # morbidity & mortality rounds
        r"morbidity\s+mortality",
        r"staff\s+meeting",
        r"faculty\s+meeting",
        r"committee\s+meeting",
        r"department\s+meeting",
        r"team\s+meeting",
        r"standing\s+meeting",
        r"lab\s+meeting",
        r"board\s+meeting",
        r"retreat\s+for\s+staff",
        r"administrative\s+meeting",
        r"internal\s+(?:use|only)",
        r"conferral\s+of\s+degrees",
        r"recommending\s+lists?(?:\s+due)?",
        r"final\s+exam",
        r"degrees?\s+due",
        r"deadline",
        r"(?:is\s+)?(?:closed|closure)",
        r"office\s+closed",
        r"financial\s+counseling",  # employee/student benefit
        r"fidelity",  # retirement/financial benefits program
        r"hr\s+benefit",
        r"employee\s+benefit",
        r"payroll",
        r"benefits\s+enrollment",
        # Law school internal/student-only events
        r"pro\s+bono",  # law school internal career programming
        r"1l\s+(?:connect|job|career|search|class)",  # first-year law student specific
        r"2l|3l",  # second/third year law school
        r"levin\s+center",  # law school career center
        r"public\s+interest.*1l",  # public interest programming for 1L
        # Support groups & personal wellness
        r"alcoholics?\s+anonymous",
        r"aa\s+(?:meeting|group)",
        r"narcotics?\s+anonymous",
        r"na\s+(?:meeting|group)",
        r"support\s+group",
        # Faculty-only professional development
        r"faculty\s+competencies",  # faculty skills workshops
        r"faculty.*assessment",
        r"faculty.*development",
        r"faculty.*risk",  # faculty risk management
        r"risk\s+(?:management|review)\s+for\s+faculty",
        r"global\s+risk.*faculty",
    )
)


def is_public_event(e: Event) -> bool:
    """Include most Stanford events except purely internal admin meetings/deadlines.

    Includes: seminars, talks, exhibitions, tours, workshops, classes, trainings,
    volunteer opportunities, wellness programs, faculty development, etc.
    Excludes: internal staff meetings, admin deadlines, closures, M&M rounds.
    """
    hay = f"{e.title} {e.description or ''}".lower()

    # Exclude only obvious internal-only events
    if any(p.search(hay) for p in _INTERNAL_ONLY_PATTERNS):
        return False

    # Default: include (most Stanford events are worth listing)
    return True
