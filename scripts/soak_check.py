"""Measure bot stability from its log: heartbeat uptime and errors over a window.

Uptime counts the time covered by RUNNING heartbeats; any gap longer than twice the
heartbeat interval is downtime. Exit code 0 means uptime >= --min-uptime and errors
<= --max-errors. Errors of the Telegram client (Telegram API outages such as "Bad Gateway")
are counted apart: they delay alerts but say nothing about the bot itself.

Usage: python3 scripts/soak_check.py [--hours 24] [--min-uptime 0.95] [--max-errors 0]
"""

import argparse
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "user_data" / "logs" / "freqtrade.log"
LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ - (\S+) - (\w+) - (.*)")
HEARTBEAT_INTERVAL = 60


def analyze(lines, now: datetime, hours: float, interval: int = HEARTBEAT_INTERVAL) -> dict:
    window_start = now - timedelta(hours=hours)
    first_seen, beats, errors, warnings, telegram_errors = None, [], [], 0, 0
    for line in lines:
        m = LINE.match(line)
        if not m:
            continue
        ts = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S")
        if ts < window_start:
            continue
        first_seen = first_seen or ts
        if m[3] == "ERROR" and m[2].startswith("telegram."):
            telegram_errors += 1
        elif m[3] == "ERROR":
            errors.append(line.strip()[:200])
        elif m[3] == "WARNING":
            warnings += 1
        if "Bot heartbeat" in m[4] and "state='RUNNING'" in m[4]:
            beats.append(ts)
    start = first_seen or window_start
    span = max((now - start).total_seconds(), 1.0)
    downtime = 0.0 if beats else span
    for prev, cur in zip([start, *beats], [*beats, now]) if beats else ():
        gap = (cur - prev).total_seconds()
        if gap > 2 * interval:
            downtime += gap - interval
    return {"from": start.isoformat(sep=" "), "to": now.isoformat(sep=" "),
            "hours": round(span / 3600, 2), "heartbeats": len(beats),
            "uptime": round(max(0.0, 1 - downtime / span), 4),
            "errors": len(errors), "warnings": warnings, "telegram_errors": telegram_errors,
            "last_errors": errors[-5:]}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--min-uptime", type=float, default=0.95)
    parser.add_argument("--max-errors", type=int, default=0)
    parser.add_argument("--log", type=Path, default=LOG)
    args = parser.parse_args(argv)
    now = datetime.now(UTC).replace(tzinfo=None)
    report = analyze(args.log.read_text(errors="replace").splitlines(), now, args.hours)
    ok = report["uptime"] >= args.min_uptime and report["errors"] <= args.max_errors
    for key, value in report.items():
        print(f"{key}: {value}")
    print(f"result: {'PASS' if ok else 'FAIL'} (uptime >= {args.min_uptime:.0%}, errors <= {args.max_errors})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
