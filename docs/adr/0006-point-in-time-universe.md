# ADR-0006: Point-in-time trading universe

- Status: accepted
- Date: 2026-11-04

## Context

Backtests, the gate and the bot all traded a static list of 15 pairs picked by 24-hour
volume on 2026-10-29. High volume on that day mostly meant "rallied recently", so every
backtest over the previous 15 months traded coins chosen with hindsight. A review of
TrendRegimeV1 (live since 2026-10-29) on 2025-08 to 2026-11, with BTC down 28%, showed:

| Universe | TrendRegimeV1 | its shorts | long only, 4h |
| --- | --- | --- | --- |
| static list picked on 2026-10-29 | +150 USDT, DD 28% | -134 | +47 |
| 15 majors fixed in advance | -141, DD 44% | -64 | -17 |
| daily top 15 by trailing 7-day volume | +162, DD 25%; -105 since July | -109 | +124, DD 16% |

The static list overstated the edge, the short side lost money everywhere, and the
nightly research agent kept optimising on the biased list (in-sample winners that failed
out of sample for five nights).

## Decision

- `scripts/build_universe.py` downloads daily candles of every active USDT-M perpetual and
  writes `user_data/universe.json`: for each UTC day, the top 15 by quote volume over the
  7 completed days before it. The whitelist (`user_data/config.pairs.json`) becomes every
  pair that was ever on a list. Both files are generated and gitignored; the research loop
  rebuilds them nightly and reloads the bot when the whitelist changes.
- `GuardedStrategy.confirm_trade_entry` refuses entries on pairs not on that day's list,
  and refuses all entries when the list is missing or more than 2 days old. Freqtrade
  calls it in backtests and in the running bot, so both follow the same rule, and the
  research agent cannot change it.
- TrendLong4hV1 (the same breakout on 4h, long only) replaces TrendRegimeV1. It passed the
  gate on the new universe (out of sample: 66 trades, PF 1.17, DD 10.6%, against a losing
  incumbent).

## Consequences

- Backtests now reflect what a bot following a volume rule could have traded. Some survivor
  bias remains: perpetuals delisted before today are missing from the exchange's market
  list, and they mostly fell.
- The whitelist grows to about 190 pairs, so the bot loads more candles and the first data
  download takes about half an hour. Many pairs are young, illiquid small caps; their
  squeezes produce most of the trend profit (including large funding payments to longs) and
  fill worse in reality than in a backtest. Check this in paper trading before going live.
- The operator chose TrendLong4hV1 after seeing the gate's held-out window, so its gate pass
  is weak evidence. Forward paper trading is the real test.
- Profit is lumpy: a few trades make the year and most months lose a little. TrendLong4hV1
  makes about 13 trades a month, so the readiness check needs about six weeks for its
  20-trade sample.
- If the universe rebuild fails, the bot stops entering new trades after 2 days; the loop
  sends a Telegram alert when that step fails.
