#!/bin/bash
# Run the events sync, commit if the ICS changed (ignoring DTSTAMP churn),
# and push to GitHub. GH Pages serves the file.
#
# Invoked by ~/Library/LaunchAgents/com.tim.local-events-sync.plist twice daily.
set -euo pipefail

REPO="$HOME/dev/local-events-feed"
PYTHON="$REPO/venv/bin/python"
LOG="$HOME/Library/Logs/local-events-sync.log"

cd "$REPO"

echo "==== $(date '+%Y-%m-%d %H:%M:%S %Z') sync starting ====" >>"$LOG"

# Generate ICS into the tracked file at repo root
"$PYTHON" -m local_events.sync --out local-events.ics >>"$LOG" 2>&1

git add local-events.ics

if git diff --cached --quiet -- local-events.ics; then
  echo "No changes to ICS file." >>"$LOG"
  exit 0
fi

# Suppress no-op runs where only DTSTAMP: lines changed
changed_lines=$(git diff --cached -U0 -- local-events.ics \
  | grep -E '^[+-]' \
  | grep -vE '^[+-]{3}' \
  | grep -vE '^[+-]DTSTAMP:' \
  | wc -l | tr -d ' ')

if [ "$changed_lines" -eq 0 ]; then
  echo "Only DTSTAMP churn; skipping commit." >>"$LOG"
  git reset HEAD -- local-events.ics
  exit 0
fi

git commit -m "sync: $(date -u +%F) (${changed_lines} lines changed)" >>"$LOG" 2>&1
git push >>"$LOG" 2>&1
echo "==== push complete ====" >>"$LOG"
