"""Shared utilities for event scrapers — logging, error tracking, fallback selectors."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class ScraperErrorTracker:
    """Track and report errors during a scraper run."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.parse_errors = 0
        self.date_parse_failures = 0
        self.missing_fields = 0
        self.http_errors = 0

    def log_parse_error(self, item_id: str = "", exc: Exception | None = None):
        """Log and track a parsing error for an event."""
        self.parse_errors += 1
        if exc:
            log.debug("%s: parse error for %s: %s", self.source_name, item_id[:50], exc)
        else:
            log.debug("%s: parse error for %s", self.source_name, item_id[:50])

    def log_date_parse_failure(self, date_str: str, item_id: str = ""):
        """Log and track a date parsing failure."""
        self.date_parse_failures += 1
        log.debug("%s: failed to parse date '%s' for %s", self.source_name, date_str, item_id[:50])

    def log_missing_field(self, field_name: str, item_id: str = ""):
        """Log and track a missing required field."""
        self.missing_fields += 1
        log.debug("%s: missing %s for %s", self.source_name, field_name, item_id[:50])

    def log_http_error(self, url: str, exc: Exception | None = None):
        """Log and track an HTTP error."""
        self.http_errors += 1
        if exc:
            log.warning("%s: fetch failed for %s: %s", self.source_name, url, exc)
        else:
            log.warning("%s: fetch failed for %s", self.source_name, url)

    def summary(self, event_count: int, container_count: int | None = None):
        """Log summary with error counters."""
        if container_count is not None:
            if self.parse_errors or self.date_parse_failures:
                log.info(
                    "%s: %d public events (%d parse errors, %d date failures out of %d containers)",
                    self.source_name,
                    event_count,
                    self.parse_errors,
                    self.date_parse_failures,
                    container_count,
                )
            else:
                log.info("%s: %d public events from %d containers", self.source_name, event_count, container_count)
        else:
            if self.parse_errors or self.date_parse_failures or self.http_errors:
                log.info(
                    "%s: %d events (%d parse errors, %d date failures, %d http errors)",
                    self.source_name,
                    event_count,
                    self.parse_errors,
                    self.date_parse_failures,
                    self.http_errors,
                )
            else:
                log.info("%s: %d events", self.source_name, event_count)


def find_elements(
    container: Any,
    selectors: list[tuple[str, dict]],
    fallback_check=None,
) -> list[Any]:
    """Find elements using primary selector, then fallback selectors if needed.

    Args:
        container: BeautifulSoup element to search within
        selectors: list of (find_method, kwargs) tuples in priority order
                  e.g. [("find_all", {"class_": "event-card"}), ("find_all", ["article"])]
        fallback_check: optional callable to validate fallback results

    Returns:
        List of found elements, or empty list if none found
    """
    from bs4 import BeautifulSoup

    elements = []

    # Try each selector in order
    for find_method, kwargs in selectors:
        if find_method == "find_all":
            if isinstance(kwargs, list):
                elements = container.find_all(kwargs)
            elif isinstance(kwargs, dict):
                elements = container.find_all(**kwargs)
        elif find_method == "find":
            if isinstance(kwargs, list):
                elements = container.find(kwargs)
            elif isinstance(kwargs, dict):
                elements = container.find(**kwargs)

        if elements:
            break

    # Apply fallback validation if elements found via fallback
    if elements and fallback_check and len(selectors) > 1:
        if isinstance(elements, list):
            elements = [e for e in elements if fallback_check(e)]
        elif not fallback_check(elements):
            elements = []

    return elements if isinstance(elements, list) else ([elements] if elements else [])


def check_page_health(soup: Any, source_name: str, min_chars: int = 100) -> bool:
    """Check if a parsed page appears to have actual content or is broken/empty.

    Returns True if page seems OK, False if it appears broken/empty.
    """
    try:
        body_text = soup.get_text(strip=True)
        if len(body_text) < min_chars:
            log.warning("%s: page appears empty or broken (< %d chars)", source_name, min_chars)
            return False
        return True
    except Exception as exc:
        log.warning("%s: error checking page health: %s", source_name, exc)
        return False
