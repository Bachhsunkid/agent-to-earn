# ADR-0007: Compare strategies at a fixed stake, with and without the best trade

Date: 2026-11-11
Status: accepted

## Context

On 2026-11-10 the gate promoted TrendLongSlowExit4hV1 (TrendLong4hV1 with a 20-bar instead
of a 10-bar Donchian exit). Its out-of-sample profit was +1,454 USDT against +26 for the live
strategy, and almost all of it was one AKE long that gained about 100x during a pump.

Two things made that comparison meaningless:

- Stakes follow equity. After the AKE trade the backtest account was several times larger,
  so every later trade, winning or losing, counted several times over.
- `beat_live_profit` compared total profit, so one outlier decided the result on its own.

Without each side's best trade, at a fixed stake, the candidate made -31 USDT out of sample
and the live strategy -13. In-sample the order was reversed (-9 vs -34): the two are close,
and both depend on a few big runs.

## Decision

`bt_metrics.py` reports two more metrics, computed from the trade list:

- `profit_fixed_abs`: each trade's profit scaled by starting balance over the equity it was
  sized from (starting balance plus profit closed before it opened), summed.
- `profit_fixed_ex_best_abs`: the same without the single best trade.

The gate's out-of-sample comparison with the live strategy now requires the candidate to beat
it on both (`beat_live_profit`, `beat_live_profit_ex_best`). The drawdown comparison and the
absolute criteria are unchanged. Cached incumbent results without the new metrics are
recomputed.

TrendLongSlowExit4hV1 stays live. Under the new rule it would have failed
`beat_live_profit_ex_best` out of sample, but it does better in-sample on the same measure,
the change is one parameter, and swapping back would restart paper-trading readiness again.

## Consequences

- An edge that rests on one trade no longer wins a promotion. A strategy with two or three
  big winners and a better rest still can.
- Trend following earns its money from a few big runs, so ex-best profit is often negative for
  both sides. The rule is relative: a candidate needs to be better without its luckiest trade,
  not profitable without it.
- The fixed-stake scaling is approximate: it ignores open positions' unrealized profit and the
  account leverage cap, which also shape stake sizes.
