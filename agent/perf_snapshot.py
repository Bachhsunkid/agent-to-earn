"""Print a compact JSON snapshot of the running bot (profit, open trades, recent trades).

Reads API credentials from the environment; prints no secrets.
Usage: python3 agent/perf_snapshot.py
"""

import json
import sys
import urllib.request
from datetime import UTC, datetime

import common
import gate

TRADE_FIELDS = ("pair", "strategy", "is_short", "leverage", "stake_amount", "open_date", "close_date",
                "profit_ratio", "profit_abs", "exit_reason", "enter_tag")


def get(path: str, auth: str):
    req = urllib.request.Request(f"{common.BOT_API}/{path}", headers={"Authorization": auth})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def main() -> int:
    try:
        auth = common.api_auth()
        profit = get("profit", auth)
        open_trades = get("status", auth)
        # order_by_id=false: newest closed trades first (the API default returns the oldest).
        recent = get("trades?limit=30&order_by_id=false", auth).get("trades", [])
        config = get("show_config", auth)
    except (OSError, KeyError, ValueError) as exc:
        print(f"bot API not reachable ({type(exc).__name__}); is the bot running?", file=sys.stderr)
        return 1
    strategy = config.get("strategy")
    closed = [t for t in recent if not t.get("is_open")]
    paused = gate.promotions_paused_until(datetime.now(UTC))
    snapshot = {
        "strategy": strategy,
        "dry_run": config.get("dry_run"),
        "state": config.get("state"),
        # The bot's totals include trades of strategies that are no longer live.
        "profit_all_strategies": {k: profit.get(k) for k in (
            "trade_count", "closed_trade_count", "profit_closed_coin", "profit_closed_percent",
            "profit_all_coin", "winning_trades", "losing_trades", "max_drawdown", "first_trade_date")},
        "open_trades": [{k: t.get(k) for k in TRADE_FIELDS} for t in open_trades],
        "recent_closed": [{k: t.get(k) for k in TRADE_FIELDS} for t in closed if t.get("strategy") == strategy],
        "recent_closed_by_retired_strategies": sum(t.get("strategy") != strategy for t in closed),
        # The gate does not promote before this time (UTC), so do not submit until then.
        "promotions_paused_until": paused.isoformat(timespec="minutes") if paused else None,
    }
    print(json.dumps(snapshot, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
