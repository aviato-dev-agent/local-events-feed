# local-events-feed

Auto-updating iCloud/Google-subscribable ICS feed of family/kids events in the
mid-Peninsula: San Mateo, Belmont, San Carlos, Redwood City, Menlo Park,
Palo Alto.

## Subscribe URL

```
https://aviato-dev-agent.github.io/local-events-feed/local-events.ics
```

### On iPhone
Settings → Calendar → Accounts → Add Account → Other → Add Subscribed Calendar → paste URL.
Set **Fetch New Data** to *Hourly* for that account (default is 12h).

### In Google Calendar
Left sidebar → **Other calendars** → **+** → **From URL** → paste.

## How it works

A GitHub Actions workflow runs daily at 13:00 UTC (6am PDT / 5am PST):
1. Fetches events from each enabled source (see `local_events/config.yaml`).
2. Filters to kid-appropriate audiences (ages ~5–13) and dedupes.
3. Prefixes titles with city tag: `[ATH] [B] [MP] [PA] [RWC] [SC] [SM]`.
4. Writes a fresh `local-events.ics` to the repo root.
5. Commits only when the event content actually changes (skips DTSTAMP-only churn).
6. GitHub Pages serves the file at the URL above.

## Sources

| Tag | Source | Status |
|-----|--------|--------|
| ATH, B, SC | San Mateo County Libraries (BiblioCommons JSON API) | Live |
| SM | San Mateo Public Library (LibCal ICS feed) | Live |
| RWC | Redwood City city + library | Phase 3 |
| MP | Menlo Park city + library | Phase 3 |
| PA | Palo Alto city + library | Phase 3 |

## Local dev

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m local_events.sync --dry-run > /tmp/preview.ics
```

## Plan / design

Full spec: [second-brain/plans/local-events-calendar.md](https://github.com/aviato-dev-agent/second-brain/blob/main/plans/local-events-calendar.md)

## Costs

$0. GitHub Actions free tier for public repos + GitHub Pages free.
