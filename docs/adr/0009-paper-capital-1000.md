# ADR-0009: Paper trade with 1000 USDT

Date: 2026-11-13
Status: accepted

## Context

The operator wants the bot to bring in about $50 a month. Backtests from 2025-09 to 2026-11
of the live strategy (LongBreakout60Exit30V1, 1% risk per trade, fixed stake) made about
$8.5 a month on 340 USDT once its single best trade (AKE, ~100x) is left out, and lost
money without its best three. Profit scales with capital. Raising the risk per trade would
also raise it, but a 22-trade losing streak at 2% risk would reach the equity floor.
Strategy work can add a few dollars a month at best.

The operator chose to add capital, starting at 1000 USDT, and to paper trade at that size
before depositing anything.

## Decision

- `dry_run_wallet` in `user_data/config.json` is 1000. Paper trading, research backtests
  and the gate all start from it.
- Risk per trade, stops, drawdown breakers and the equity floor are ratios of equity and
  do not change. The floor is now about 588 USDT.
- The gate's cached out-of-sample result for the live strategy is reused only when it was
  computed at the candidate's starting balance, because profits in USDT are compared.
- The readiness check's absolute tolerance for paper P&L below the backtest goes from 5 to
  15 USDT, keeping it at about 1.5% of the wallet.
- `config.live.json` is unchanged (115 USDT). Its limit is set to the deposited amount when
  the operator goes live, after readiness passes (ADR-0005).

## Consequences

- At the backtest's rate, 1000 USDT makes about $25 a month, not $50. That rate is an
  estimate: it rests on a few big runs and funding payments.
- The paper bot keeps its trade history. The 14 trades closed before the change (-17.3 USDT)
  were sized for 340 USDT. Percentages on the dashboard now use 1000 as the base.
- Gate results and journals before 2026-11-13 report USDT at 340 and cannot be compared
  directly with later ones.
