"""Go-live readiness: does paper trading behave like the backtest, long enough, stably?

Backtests the live strategy over the paper-trading window and compares it trade by trade
with what the dry-run bot actually did. Matching entries mean the live machinery (data,
timing, protections) reproduces the research numbers; a big gap means a bug or an
execution effect the backtest misses, and going live would be a guess.

The verdict is advice for the operator; switching to real money stays a human decision.
The result covers recent, held-out data, so it is written where the research agent may
not read (agent/loop.settings.json denies agent/runs/readiness/**).

Runs in the research container (bot API, freqtrade and data):
  python3 agent/readiness.py [--write agent/runs/readiness/latest.json]
"""

import argparse
import json
import subprocess
import sys
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import common

sys.path.insert(0, str(common.ROOT / "scripts"))
import soak_check as soak  # noqa: E402

OUT = common.RUNS / "readiness" / "latest.json"
MIN_PAPER_DAYS = 14
MIN_CLOSED_TRADES = 20
MIN_AGREEMENT = 0.70  # share of trades found on both sides (same pair, side, entry within MATCH_WINDOW)
MATCH_WINDOW = timedelta(hours=2)
MIN_UPTIME = 0.95
UPTIME_HOURS = 72
# Paper may trail the backtest by this much before it counts as a failure.
PROFIT_TOLERANCE_ABS = 5.0
PROFIT_TOLERANCE_REL = 0.30


def api_get(path: str):
    req = urllib.request.Request(f"{common.BOT_API}/{path}", headers={"Authorization": common.api_auth()})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def paper_trades(get=api_get) -> tuple[dict, list[dict]]:
    config = get("show_config")
    trades, offset = [], 0
    while True:
        page = get(f"trades?limit=500&offset={offset}").get("trades", [])
        trades += page
        if len(page) < 500:
            return config, trades
        offset += 500


