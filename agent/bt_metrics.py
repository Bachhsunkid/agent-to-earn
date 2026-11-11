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


def trading_costs(trades: list[dict]) -> dict:
    """Fees paid and funding (negative = paid) in stake currency; profit_total_abs is net of both."""
    fees = sum((t.get("amount") or 0) * ((t.get("open_rate") or 0) * (t.get("fee_open") or 0)
                                         + (t.get("close_rate") or 0) * (t.get("fee_close") or 0)) for t in trades)
    hold = sum(t.get("trade_duration") or 0 for t in trades) / len(trades) / 60 if trades else 0.0
    return {"fees_abs": round(fees, 2), "funding_abs": round(sum(t.get("funding_fees") or 0 for t in trades), 2),
            "avg_hold_hours": round(hold, 1)}


def fixed_stake_profit(trades: list[dict], starting_balance: float) -> dict:
    """Profit as if every trade had been sized from the starting balance, with and without the
    single best trade.

    Stakes follow equity, so one huge winner inflates every later trade, and a few outliers can
    decide a comparison on their own. Each trade's profit is scaled by starting balance over the
    equity it was sized from (starting balance plus profit closed before it opened).
    """
    closed = sorted((t["close_timestamp"], t["profit_abs"]) for t in trades)
    scaled = []
    for t in trades:
        equity = starting_balance + sum(p for ts, p in closed if ts <= t["open_timestamp"])
        scaled.append(t["profit_abs"] * starting_balance / equity if equity > 0 else 0.0)
    total = sum(scaled)
    best = max(0.0, max(scaled, default=0.0))
    return {"profit_fixed_abs": round(total, 2), "profit_fixed_ex_best_abs": round(total - best, 2)}


def summarize(stats: dict, strategy: str, detail: bool = False) -> dict:
    s = stats["strategy"][strategy]
    out = {k: s.get(k) for k in FIELDS}
    out["max_leverage"] = max((t["leverage"] for t in s.get("trades", [])), default=0.0)
    out |= trading_costs(s.get("trades", []))
    out |= fixed_stake_profit(s.get("trades", []), s.get("starting_balance") or 0.0)
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
