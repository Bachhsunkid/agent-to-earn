#!/usr/bin/env bash
# One unattended research loop: refresh data, let Claude Code propose and gate one
# candidate strategy. Results go to the journal and the dashboard; Telegram only
# hears about failures. Runs inside the research container (agent/scheduler.sh runs it
# nightly; `make loop` runs it now).
set -uo pipefail
cd "$(dirname "$0")/.."

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TODAY=$(date -u +%F)
RUNS=agent/runs
LOG="$RUNS/loop-$STAMP.log"
DATA_FROM=20250801  # keep in sync with DATA_FROM in the Makefile
mkdir -p "$RUNS" agent/journal

notify() { python3 agent/notify.py "$1" >/dev/null || true; }
# Machine-readable run record for the dashboard.
record() { printf '{"stamp": "%s", "date": "%s", "stage": "%s", "exit": %s}\n' \
  "$STAMP" "$TODAY" "$1" "$2" >"$RUNS/loop-$STAMP.json"; }

if ! mkdir "$RUNS/.loop.lock" 2>/dev/null; then
  echo "another research loop is running" >&2
  exit 1
fi
trap 'rmdir "$RUNS/.loop.lock"' EXIT
record running 0

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  record config 1
  notify "Research loop $STAMP skipped: CLAUDE_CODE_OAUTH_TOKEN is not set in .env (run: claude setup-token)"
  exit 1
fi

if ! freqtrade download-data --config user_data/config.json --timerange "$DATA_FROM-" \
    --timeframes 1h 2h 4h >>"$LOG" 2>&1; then
  record data 1
  notify "Research loop $STAMP: data refresh failed, see $LOG"
  exit 1
fi

# Go-live readiness for the dashboard. Its output covers held-out data, so it goes only to a
# directory the agent may not read, never to $LOG. A failure here never blocks research.
python3 agent/readiness.py --write agent/runs/readiness/latest.json >/dev/null 2>&1 || true

# Only the permissions in agent/loop.settings.json apply: user-level allow rules and
# MCP servers are not loaded, and anything not allowed is denied without asking.
claude -p "$(cat agent/LOOP.md)" \
  --permission-mode dontAsk \
  --settings agent/loop.settings.json \
  --setting-sources project \
  --strict-mcp-config \
  </dev/null >>"$LOG" 2>&1
status=$?

if [ "$status" -ne 0 ] || [ ! -f "agent/journal/$TODAY.md" ]; then
  record claude "$(( status == 0 ? 1 : status ))"
  notify "Research loop $STAMP failed (exit $status, journal: $([ -f "agent/journal/$TODAY.md" ] && echo yes || echo missing)), see $LOG"
  exit $(( status == 0 ? 1 : status ))
fi
record done 0