def parse_time(value) -> datetime:
    """Freqtrade API dates are 'YYYY-MM-DD HH:MM:SS' in UTC; backtest exports carry a zone."""
    dt = datetime.fromisoformat(str(value).replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normalize(t: dict) -> dict:
    return {"pair": t["pair"], "short": bool(t.get("is_short")), "open": parse_time(t["open_date"]),
            "profit": float(t.get("profit_abs") or 0.0)}


def match(paper: list[dict], backtest: list[dict], window: timedelta = MATCH_WINDOW) -> dict:
    """Pair trades greedily by (pair, side, nearest entry within window)."""
    unmatched = list(backtest)
    matched = 0
    for p in sorted(paper, key=lambda t: t["open"]):
        candidates = [b for b in unmatched if b["pair"] == p["pair"] and b["short"] == p["short"]
                      and abs(b["open"] - p["open"]) <= window]
        if candidates:
            unmatched.remove(min(candidates, key=lambda b: abs(b["open"] - p["open"])))
            matched += 1
    total = len(paper) + len(backtest)
    return {"matched": matched, "paper_only": len(paper) - matched, "backtest_only": len(unmatched),
            "agreement": 2 * matched / total if total else None}


def backtest_trades(strategy: str, start: datetime, end: datetime) -> list[dict]:
    """Closed backtest trades of `strategy` that opened in [start - MATCH_WINDOW, end).

    The window opens early because the bot fills seconds after the candle the backtest enters
    on. Trades still open at the last candle (force_exit) are left out, like open paper trades.
    """
    from freqtrade.data.btanalysis import load_backtest_data

    out_dir = common.RESULTS / "readiness" / uuid.uuid4().hex[:8]
    out_dir.mkdir(parents=True)
    timerange = f"{(start - timedelta(days=1)):%Y%m%d}-{(end + timedelta(days=1)):%Y%m%d}"
    for args in (["freqtrade", "download-data", "--config", "user_data/config.json", "--timerange",
                  f"{(start - timedelta(days=30)):%Y%m%d}-", "--timeframes", "1h", "2h", "4h"],
                 ["freqtrade", "backtesting", "--config", "user_data/config.json", "--strategy", strategy,
                  "--timerange", timerange, "--enable-protections", "--export", "trades",
                  "--backtest-directory", str(out_dir)]):
        proc = common.run_tools(args)
        if proc.returncode != 0:
            raise RuntimeError(f"{args[1]} failed:\n{common.tail(proc)}")
    df = load_backtest_data(out_dir, strategy)
    rows = [r for r in df.to_dict("records") if r.get("exit_reason") != "force_exit"]
    return [t for t in map(normalize, rows) if start - MATCH_WINDOW <= t["open"] < end]


def check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def evaluate(config: dict, trades: list[dict], backtest, uptime: dict, now: datetime) -> dict:
    strategy = config.get("strategy")
    closed = [normalize(t) for t in trades if not t.get("is_open") and t.get("strategy") == strategy]
    checks = []
    if not config.get("dry_run", True):
        checks.append(check("mode", "info", "bot is trading live; readiness applies to paper trading"))
    first = min((t["open"] for t in closed), default=None)
    # The clock starts at the strategy's first entry, even while that trade is still open.
    started = min((parse_time(t["open_date"]) for t in trades if t.get("strategy") == strategy), default=None)
    days = (now - started).total_seconds() / 86400 if started else 0.0
    checks.append(check("paper_days", "pass" if days >= MIN_PAPER_DAYS else "wait",
                        f"{days:.1f} of {MIN_PAPER_DAYS} days of paper trading with {strategy}"))
    checks.append(check("sample", "pass" if len(closed) >= MIN_CLOSED_TRADES else "wait",
                        f"{len(closed)} of {MIN_CLOSED_TRADES} closed trades"))
    checks.append(check("uptime", "pass" if uptime["uptime"] >= MIN_UPTIME else "fail",
                        f"{uptime['uptime']:.1%} over {uptime['hours']}h, {uptime['errors']} errors"))
    comparison = None
    if closed:
        bt = backtest(strategy, first, now)
        m = match(closed, bt)
        paper_profit, bt_profit = sum(t["profit"] for t in closed), sum(t["profit"] for t in bt)
        floor = bt_profit - max(PROFIT_TOLERANCE_ABS, PROFIT_TOLERANCE_REL * abs(bt_profit))
        comparison = {**m, "paper_trades": len(closed), "backtest_trades": len(bt),
                      "paper_profit": round(paper_profit, 2), "backtest_profit": round(bt_profit, 2)}
        agreement = m["agreement"] or 0.0
        checks.append(check("agreement", "pass" if agreement >= MIN_AGREEMENT else "fail",
                            f"{agreement:.0%} of trades match the backtest ({m['matched']} matched, "
                            f"{m['paper_only']} paper only, {m['backtest_only']} backtest only)"))
        checks.append(check("profit_vs_backtest", "pass" if paper_profit >= floor else "fail",
                            f"paper {paper_profit:+.2f} vs backtest {bt_profit:+.2f} USDT (floor {floor:+.2f})"))
        checks.append(check("profitable", "pass" if paper_profit > 0 else "fail",
                            f"paper P&L {paper_profit:+.2f} USDT"))
        if len(closed) < MIN_CLOSED_TRADES:
            # A handful of trades proves nothing either way: report misses, but keep waiting.
            for c in checks[-3:]:
                c["status"] = "wait" if c["status"] == "fail" else c["status"]
    statuses = {c["status"] for c in checks}
    verdict = "not_ready" if "fail" in statuses else "wait" if "wait" in statuses else "ready"
    return {"generated_at": now.isoformat(timespec="seconds"), "strategy": strategy, "verdict": verdict,
            "checks": checks, "comparison": comparison}


def write(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1, default=str))
    tmp.replace(path)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", type=Path, help=f"also save the report (default location: {OUT})")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        config, trades = paper_trades()
        uptime = soak.analyze(soak.read_log(soak.LOG), now.replace(tzinfo=None), UPTIME_HOURS)
        report = evaluate(config, trades, backtest_trades, uptime, now)
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        report = {"generated_at": now.isoformat(timespec="seconds"), "verdict": "error",
                  "checks": [check("run", "fail", f"{type(exc).__name__}: {exc}"[:500])], "comparison": None}
    if args.write:
        write(report, args.write)
    print(json.dumps(report, indent=1, default=str))
    return 0 if report["verdict"] in ("ready", "wait") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
