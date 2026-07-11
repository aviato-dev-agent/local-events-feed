"""Little Green a Plant Bar (Redwood City) — classes & events.

Squarespace site, no structured event API. Each event lives in a
`.sqs-html-content` block containing an `<h4>` title and one or more `<p>`
blocks with the description and a date/time line.

Common patterns observed:
    "July 8th date moved to July 15th"
    "July 19th   3pm-6pm"
    "July 22nd   5:30-8:30"
    "Wednesday Afternoons   5:15pm"  (recurring — skipped)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from ..event import Event

log = logging.getLogger(__name__)

INDEX_URL = "https://www.littlegreenaplantbar.com/classes"
LOCATION = "Little Green a Plant Bar, 1101 Main St, Redwood City, CA 94063"
TZ = "America/Los_Angeles"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "July 8th", "July 15", "August 3rd"
_DATE_RE = re.compile(
    r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)

# "5:15pm", "3pm-6pm", "5:30-8:30", "3pm - 6pm"
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|–|—|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
    re.IGNORECASE,
)
_TIME_SINGLE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)

# Titles that indicate recurring/undated info blocks we can't extract from
_SKIP_TITLE_TOKENS = (
    "stay tuned",
    "coming soon",
)

# Text tokens that mark recurring events without concrete dates
_RECURRING_TOKENS = (
    "wednesday afternoons",
    "every third sunday",
    "every friday",
    "every saturday",
    "every sunday",
    "monthly",
    "weekly",
)


def fetch(city_tag: str = "RWC", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    horizon = datetime.now() + timedelta(days=lookahead_days)
    today = datetime.now()

    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
            r = client.get(INDEX_URL)
            r.raise_for_status()
            html_text = r.text
    except Exception as exc:
        log.warning("littlegreen: fetch failed: %s", exc)
        return events

    soup = BeautifulSoup(html_text, "html.parser")

    for block in soup.select(".sqs-html-content"):
        h4 = block.find("h4")
        if not h4:
            continue
        title = h4.get_text(" ", strip=True)
        if not title or _skip_title(title):
            continue

        body_text = block.get_text(" ", strip=True)
        low = body_text.lower()

        # Skip recurring events without a concrete upcoming date
        if any(tok in low for tok in _RECURRING_TOKENS) and _DATE_RE.search(body_text) is None:
            continue

        # Use the LAST date match in the block (handles "July 8th date moved to July 15th")
        matches = list(_DATE_RE.finditer(body_text))
        if not matches:
            continue

        for date_m in matches:
            month = _MONTHS.get(date_m.group(1).lower())
            if not month:
                continue
            try:
                day = int(date_m.group(2))
            except ValueError:
                continue

            # Look for time within 80 chars of the date match
            window = body_text[date_m.end():date_m.end() + 80]
            start_time, end_time = _parse_time(window)

            year = _pick_year(month, day, today)
            try:
                start = datetime(year, month, day, *start_time)
            except ValueError:
                continue
            if start < today - timedelta(hours=6) or start > horizon:
                continue

            end = None
            if end_time:
                try:
                    end = datetime(year, month, day, *end_time)
                    if end <= start:
                        end += timedelta(days=1)
                except ValueError:
                    end = None

            events.append(
                Event(
                    source="littlegreen",
                    source_id=f"lg-{_slug(title)}-{start.strftime('%Y%m%d')}",
                    city_tag=city_tag,
                    title=title,
                    start=start,
                    end=end,
                    location=LOCATION,
                    description=_short(body_text),
                    ages="All ages",
                    registration=None,
                    url=INDEX_URL,
                    tz=TZ,
                )
            )

    # Dedupe (title, start) — the "date moved" case creates two matches
    seen: set[tuple] = set()
    unique: list[Event] = []
    for e in events:
        # Prefer the LATER date when the title matches (accounts for "moved to X")
        key = (e.title, e.city_tag)
        # Just keep both for now; normalizer dedupes by (title, start)
        unique.append(e)

    log.info("littlegreen: %d events after filter", len(unique))
    return unique


def _parse_time(text: str) -> tuple[tuple[int, int], tuple[int, int] | None]:
    """Return ((start_h, start_m), (end_h, end_m) | None). Default 17:00 if none."""
    m = _TIME_RANGE_RE.search(text)
    if m:
        end_ampm = m.group(6)
        # "5:30-8:30" (no am/pm on start): inherit from end
        start_ampm = m.group(3) or end_ampm
        sh = _to24(int(m.group(1)), start_ampm)
        sm = int(m.group(2) or 0)
        eh = _to24(int(m.group(4)), end_ampm)
        em = int(m.group(5) or 0)
        # If start > end after conversion (e.g. "5:30-8:30pm" both pm → 17:30-20:30, fine).
        # But "10-2pm" → 10am-2pm; our logic already handles because start_ampm falls back to pm.
        # Fix that special case: if start_ampm was inherited and start > 12 vs end wrap
        if not m.group(3) and end_ampm.lower().startswith("p") and int(m.group(1)) > int(m.group(4)):
            # e.g. "10-2pm": start=10 (inherited pm becomes 22), end=14 → bad.
            sh -= 12  # treat start as AM
        return (sh, sm), (eh, em)

    m = _TIME_SINGLE_RE.search(text)
    if m:
        sh = _to24(int(m.group(1)), m.group(3))
        sm = int(m.group(2) or 0)
        return (sh, sm), None

    return (17, 0), None  # sensible default for evening classes at Little Green


def _to24(hour: int, ampm: str) -> int:
    ampm = ampm.lower().replace(".", "")
    if ampm.startswith("p") and hour != 12:
        return hour + 12
    if ampm.startswith("a") and hour == 12:
        return 0
    return hour


def _pick_year(month: int, day: int, ref: datetime) -> int:
    candidate = datetime(ref.year, month, day) if _valid(ref.year, month, day) else None
    if candidate and candidate >= ref - timedelta(days=30):
        return ref.year
    return ref.year + 1


def _valid(y: int, m: int, d: int) -> bool:
    try:
        datetime(y, m, d)
        return True
    except ValueError:
        return False


def _skip_title(title: str) -> bool:
    low = title.lower()
    return any(t in low for t in _SKIP_TITLE_TOKENS)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def _short(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 600:
        s = s[:600].rsplit(" ", 1)[0] + "…"
    return s
