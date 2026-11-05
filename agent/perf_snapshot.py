"""Print a compact JSON snapshot of the running bot (profit, open trades, recent trades).

Reads API credentials from the environment; prints no secrets.
Usage: python3 agent/perf_snapshot.py
"""

import json
import sys
import urllib.request

import common

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
    snapshot = {
        "strategy": config.get("strategy"),
        "dry_run": config.get("dry_run"),
        "state": config.get("state"),
        "profit": {k: profit.get(k) for k in (
            "trade_count", "closed_trade_count", "profit_closed_coin", "profit_closed_percent",
            "profit_all_coin", "winning_trades", "losing_trades", "max_drawdown", "first_trade_date")},
        "open_trades": [{k: t.get(k) for k in TRADE_FIELDS} for t in open_trades],
        "recent_closed": [{k: t.get(k) for k in TRADE_FIELDS} for t in recent if not t.get("is_open")],
    }
    print(json.dumps(snapshot, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
