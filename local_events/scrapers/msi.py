"""Marine Science Institute (Redwood City) — public boat trips.

MSI runs Wix Bookings for their public program registration. The frontend
"View Available Dates and Times" button fetches slot data from Wix's internal
`/_api/wix-bookings-*` endpoints, but these endpoints require an authenticated
app instance token that's only issued to a real browser session.

Building this scraper requires either:
  (a) Reverse-engineering the Wix auth handshake (fragile, breaks with any
      Wix Bookings update), or
  (b) Running a headless browser via scrape.do render=true (uses credits, and
      the user asked to hold scrape.do additions this session).

For now this scraper is a stub: it verifies the site is reachable and returns
an empty list. Once we have a plan for (a) or (b), the fetch() body gets its
real implementation.
"""
from __future__ import annotations

import logging

import httpx

from ..event import Event

log = logging.getLogger(__name__)

PUBLIC_EVENTS_URL = "https://www.sfbaymsi.org/public-events"
LOCATION = "Marine Science Institute, 500 Discovery Pkwy, Redwood City, CA 94063"
TZ = "America/Los_Angeles"
UA = "local-events-sync (personal, timmermerican@gmail.com)"


def fetch(city_tag: str = "SM", lookahead_days: int = 90) -> list[Event]:
    """Stub — see module docstring."""
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=15, follow_redirects=True) as client:
            r = client.get(PUBLIC_EVENTS_URL)
            r.raise_for_status()
    except Exception as exc:
        log.warning("msi: page fetch failed: %s", exc)
        return []

    log.info(
        "msi: 0 events (stub — Wix Bookings API requires auth handshake, "
        "see module docstring for followup)"
    )
    return []
