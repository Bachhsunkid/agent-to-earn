"""Backtest a strategy for research. Out-of-sample data is off limits here.

Usage: python3 agent/bt.py <StrategyClass> [--timerange YYYYMMDD-YYYYMMDD]

Defaults to the full in-sample window. Ranges reaching into the held-out
out-of-sample window are rejected; only agent/gate.py evaluates that data.
"""

import argparse
import json
import sys
from datetime import date

import common


def validate(strategy: str, timerange: str | None, today: date) -> str:
    if not common.STRATEGY_NAME_RE.match(strategy):
        raise ValueError(f"invalid strategy class name: {strategy!r}")
    in_sample, out_of_sample = common.windows(today)
    if timerange is None:
        return in_sample
    start, end = common.parse_timerange(timerange)
    oos_start, _ = common.parse_timerange(out_of_sample)
    if start < common.DATA_START:
        raise ValueError(f"timerange must start on or after {common.DATA_START:%Y%m%d}")
    if end is None or end > oos_start:
        raise ValueError(f"timerange must end on or before {oos_start:%Y%m%d} (later data is held out)")
    return timerange


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy")
    parser.add_argument("--timerange")
    args = parser.parse_args(argv)
    try:
        timerange = validate(args.strategy, args.timerange, date.today())
        metrics = common.backtest(args.strategy, timerange, "research", detail=True)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"strategy": args.strategy, "timerange": timerange, **metrics}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
