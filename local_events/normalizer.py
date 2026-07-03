"""Normalize, dedupe, and enforce defaults across scraped events."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from .event import Event

log = logging.getLogger(__name__)

DEFAULT_DURATION = timedelta(hours=1)


def normalize(events: list[Event]) -> list[Event]:
    """Apply default duration + tag prefix + dedupe."""
    out: list[Event] = []
    for e in events:
        if e.end is None or e.end <= e.start:
            e.end = e.start + DEFAULT_DURATION
        if not e.title.startswith(f"[{e.city_tag}]"):
            e.title = f"[{e.city_tag}] {e.title}"
        out.append(e)
    return _dedupe(out)


def _dedupe(events: list[Event]) -> list[Event]:
    """Drop duplicates by (normalized_title, start rounded to 30min).

    Prefers the entry whose description is longest (assume more info).
    """
    buckets: dict[tuple, Event] = {}
    for e in events:
        key = (_norm_title(e.title), _bucket_time(e.start))
        prior = buckets.get(key)
        if prior is None or len(e.description) > len(prior.description):
            buckets[key] = e
    result = list(buckets.values())
    if len(result) < len(events):
        log.info("normalizer: deduped %d -> %d", len(events), len(result))
    return result


def _norm_title(t: str) -> str:
    # strip city tag prefix then lowercase alnum
    t = re.sub(r"^\[[A-Z]+\]\s*", "", t)
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _bucket_time(dt) -> str:
    minute = 30 if dt.minute >= 15 and dt.minute < 45 else 0
    if dt.minute >= 45:
        # round up to next hour
        return f"{dt.year}{dt.month:02d}{dt.day:02d}{(dt.hour + 1) % 24:02d}00"
    return f"{dt.year}{dt.month:02d}{dt.day:02d}{dt.hour:02d}{minute:02d}"
