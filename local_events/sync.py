"""Orchestrator: run all enabled scrapers, normalize, write ICS.

Usage:
    python -m local_events.sync            # write output to configured path
    python -m local_events.sync --dry-run  # print ICS to stdout
    python -m local_events.sync --diff     # compare today's ICS to prior

Run standalone from ~/scripts:
    cd ~/scripts && python -m local-events.sync --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .event import Event, is_volunteer_event, is_sports_event
from .ics_writer import build_calendar
from .normalizer import normalize
from .scrapers import (
    smcl, sanmateopl, curiodyssey, smcas,
    menlopark, menlopark_city,
    bayareakidfun,
    sancarlos,
    rwc,
    hiller,
    hiddenvilla,
    filoli,
    littlegreen,
    thehub,
    townandcountry,
    citytrees,
    msi,
    stanford,
    grassrootsecology,
    savethebay,
    canopy,
    flowstobay,
    pacificbeach,
    static_recurring,
)

log = logging.getLogger("local-events")


def load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run_all(cfg: dict) -> list[Event]:
    """Run every enabled scraper. Per-source failure is isolated."""
    all_events: list[Event] = []
    counts: dict[str, int] = {}
    sources_cfg = cfg["sources"]
    lookahead = cfg.get("lookahead_days", 90)

    if sources_cfg.get("smcl", {}).get("enabled"):
        try:
            evs = smcl.fetch(sources_cfg["smcl"]["branches"], lookahead_days=lookahead)
            counts["smcl"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("smcl scraper failed: %s", exc)
            counts["smcl"] = -1

    if sources_cfg.get("sanmateopl", {}).get("enabled"):
        try:
            evs = sanmateopl.fetch(
                sources_cfg["sanmateopl"]["ics_urls"],
                sources_cfg["sanmateopl"]["city_tag"],
                lookahead_days=lookahead,
            )
            counts["sanmateopl"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("sanmateopl scraper failed: %s", exc)
            counts["sanmateopl"] = -1

    if sources_cfg.get("curiodyssey", {}).get("enabled"):
        try:
            evs = curiodyssey.fetch(
                city_tag=sources_cfg["curiodyssey"].get("city_tag", "SM"),
                lookahead_days=lookahead,
            )
            counts["curiodyssey"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("curiodyssey scraper failed: %s", exc)
            counts["curiodyssey"] = -1

    if sources_cfg.get("smcas", {}).get("enabled"):
        try:
            evs = smcas.fetch(
                city_tag=sources_cfg["smcas"].get("city_tag", "SC"),
                lookahead_days=lookahead,
            )
            counts["smcas"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("smcas scraper failed: %s", exc)
            counts["smcas"] = -1

    if sources_cfg.get("menlopark", {}).get("enabled"):
        try:
            evs = menlopark.fetch(
                city_tag=sources_cfg["menlopark"].get("city_tag", "MP"),
                lookahead_days=lookahead,
            )
            counts["menlopark"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("menlopark scraper failed: %s", exc)
            counts["menlopark"] = -1

    if sources_cfg.get("bayareakidfun", {}).get("enabled"):
        try:
            evs = bayareakidfun.fetch(lookahead_days=lookahead)
            counts["bayareakidfun"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("bayareakidfun scraper failed: %s", exc)
            counts["bayareakidfun"] = -1

    if sources_cfg.get("menlopark_city", {}).get("enabled"):
        try:
            evs = menlopark_city.fetch(
                city_tag=sources_cfg["menlopark_city"].get("city_tag", "MP"),
                lookahead_days=lookahead,
            )
            counts["menlopark_city"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("menlopark_city scraper failed: %s", exc)
            counts["menlopark_city"] = -1

    if sources_cfg.get("sancarlos", {}).get("enabled"):
        try:
            evs = sancarlos.fetch(
                city_tag=sources_cfg["sancarlos"].get("city_tag", "SC"),
                lookahead_days=lookahead,
            )
            counts["sancarlos"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("sancarlos scraper failed: %s", exc)
            counts["sancarlos"] = -1

    if sources_cfg.get("hiller", {}).get("enabled"):
        try:
            evs = hiller.fetch(
                city_tag=sources_cfg["hiller"].get("city_tag", "SC"),
                lookahead_days=lookahead,
            )
            counts["hiller"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("hiller scraper failed: %s", exc)
            counts["hiller"] = -1

    if sources_cfg.get("hiddenvilla", {}).get("enabled"):
        try:
            evs = hiddenvilla.fetch(
                city_tag=sources_cfg["hiddenvilla"].get("city_tag", "LAH"),
                lookahead_days=lookahead,
            )
            counts["hiddenvilla"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("hiddenvilla scraper failed: %s", exc)
            counts["hiddenvilla"] = -1

    for name, mod, default_tag in (
        ("filoli", filoli, "WS"),
        ("littlegreen", littlegreen, "RWC"),
        ("thehub", thehub, "RWC"),
        ("townandcountry", townandcountry, "PA"),
        ("citytrees", citytrees, "RWC"),
        ("msi", msi, "SM"),
        ("grassrootsecology", grassrootsecology, "PA"),
        ("savethebay", savethebay, "PA"),
        ("canopy", canopy, "PA"),
        ("flowstobay", flowstobay, "SM"),
        ("pacificbeach", pacificbeach, "PAC"),
        ("static_recurring", static_recurring, "PA"),
    ):
        if not sources_cfg.get(name, {}).get("enabled"):
            continue
        try:
            evs = mod.fetch(
                city_tag=sources_cfg[name].get("city_tag", default_tag),
                lookahead_days=lookahead,
            )
            counts[name] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("%s scraper failed: %s", name, exc)
            counts[name] = -1

    if sources_cfg.get("stanford", {}).get("enabled"):
        try:
            evs = stanford.fetch(
                city_tag=sources_cfg["stanford"].get("city_tag", ""),
                lookahead_days=lookahead,
            )
            counts["stanford"] = len(evs)
            all_events.extend(evs)
        except Exception as exc:
            log.exception("stanford scraper failed: %s", exc)
            counts["stanford"] = -1

    rwc_cfg = sources_cfg.get("rwc", {})
    if rwc_cfg.get("enabled"):
        token = os.environ.get("SCRAPE_DO_TOKEN", "")
        if not token:
            log.warning("rwc: SCRAPE_DO_TOKEN not set; skipping")
        else:
            try:
                evs = rwc.fetch(
                    token=token,
                    city_tag=rwc_cfg.get("city_tag", "RWC"),
                    lookahead_days=lookahead,
                )
                counts["rwc"] = len(evs)
                all_events.extend(evs)
            except Exception as exc:
                log.exception("rwc scraper failed: %s", exc)
                counts["rwc"] = -1

    log.info("scraper counts: %s (total=%d)", counts, len(all_events))
    return all_events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="print per-feed counts to stdout, no file write")
    parser.add_argument("--out", help="override main output path (local-events.ics)")
    parser.add_argument("--volunteer-out", help="override volunteer output path (volunteer-events.ics)")
    parser.add_argument("--sports-out", help="override sports output path (college-sports.ics)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    cfg = load_config(Path(args.config))
    sources_cfg = cfg["sources"]
    raw = run_all(cfg)
    events = normalize(raw)
    log.info("final event count: %d", len(events))

    calendar_events: list[Event] = []
    volunteer_events: list[Event] = []
    sports_events: list[Event] = []
    # Partition order: sports > volunteer > main. Sports is a pure per-source
    # route (no keyword match), so overlap with the other two is impossible
    # in practice; explicit ordering documents intent.
    for e in events:
        src_cfg = sources_cfg.get(e.source, {})
        if is_sports_event(e, src_cfg.get("is_sports_source", False)):
            sports_events.append(e)
        elif is_volunteer_event(e, src_cfg.get("is_volunteer_source", False)):
            volunteer_events.append(e)
        else:
            calendar_events.append(e)
    log.info(
        "partitioned: main=%d volunteer=%d sports=%d",
        len(calendar_events), len(volunteer_events), len(sports_events),
    )

    main_bytes = build_calendar(calendar_events, name="Local Events")
    volunteer_bytes = build_calendar(volunteer_events, name="Volunteer Events")
    sports_bytes = build_calendar(sports_events, name="College Sports")

    if args.dry_run:
        print(f"main: {len(calendar_events)} events, {len(main_bytes)} bytes")
        print(f"volunteer: {len(volunteer_events)} events, {len(volunteer_bytes)} bytes")
        print(f"sports: {len(sports_events)} events, {len(sports_bytes)} bytes")
        for e in volunteer_events:
            print(f"  [volunteer] {e.source} {e.title} {e.start:%Y-%m-%d}")
        for e in sports_events:
            print(f"  [sports] {e.source} {e.title} {e.start:%Y-%m-%d}")
        return 0

    main_out = Path(os.path.expanduser(args.out or cfg["output_path"]))
    vol_out = Path(os.path.expanduser(
        args.volunteer_out or cfg.get("volunteer_output_path", str(main_out.parent / "volunteer-events.ics"))
    ))
    sports_out = Path(os.path.expanduser(
        args.sports_out or cfg.get("sports_output_path", str(main_out.parent / "college-sports.ics"))
    ))

    _write_feed(main_out, main_bytes, calendar_events, "main")
    _write_feed(vol_out, volunteer_bytes, volunteer_events, "volunteer")
    _write_feed(sports_out, sports_bytes, sports_events, "sports")
    return 0


def _write_feed(out_path: Path, ics_bytes: bytes, events: list[Event], label: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Prior-good fallback: only overwrite if we produced a non-empty ICS
    if len(events) == 0 and out_path.exists():
        log.warning("%s: no events produced; preserving prior ICS at %s", label, out_path)
        return
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_bytes(ics_bytes)
    if out_path.exists():
        shutil.copy2(out_path, out_path.with_suffix(out_path.suffix + ".prev"))
    tmp.replace(out_path)
    log.info("%s: wrote %d bytes to %s", label, len(ics_bytes), out_path)


if __name__ == "__main__":
    sys.exit(main())
