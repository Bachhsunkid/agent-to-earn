# ADR-0005: Go-live readiness check

- Status: accepted
- Date: 2026-10-31

## Context

The bot only earns money when it trades live, and going live is the operator's decision.
Until now that decision had no evidence beyond backtests and a raw P&L number. A backtest
can look good while the live machinery differs: missing candles, timing, protections,
fills, or a bug that only shows with real data. Paper trading is the cheap way to find out,
but only if it is compared with what the backtest says should have happened on the same days.

## Decision

`agent/readiness.py` backtests the live strategy over the paper-trading window and matches
the trades one by one (same pair and side, entry within 2 hours). The verdict is:

| Check | Pass when |
| --- | --- |
| paper_days | at least 14 days since the current strategy's first entry |
| sample | at least 20 closed paper trades |
| uptime | at least 95% heartbeat uptime over 72 hours |
| agreement | at least 70% of the trades on both sides match |
| profit_vs_backtest | paper P&L not below the backtest by more than max(5 USDT, 30%) |
| profitable | paper P&L above zero |

`wait` while the first two are short, `not_ready` if anything fails, `ready` otherwise.
Below 20 closed trades a failed comparison check shows as `wait`: a handful of trades
says nothing either way. Backtest trades are taken from two hours before the first paper
trade (the bot fills seconds after the candle the backtest enters on), and backtest trades
still open at the last candle are left out, as open paper trades are.
It runs before each research loop and on demand (`make readiness`); the dashboard shows it.

The report covers recent data that the gate holds out, so it is written to
`agent/runs/readiness/`, which the research agent may not read, and never to the loop log.

## Consequences

- The thresholds are judgment calls, not statistics: 20 trades cannot prove an edge. They
  catch broken plumbing and gross execution gaps, which is what paper trading can show.
- A strategy promotion restarts the clock, because only trades of the current strategy count.
- The check never switches to live by itself.
