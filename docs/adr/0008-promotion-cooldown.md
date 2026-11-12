# ADR-0008: Promote at most once every 14 days

Date: 2026-11-12
Status: accepted

## Context

The gate promoted TrendLongSlowExit4hV1 on 2026-11-10 and LongBreakout60Exit30V1 on
2026-11-12. Both are variants of the same long breakout, and each one passed on the held-out
window that the previous one had also been judged on.

The live strategy enters about 10 times a month (5 to 17 per month in backtests since
2025-09) and none at all from 2026-11-01 to 2026-11-12. The go-live readiness check
(ADR-0005) needs 14 days and 20 closed trades of the current strategy, and a promotion
restarts that count. With nightly promotions possible, the bot would never collect the paper
record needed to judge any strategy. The research agent also gets no live trades of the
current strategy to learn from.

## Decision

- `gate.py` refuses to promote within `PROMOTION_COOLDOWN` (14 days) of the last promotion.
  The last promotion is the newest gate report whose action starts with "promoted".
- A candidate submitted during the pause is not judged. The gate runs only the integrity
  check, reports `cooldown` with the end of the pause, sets the action to "deferred", and
  leaves the file in `candidates/` so it can be submitted later. The candidate is not
  archived and no backtest runs.
- Dry runs (`--no-promote`) ignore the cooldown.
- `perf_snapshot.py` reports `promotions_paused_until`, so the research agent knows not to
  submit. LOOP.md tells it to keep researching and, once the pause ends, to submit the best
  qualifying earlier candidate instead of a new one.
- The public page leaves deferred reports out of the list of gate decisions.

## Consequences

- A strategy keeps trading for at least 14 days. That is still short of the 20-trade
  readiness bar at the current trade rate, but it no longer resets every night.
- A better candidate can wait up to 14 days. Paper trading costs nothing, so the delay
  costs nothing either. The held-out window moves forward meanwhile, so the candidate is
  judged on newer data when it is submitted.
- The clock counts from the last promotion only, so an operator's manual strategy change
  does not start a cooldown.
