"""SMCL BiblioCommons events scraper.

API: https://gateway.bibliocommons.com/v2/libraries/smcl/events
Returns paginated JSON with entities lookup for branches and audiences.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx
from dateutil import parser as dtparse

from ..event import Event

log = logging.getLogger(__name__)

API_URL = "https://gateway.bibliocommons.com/v2/libraries/smcl/events"
EVENT_PERMALINK = "https://smcl.bibliocommons.com/events/{event_id}"
PAGE_LIMIT = 100
TZ = "America/Los_Angeles"

# Audiences that qualify for a family/kids calendar (ages 5-13 window)
KID_AUDIENCES = {
    "Preschoolers (0-5)",   # 6yo may still enjoy edge cases
    "Children (6-11)",
    "Teens (12-18)",
    "All Ages",
}
ADULT_ONLY_AUDIENCES = {"Adults (19+)", "Adults (55+)"}


def fetch(branch_to_tag: dict[str, str], lookahead_days: int = 90) -> list[Event]:
    """Fetch SMCL events for the given branches, filtered to kid audiences."""
    branches = set(branch_to_tag.keys())
    horizon = datetime.now(timezone.utc) + timedelta(days=lookahead_days)
    events: list[Event] = []
    page = 1
    with httpx.Client(
        headers={"User-Agent": "local-events-sync (personal, timmermerican@gmail.com)"},
        timeout=30,
    ) as client:
        while True:
            r = client.get(API_URL, params={"limit": PAGE_LIMIT, "page": page})
            r.raise_for_status()
            data = r.json()
            ents = data["entities"]
            branch_lookup = {k: v.get("name") for k, v in ents.get("locations", {}).items()}
            audience_lookup = {k: v.get("name") for k, v in ents.get("eventAudiences", {}).items()}

            for ev_id, ev in ents["events"].items():
                d0 = ev.get("definition") or {}
                if d0.get("isCancelled"):
                    continue
                branch_name = branch_lookup.get(d0.get("branchLocationId"))
                if branch_name not in branches:
                    continue
                audience_names = {audience_lookup.get(a) for a in d0.get("audienceIds") or []}
                if not audience_names & KID_AUDIENCES:
                    continue
                if audience_names and audience_names.issubset(ADULT_ONLY_AUDIENCES):
                    continue

                try:
                    start_local = dtparse.parse(d0["start"])
                except (KeyError, ValueError):
                    continue
                end_raw = d0.get("end")
                end_local = dtparse.parse(end_raw) if end_raw else None

                # start_local is naive local (America/Los_Angeles wall time)
                if start_local > horizon.replace(tzinfo=None):
                    continue
                if start_local < datetime.now().replace(microsecond=0) - timedelta(hours=6):
                    continue

                ages = _pick_age_range(audience_names)
                events.append(
                    Event(
                        source="smcl",
                        source_id=ev_id,
                        city_tag=branch_to_tag[branch_name],
                        title=d0.get("title", "").strip(),
                        start=start_local,
                        end=end_local,
                        location=branch_name,
                        description=_strip_html(d0.get("description") or ""),
                        ages=ages,
                        registration=bool(d0.get("registrationInfo", {}).get("cap")),
                        url=EVENT_PERMALINK.format(event_id=ev_id),
                        tz=TZ,
                    )
                )

            pagination = data["events"]["pagination"]
            if page >= pagination["pages"]:
                break
            page += 1
    log.info("smcl: %d events after filter", len(events))
    return events


def _pick_age_range(audience_names: set[str]) -> str:
    parts = []
    if "Preschoolers (0-5)" in audience_names:
        parts.append("0-5")
    if "Children (6-11)" in audience_names:
        parts.append("6-11")
    if "Teens (12-18)" in audience_names:
        parts.append("12-18")
    if "All Ages" in audience_names and not parts:
        return "All ages"
    return ", ".join(parts) or "unspecified"


def _strip_html(s: str) -> str:
    from html import unescape
    import re
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return unescape(s).strip()
