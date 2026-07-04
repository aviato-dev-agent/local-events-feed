"""Menlo Park Library & Community Services events (Granicus CMS).

Scrapes the Community-events landing page which lists ~12 upcoming items.
Filters out adult-only and under-6 events using the same heuristics as
sanmateopl.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..event import Event
from .sanmateopl import _is_under_six

log = logging.getLogger(__name__)

BASE = "https://www.menlopark.gov"
URLS = [
    "https://www.menlopark.gov/Government/Departments/Library-and-Community-Services/Events",
    "https://www.menlopark.gov/Government/Departments/Library-and-Community-Services/Events/Community-events",
]
TZ = "America/Los_Angeles"
UA = "Mozilla/5.0 (compatible; local-events-sync/1.0; +https://github.com/aviato-dev-agent/local-events-feed)"

# URL path fragments that indicate an adult-targeted event
ADULT_PATH_HINTS = ("Events-for-adults",)


def fetch(city_tag: str = "MP", lookahead_days: int = 90) -> list[Event]:
    events: list[Event] = []
    seen_hrefs: set[str] = set()
    horizon = datetime.now() + timedelta(days=lookahead_days)

    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for url in URLS:
            try:
                r = client.get(url)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("menlopark: fetch failed for %s: %s", url, exc)
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            for item in soup.select(".list-item-container"):
                title_el = item.select_one(".list-item-title")
                date_el = item.select_one(".list-item-block-date")
                desc_el = item.select_one(".list-item-block-desc")
                addr_el = item.select_one(".list-item-address")
                if not title_el or not date_el:
                    continue

                title = title_el.get_text(strip=True)
                a = item.find("a", href=True)
                if not a:
                    continue
                href = urljoin(BASE, a["href"])
                if href in seen_hrefs:
                    continue

                # Skip adult-targeted event pages by URL hint
                if any(hint in href for hint in ADULT_PATH_HINTS):
                    continue

                date_text = date_el.get_text(" ", strip=True)
                start = _parse_date(date_text)
                if not start:
                    continue
                if start > horizon or start < datetime.now() - timedelta(days=1):
                    continue

                desc = desc_el.get_text(" ", strip=True) if desc_el else ""
                location = addr_el.get_text(" ", strip=True) if addr_el else "Menlo Park"

                if _is_closure(title, desc):
                    continue
                if _is_under_six(title, desc, ""):
                    continue
                if _is_adult_only(title, desc):
                    continue

                seen_hrefs.add(href)
                events.append(
                    Event(
                        source="menlopark",
                        source_id=_uid_from_href(href),
                        city_tag=city_tag,
                        title=title,
                        start=start,
                        end=None,  # rarely stated; normalizer defaults to 1h
                        location=location,
                        description=desc,
                        ages=_infer_ages(title, desc, href),
                        registration=None,
                        url=href,
                        tz=TZ,
                    )
                )

    log.info("menlopark: %d events after filter", len(events))
    return events


DATE_PATTERNS = [
    # "04 Jul 2026"
    (re.compile(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})"), "%d %b %Y"),
    # "July 4, 2026"
    (re.compile(r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})"), "%B %d %Y"),
]


def _parse_date(text: str):
    for pattern, fmt in DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            try:
                if fmt == "%d %b %Y":
                    return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
                return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
            except ValueError:
                continue
    return None


def _uid_from_href(href: str) -> str:
    # trailing path segment is usually the date-slug event id
    tail = href.rstrip("/").rsplit("/", 1)[-1]
    return tail or href


def _infer_ages(title: str, description: str, href: str) -> str:
    hay = f"{title} {description} {href}".lower()
    if "events-for-children" in hay or "children" in hay or "kids" in hay:
        return "children"
    if "events-for-teens" in hay or "teens" in hay:
        return "teens"
    if "family" in hay or "community" in hay or "all ages" in hay:
        return "All ages / family"
    return "unspecified"


CLOSURE_TOKENS = ("offices closed", "closure:", "closed:", "holiday - administrative", "library closed")


def _is_closure(title: str, description: str) -> bool:
    hay = f"{title} {description}".lower()
    return any(t in hay for t in CLOSURE_TOKENS)


ADULT_TOKENS = ("adult book club", "grown-up", " 18+", " 21+", "seniors only")


def _is_adult_only(title: str, description: str) -> bool:
    hay = f"{title} {description}".lower()
    if any(t in hay for t in ADULT_TOKENS):
        if "family" in hay or "kids" in hay or "children" in hay or "all ages" in hay:
            return False
        return True
    return False
