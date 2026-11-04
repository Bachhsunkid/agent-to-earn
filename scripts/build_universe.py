"""Point-in-time trading universe: each day's top-N USDT-M perpetuals by trailing quote volume.

Backtests and the live bot may only enter the pairs on that day's list (GuardedStrategy
checks before every entry). A day's list uses only volume from earlier, completed days, so a
backtest cannot favour coins that are popular today because they already rallied.

Writes (both gitignored, rebuilt nightly by agent/run_loop.sh):
  user_data/universe.json      {"top", "lookback_days", "generated_at", "days": {date: [pairs]}}
  user_data/config.pairs.json  whitelist = every pair that was ever on a list, so the bot and
                               the backtests have candles for all of them

Daily candles of every eligible perpetual are downloaded first. Pairs delisted before today
are missing from the exchange's market list, so some survivor bias remains.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "user_data" / "universe.json"
PAIRS_CONFIG = ROOT / "user_data" / "config.pairs.json"
DATA_DIR = ROOT / "user_data" / "data" / "binance" / "futures"
DATA_FROM = date(2025, 8, 1)  # keep in sync with DATA_FROM in the Makefile and agent/run_loop.sh
TOP = 15
LOOKBACK_DAYS = 7
STABLE_BASES = re.compile(r"^(USDC|FDUSD|TUSD|USDP|DAI|BUSD|EUR|USD1|USDE)$")


def eligible(markets: dict) -> list[str]:
    """Active linear USDT-settled perpetuals, stablecoin bases excluded."""
    pairs = []
    for symbol, m in markets.items():
        if not (m.get("swap") and m.get("linear") and m.get("active")):
            continue
        if m.get("quote") != "USDT" or m.get("settle") != "USDT":
            continue
        if m.get("info", {}).get("contractType") != "PERPETUAL" or STABLE_BASES.match(m.get("base", "")):
            continue
        pairs.append(symbol)
    return sorted(pairs)


def daily_members(quote_volume: pd.DataFrame, top: int, lookback: int, start: date, end: date) -> dict[str, list[str]]:
    """{YYYY-MM-DD: top pairs} for start..end; each day ranks the `lookback` days before it.

    `quote_volume` has one row per UTC day (DatetimeIndex) and one column per pair; missing
    days count as no data, and a pair needs all `lookback` days to be ranked.
    """
    days = pd.date_range(min(quote_volume.index.min(), pd.Timestamp(start, tz="UTC")),
                         pd.Timestamp(end, tz="UTC"), freq="D")
    trailing = quote_volume.reindex(days).rolling(lookback, min_periods=lookback).sum().shift(1)
    members = {}
    for day, row in trailing.loc[pd.Timestamp(start, tz="UTC"):].iterrows():
        ranked = row.dropna().sort_values(ascending=False, kind="stable")
        members[day.strftime("%Y-%m-%d")] = sorted(ranked.index[:top])
    return members


def load_quote_volume(pairs: list[str], data_dir: Path = DATA_DIR) -> pd.DataFrame:
    columns = {}
    for pair in pairs:
        path = data_dir / f"{pair.replace('/', '_').replace(':', '_')}-1d-futures.feather"
        if path.exists():
            candles = pd.read_feather(path).set_index("date")
            columns[pair] = candles["volume"] * candles["close"]
    return pd.DataFrame(columns).sort_index()


def download_daily(pairs: list[str], since: date) -> None:
    proc = subprocess.run(
        ["freqtrade", "download-data", "--config", "user_data/config.json", "--pairs", *pairs,
         "--timeframes", "1d", "--candle-types", "futures", "--timerange", f"{since:%Y%m%d}-"],
        cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("download-data failed:\n" + "\n".join((proc.stdout + proc.stderr).splitlines()[-20:]))


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    tmp.replace(path)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=TOP)
    parser.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    parser.add_argument("--skip-download", action="store_true", help="use the daily candles already on disk")
    args = parser.parse_args(argv)

    import ccxt

    pairs = eligible(ccxt.binanceusdm().load_markets())
    if not PAIRS_CONFIG.exists():  # config.json merges it; download-data needs it to exist
        write_json(PAIRS_CONFIG, {"exchange": {"pair_whitelist": []}})
    if not args.skip_download:
        download_daily(pairs, DATA_FROM - timedelta(days=args.lookback_days + 1))
    today = datetime.now(UTC).date()
    members = daily_members(load_quote_volume(pairs), args.top, args.lookback_days, DATA_FROM, today)
    if not members.get(today.isoformat()):
        print(f"error: no universe for {today}; daily candles are missing or stale", file=sys.stderr)
        return 1
    whitelist = sorted({p for day in members.values() for p in day})
    write_json(UNIVERSE, {"top": args.top, "lookback_days": args.lookback_days,
                          "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "days": members})
    write_json(PAIRS_CONFIG, {"exchange": {"pair_whitelist": whitelist}})
    print(f"{len(members)} days, {len(whitelist)} pairs in the whitelist; today: {', '.join(members[today.isoformat()])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
