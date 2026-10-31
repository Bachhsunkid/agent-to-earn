"""Print summary metrics of the latest backtest in a directory as one JSON line.

Runs inside the tools container (needs freqtrade).
Usage: python agent/bt_metrics.py <results_dir> <Strategy> [--detail]
"""

import json
import sys

FIELDS = (
    "total_trades", "trade_count_long", "trade_count_short", "profit_total", "profit_total_abs",
    "max_drawdown_account", "profit_factor", "winrate", "sharpe", "calmar",
    "starting_balance", "final_balance", "backtest_start", "backtest_end",
)


def summarize(stats: dict, strategy: str, detail: bool = False) -> dict:
    s = stats["strategy"][strategy]
    out = {k: s.get(k) for k in FIELDS}
    out["max_leverage"] = max((t["leverage"] for t in s.get("trades", [])), default=0.0)
    if detail:
        out["per_pair"] = [
            {"pair": r["key"], "trades": r["trades"], "profit_abs": round(r["profit_total_abs"], 2)}
            for r in s.get("results_per_pair", []) if r.get("key") != "TOTAL"
        ]
        out["exit_reasons"] = [
            {"reason": r["key"], "trades": r["trades"], "profit_abs": round(r["profit_total_abs"], 2)}
            for r in s.get("exit_reason_summary", []) if r.get("key") != "TOTAL"
        ]
    return out


def main(argv: list[str]) -> None:
    from freqtrade.data.btanalysis import load_backtest_stats

    print(json.dumps(summarize(load_backtest_stats(argv[0]), argv[1], "--detail" in argv)))


if __name__ == "__main__":
    main(sys.argv[1:])
