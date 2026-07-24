"""Stanford Campus Events — public talks, seminars, lectures, symposia, exhibitions.

Sources (in priority order):
1. Localist JSON API at events.stanford.edu — all departments, paginated
2. Stanford Law School ICS (outside Localist)
3. Stanford Economics seminar ICS feeds (outside Localist)

Title format: [School / Dept] Event Title
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from ..event import Event, is_public_event

log = logging.getLogger(__name__)

TZ = "America/Los_Angeles"
LOCALIST_API = "https://events.stanford.edu/api/2/events"
LAW_ICS_URL = "https://law.stanford.edu/events/ical/"
ECON_FEEDS_URL = "https://economics.stanford.edu/ical-feeds"
UA = "local-events-sync (personal, timmermerican@gmail.com)"

_ADMIN_RE = re.compile(
    r"\b(faculty\s+meeting|staff\s+meeting|committee\s+meeting|board\s+meeting|"
    r"department\s+meeting|team\s+meeting|standing\s+meeting|lab\s+meeting|"
    r"retreat\s+for\s+staff|administrative\s+meeting)\b",
    re.IGNORECASE,
)

_DEPT_ABBREVS: dict[str, str] = {
    "Stanford Graduate School of Business": "GSB",
    "Graduate School of Business": "GSB",
    "School of Engineering": "Engineering",
    "School of Medicine": "Medicine",
    "School of Law": "Law",
    "Stanford Law School": "Law",
    "School of Humanities and Sciences": "H&S",
    "Graduate School of Education": "Ed School",
    "Doerr School of Sustainability": "Sustainability",
    "School of Earth, Energy & Environmental Sciences": "Earth Sciences",
    "Hoover Institution": "Hoover",
    "Freeman Spogli Institute for International Studies": "FSI",
    "Human-Centered Artificial Intelligence": "HAI",
    "Stanford Institute for Economic Policy Research": "SIEPR",
    "Institute for Research in the Social Sciences": "IRiSS",
    "Department of Economics": "Economics",
    "Cantor Arts Center": "Cantor Arts",
    "Stanford Libraries": "Libraries",
}


def _shorten_dept(name: str) -> str:
    return _DEPT_ABBREVS.get(name, name)


def _dept_prefix(departments: list[dict]) -> str:
    names = [d.get("name", "").strip() for d in (departments or []) if d.get("name")]
    if not names:
        return "Stanford"
    shortened = [_shorten_dept(n) for n in names[:2]]
    return " / ".join(shortened)


def _is_admin_event(title: str, desc: str) -> bool:
    return bool(_ADMIN_RE.search(f"{title} {desc}"))


def _clean_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _parse_localist_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    # Localist returns local times without timezone info
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=ZoneInfo(TZ))
        except ValueError:
            continue
    return None


def _fetch_localist(client: httpx.Client, lookahead_days: int) -> list[Event]:
    now = datetime.now(ZoneInfo(TZ))
    horizon = now + timedelta(days=lookahead_days)
    start_str = now.strftime("%Y-%m-%d")
    end_str = horizon.strftime("%Y-%m-%d")

    events: list[Event] = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        r = client.get(LOCALIST_API, params={
            "start": start_str,
            "end": end_str,
            "pp": 100,
            "p": page,
        })
        r.raise_for_status()
        data = r.json()
        meta = data.get("meta", {})
        total_pages = min(meta.get("pages", 1), 20)  # safety cap

        for wrapper in data.get("events", []):
            ev = wrapper.get("event", {})
            title = html.unescape((ev.get("title") or "").strip())
            if not title:
                continue
            desc_text = _clean_html(ev.get("description_text") or "")
            if _is_admin_event(title, desc_text):
                continue

            prefix = _dept_prefix(ev.get("departments", []))
            full_title = f"[{prefix}] {title}"
            url = ev.get("url") or ""
            location = (ev.get("location_name") or "").strip()
            event_id = ev.get("id") or ""

            for inst_wrapper in ev.get("event_instances", []):
                inst = inst_wrapper.get("event_instance", {})
                start_dt = _parse_localist_dt(inst.get("start"))
                end_dt = _parse_localist_dt(inst.get("end"))
                if start_dt is None:
                    continue
                if start_dt < now - timedelta(hours=6):
                    continue
                if start_dt > horizon:
                    continue

                inst_id = inst.get("id") or ""
                events.append(Event(
                    source="stanford_campus",
                    source_id=f"localist-{event_id}-{inst_id}",
                    city_tag="",
                    title=full_title,
                    start=start_dt.replace(tzinfo=None),
                    end=end_dt.replace(tzinfo=None) if end_dt else None,
                    location=location,
                    description=desc_text[:500].strip(),
                    ages="All ages",
                    registration=None,
                    url=url,
                    tz=TZ,
                ))

        page += 1

    log.info("stanford_campus localist: %d events", len(events))
    return events


def _fetch_ics(
    client: httpx.Client,
    url: str,
    source_id_prefix: str,
    label: str,
    title_prefix: str,
    now: datetime,
    horizon: datetime,
) -> list[Event]:
    try:
        r = client.get(url)
        r.raise_for_status()
    except Exception as exc:
        log.warning("%s: fetch failed: %s", label, exc)
        return []

    try:
        cal = Calendar.from_ical(r.content)
    except Exception as exc:
        log.warning("%s: ICS parse failed: %s", label, exc)
        return []

    events: list[Event] = []
    for comp in cal.walk("VEVENT"):
        start_prop = comp.get("DTSTART")
        if start_prop is None:
            continue
        start = start_prop.dt
        if not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time(), tzinfo=ZoneInfo(TZ))
        if start.tzinfo is None:
            start = start.replace(tzinfo=ZoneInfo(TZ))
        start_local = start.astimezone(ZoneInfo(TZ))
        if start_local < now - timedelta(hours=6):
            continue
        if start_local > horizon:
            continue

        end_prop = comp.get("DTEND")
        end_local = None
        if end_prop is not None:
            end = end_prop.dt
            if not isinstance(end, datetime):
                end = datetime.combine(end, datetime.min.time(), tzinfo=ZoneInfo(TZ))
            if end.tzinfo is None:
                end = end.replace(tzinfo=ZoneInfo(TZ))
            end_local = end.astimezone(ZoneInfo(TZ))

        uid = str(comp.get("UID") or "")
        title = str(comp.get("SUMMARY") or "").strip()
        if not title:
            # Some Drupal ICS feeds omit SUMMARY; try to derive from DESCRIPTION URL
            desc_raw_try = str(comp.get("DESCRIPTION") or "").strip()
            url_in_desc = re.search(r'https?://\S+', desc_raw_try)
            if url_in_desc:
                slug = url_in_desc.group(0).rstrip("/").split("/")[-1]
                title = slug.replace("-", " ").title()
            if not title:
                continue
        full_title = f"[{title_prefix}] {title}" if not title.startswith("[") else title

        desc_raw = _clean_html(str(comp.get("DESCRIPTION") or ""))
        location = str(comp.get("LOCATION") or "").strip()
        url_prop = comp.get("URL")
        ev_url = str(url_prop) if url_prop else ""

        events.append(Event(
            source="stanford_campus",
            source_id=f"{source_id_prefix}-{uid or title}-{start_local.isoformat()}",
            city_tag="",
            title=full_title,
            start=start_local.replace(tzinfo=None),
            end=end_local.replace(tzinfo=None) if end_local else None,
            location=location,
            description=desc_raw[:500].strip(),
            ages="All ages",
            registration=None,
            url=ev_url,
            tz=TZ,
        ))

    log.info("%s: %d events", label, len(events))
    return events


def _fetch_econ_feeds(client: httpx.Client, now: datetime, horizon: datetime) -> list[Event]:
    try:
        r = client.get(ECON_FEEDS_URL)
        r.raise_for_status()
    except Exception as exc:
        log.warning("stanford_campus economics feeds page: fetch failed: %s", exc)
        return []

    # Feeds appear as either https://.../.../ical or https://.../.ics
    ics_urls = list(dict.fromkeys(
        re.findall(r'https://economics\.stanford\.edu/[^\s"\'<>\t]+(?:/ical|\.ics)', r.text)
    ))
    if not ics_urls:
        log.warning("stanford_campus economics feeds page: no /ical or .ics URLs found")
        return []

    events: list[Event] = []
    for url in ics_urls:
        events.extend(_fetch_ics(
            client, url,
            source_id_prefix="econ",
            label=f"stanford_campus economics: {url}",
            title_prefix="Economics",
            now=now,
            horizon=horizon,
        ))
    return events


def fetch(city_tag: str = "", lookahead_days: int = 90) -> list[Event]:
    now = datetime.now(ZoneInfo(TZ))
    horizon = now + timedelta(days=lookahead_days)
    all_events: list[Event] = []

    with httpx.Client(
        headers={"User-Agent": UA},
        timeout=30,
        follow_redirects=True,
    ) as client:
        try:
            all_events.extend(_fetch_localist(client, lookahead_days))
        except Exception as exc:
            log.exception("stanford_campus localist failed: %s", exc)

        all_events.extend(_fetch_ics(
            client, LAW_ICS_URL,
            source_id_prefix="law",
            label="stanford_campus law ics",
            title_prefix="Stanford Law",
            now=now,
            horizon=horizon,
        ))

        try:
            all_events.extend(_fetch_econ_feeds(client, now, horizon))
        except Exception as exc:
            log.exception("stanford_campus economics feeds failed: %s", exc)

    # Dedupe within this source by source_id
    seen: set[str] = set()
    deduped: list[Event] = []
    for e in all_events:
        if e.source_id not in seen:
            seen.add(e.source_id)
            deduped.append(e)

    # Filter to public events only
    public_events = [e for e in deduped if is_public_event(e)]
    log.info("stanford_campus: %d after dedup, %d public", len(deduped), len(public_events))
    return public_events
