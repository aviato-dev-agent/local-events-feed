"""Stanford d.school (Hasso Plattner Institute of Design) Events.

Scrapes dschool.stanford.edu/connect/events — workshops, guest lectures, etc.
No API or ICS feed available; HTML scraping required.

Title format: [d.school] Event Title
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from ..event import Event, is_public_event

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"
DSCHOOL_URL = "https://dschool.stanford.edu/connect/events"
UA = "local-events-sync (personal, timmermerican@gmail.com)"


def _parse_date_range(date_str: str, year: int = 2026) -> list[datetime]:
    """Parse d.school date ranges like 'August 11, 2026' or 'Sept 8-11, 2026'.

    Returns list of datetime objects (naive, local time).
    """
    if not date_str:
        return []

    date_str = date_str.strip().rstrip(',')  # Remove trailing comma

    # Normalize month names for consistent parsing
    month_map = {
        'September': 'Sep', 'Sept': 'Sep',
        'January': 'Jan', 'February': 'Feb', 'March': 'Mar', 'April': 'Apr',
        'May': 'May', 'June': 'Jun', 'July': 'Jul', 'August': 'Aug',
        'October': 'Oct', 'November': 'Nov', 'December': 'Dec',
    }
    for full, abbr in month_map.items():
        date_str = re.sub(rf'\b{full}\b', abbr, date_str)

    # Try to extract year if present
    year_match = re.search(r'\b(202[0-9])\b', date_str)
    if year_match:
        year = int(year_match.group(1))

    # Pattern: "Month Day-Day" or "Month Day"
    # E.g. "Sep 8-11" or "August 11"

    # Try range first (e.g., "Sep 8-11")
    range_match = re.match(r'^(\w+)\s+(\d+)\s*-\s*(\d+)', date_str)
    if range_match:
        month_str, start_day, end_day = range_match.groups()
        start_day, end_day = int(start_day), int(end_day)

        # Try both abbreviated and full month names
        for fmt in ('%b %d %Y', '%B %d %Y'):
            try:
                start_dt = datetime.strptime(f'{month_str} {start_day} {year}', fmt)
                start_dt = start_dt.replace(tzinfo=ZoneInfo(TZ))
                results = []
                for i in range(end_day - start_day + 1):
                    results.append((start_dt + timedelta(days=i)).replace(tzinfo=None))
                return results
            except ValueError:
                continue

    # Try single date (e.g., "August 11" or "Sep 8")
    single_match = re.match(r'^(\w+)\s+(\d+)', date_str)
    if single_match:
        month_str, day = single_match.groups()

        # Try both abbreviated and full month names
        for fmt in ('%b %d %Y', '%B %d %Y'):
            try:
                dt = datetime.strptime(f'{month_str} {day} {year}', fmt)
                dt = dt.replace(tzinfo=ZoneInfo(TZ))
                return [dt.replace(tzinfo=None)]
            except ValueError:
                continue

    log.debug("Could not parse date: %s (tried year %d)", date_str, year)
    return []


def fetch(city_tag: str = "", lookahead_days: int = 90) -> list[Event]:
    """Fetch d.school events from public website."""
    now = datetime.now(ZoneInfo(TZ))
    horizon = now + timedelta(days=lookahead_days)

    try:
        r = httpx.get(DSCHOOL_URL, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
    except Exception as exc:
        log.exception("dschool: fetch failed: %s", exc)
        return []

    try:
        soup = BeautifulSoup(r.content, 'html.parser')
    except Exception as exc:
        log.warning("dschool: parse failed: %s", exc)
        return []

    events: list[Event] = []
    seen_titles = set()

    # d.school uses c-card__inner-wrapper divs for event cards
    event_containers = soup.find_all('div', class_='c-card__inner-wrapper')

    if not event_containers:
        log.warning("dschool: no event cards found; page structure may have changed")
        return events

    for container in event_containers:
        try:
            text = container.get_text(strip=True)

            # Extract title from h3
            title_elem = container.find('h3')
            title = title_elem.get_text(strip=True) if title_elem else None

            if not title or title in seen_titles:
                continue
            seen_titles.add(title)

            # Extract date (appears after title in the card text)
            # Format: "TitleDateTypeLocation" (no spacing in HTML extraction)
            # Look for month names followed by day(s), handling cases with no space
            date_pattern = r'((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\s+\d+(?:\s*-\s*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\s+)?\d+)?(?:\s*,?\s*202[0-9])?)'
            date_match = re.search(date_pattern, text)
            date_str = date_match.group(1) if date_match else None

            if not date_str:
                continue

            # Parse dates to individual instances
            dates = _parse_date_range(date_str)
            if not dates:
                continue

            # Extract event type and location from remaining text
            # They appear as separate items in the card (e.g., "Guest Lecture", "Online")
            event_type = "Workshop" if "workshop" in text.lower() else "Event"
            location = "On Campus" if "on campus" in text.lower() else "Online" if "online" in text.lower() else "TBA"

            # Extract URL (look for links in the card)
            link_elem = container.find('a', href=True)
            url = link_elem['href'] if link_elem else ""
            if url and not url.startswith('http'):
                url = f"https://dschool.stanford.edu{url}" if url.startswith('/') else f"https://dschool.stanford.edu/{url}"

            # Use truncated card text as description
            description = text[:500]

            # Create event instances for each date
            for start_dt in dates:
                # Skip events outside lookahead window
                if start_dt.date() < (now - timedelta(hours=6)).date() or start_dt.date() > horizon.date():
                    continue

                event = Event(
                    source="dschool",
                    source_id=f"dschool-{title}-{start_dt.isoformat()}",
                    city_tag="",
                    title=f"[d.school] {title}",
                    start=start_dt,
                    end=None,
                    location=location,
                    description=description,
                    ages="All ages",
                    registration=None,
                    url=url,
                    tz=TZ,
                )

                # Filter to public events
                if is_public_event(event):
                    events.append(event)

        except Exception as exc:
            log.warning("dschool: error parsing event: %s", exc)
            continue

    log.info("dschool: %d public events", len(events))
    return events
