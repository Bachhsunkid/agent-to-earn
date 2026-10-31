"""Pick the top-N Binance USDT-M perpetuals by 24h quote volume as the static watchlist.

Writes user_data/config.pairs.json, which config.json merges via add_config_files.
Pairs younger than --min-age-days are skipped so backtests have enough history.
"""

import argparse
import json
import re
import time
from pathlib import Path

import ccxt

STABLE_BASES = re.compile(r"^(USDC|FDUSD|TUSD|USDP|DAI|BUSD|EUR|USD1|USDE)$")
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "user_data" / "config.pairs.json"


def select_pairs(markets: dict, tickers: dict, top: int, min_age_days: int, now_ms: float) -> list[str]:
    rows = []
    for symbol, m in markets.items():
        info = m.get("info", {})
        if not (m.get("swap") and m.get("linear") and m.get("active")):
            continue
        if m.get("quote") != "USDT" or m.get("settle") != "USDT":
            continue
        if info.get("contractType") != "PERPETUAL" or STABLE_BASES.match(m.get("base", "")):
            continue
        onboard_ms = int(info.get("onboardDate") or now_ms)
        if now_ms - onboard_ms < min_age_days * 86_400_000:
            continue
        rows.append(((tickers.get(symbol) or {}).get("quoteVolume") or 0.0, symbol))
    rows.sort(reverse=True)
    return [symbol for _, symbol in rows[:top]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--min-age-days", type=int, default=400)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    exchange = ccxt.binanceusdm()
    pairs = select_pairs(exchange.load_markets(), exchange.fetch_tickers(), args.top,
                         args.min_age_days, time.time() * 1000)
    args.out.write_text(json.dumps({"exchange": {"pair_whitelist": pairs}}, indent=2) + "\n")
    print(f"{len(pairs)} pairs -> {args.out.name}: {', '.join(pairs)}")


if __name__ == "__main__":
    main()
