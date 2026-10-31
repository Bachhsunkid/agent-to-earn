#!/usr/bin/env bash
# Entrypoint of the research container: run the research loop every day at RESEARCH_AT
# (HH:MM, UTC). Replaces cron, so the VM needs nothing but Docker.
set -uo pipefail
cd "$(dirname "$0")/.."

AT=${RESEARCH_AT:-01:00}
if [[ ! $AT =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  echo "RESEARCH_AT must be HH:MM (UTC), got '$AT'" >&2
  exit 1
fi
# A lock left behind by a container that was killed mid-run would block every later run.
rmdir agent/runs/.loop.lock 2>/dev/null && echo "removed stale research loop lock"

while true; do
  now=$(date -u +%s)
  next=$(date -u -d "today $AT" +%s)
  if [ "$next" -le "$now" ]; then next=$(date -u -d "tomorrow $AT" +%s); fi
  echo "next research loop at $(date -u -d "@$next" '+%F %H:%M') UTC"
  sleep $(( next - now ))
  agent/run_loop.sh || echo "research loop exited with $?"
done
