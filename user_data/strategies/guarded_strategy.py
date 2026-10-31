"""Risk guardrails shared by every strategy this bot runs.

Owned by the human operator. The research agent only writes subclasses that
provide signals: indicators, entries, exits and two per-candle columns:

- ``stop_dist``: desired stop distance as a fraction of price (e.g. 0.02 = 2%).
- ``risk_mult``: regime multiplier in [0, 1]; 0 means stand aside.

Every risk decision (leverage, position size, stop, circuit breakers) lives here,
and ``__init_subclass__`` rejects subclasses that try to override it.

Sizing model: the stop always costs ``STOPLOSS_RATIO`` of the stake (margin).
Leverage is chosen so that this loss happens at ``stop_dist`` away from entry,
and the stake is chosen so that this loss equals the risk budget. Leverage
therefore only changes how much margin is locked, not how much can be lost.
"""

import logging
import math
from datetime import datetime
from typing import Any

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

logger = logging.getLogger(__name__)

MAX_LEVERAGE = 10.0
# Total open notional across all trades, as a multiple of equity.
MAX_ACCOUNT_LEVERAGE = 10.0
# Fraction of equity lost when a stop is hit, at risk_mult = 1.
BASE_RISK_PER_TRADE = 0.01
MAX_RISK_PER_TRADE = 0.02
# Loss on the stake when the stop is hit (freqtrade's leveraged "risk on trade").
STOPLOSS_RATIO = 0.20
MIN_STOP_DISTANCE = 0.005
MAX_STOP_DISTANCE = STOPLOSS_RATIO
DEFAULT_STOP_DISTANCE = 0.03
DEFAULT_RISK_MULT = 0.5
# Stop opening trades once equity falls below this share of the starting balance ($200 of $340).
EQUITY_FLOOR_RATIO = 200 / 340
ALLOWED_TIMEFRAMES = frozenset({"1h", "2h", "4h"})

GUARDED_MEMBERS = frozenset({
    "__init__",
    "INTERFACE_VERSION",
    "can_short",
    "stoploss",
    "use_custom_stoploss",
    "custom_stoploss",
    "trailing_stop",
    "trailing_stop_positive",
    "trailing_stop_positive_offset",
    "trailing_only_offset_is_reached",
    "leverage",
    "custom_stake_amount",
    "confirm_trade_entry",
    "protections",
    "position_adjustment_enable",
    "max_entry_position_adjustment",
    "adjust_trade_position",
    "order_types",
    "order_time_in_force",
})


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(value):
        return default
    return min(max(value, low), high)


class GuardedStrategy(IStrategy):
    INTERFACE_VERSION = 3

    can_short = True
    stoploss = -STOPLOSS_RATIO
    use_custom_stoploss = False
    trailing_stop = False
    position_adjustment_enable = False
    # Exits come from signals and the stop, not from ROI targets.
    minimal_roi = {"0": 100.0}
    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 250

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        overridden = sorted(GUARDED_MEMBERS & set(vars(cls)))
        if overridden:
            raise TypeError(f"{cls.__name__} must not override guarded members: {', '.join(overridden)}")
        if cls.timeframe not in ALLOWED_TIMEFRAMES:
            raise TypeError(f"{cls.__name__}.timeframe must be one of {sorted(ALLOWED_TIMEFRAMES)}")

    @property
    def protections(self) -> list[dict]:
        return [
            # No StoplossGuard: with ~30% win rate trend strategies it blocked most
            # entries and turned a +38% in-sample backtest into -16%.
            {"method": "CooldownPeriod", "stop_duration": 60},
            # Daily / weekly / monthly drawdown breakers.
            {"method": "MaxDrawdown", "lookback_period": 1440, "trade_limit": 1,
             "stop_duration": 1440, "max_allowed_drawdown": 0.05, "calculation_mode": "equity"},
            {"method": "MaxDrawdown", "lookback_period": 10080, "trade_limit": 1,
             "stop_duration": 4320, "max_allowed_drawdown": 0.10, "calculation_mode": "equity"},
            {"method": "MaxDrawdown", "lookback_period": 43200, "trade_limit": 1,
             "stop_duration": 10080, "max_allowed_drawdown": 0.20, "calculation_mode": "equity"},
        ]

    def _last_candle(self, pair: str) -> Any:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return {}
        return df.iloc[-1]

    def _stop_distance(self, pair: str) -> float:
        return _clamp(self._last_candle(pair).get("stop_dist"),
                      MIN_STOP_DISTANCE, MAX_STOP_DISTANCE, DEFAULT_STOP_DISTANCE)

    def _risk_mult(self, pair: str) -> float:
        return _clamp(self._last_candle(pair).get("risk_mult"), 0.0, 1.0, DEFAULT_RISK_MULT)

    def _equity(self) -> float:
        return float(self.wallets.get_total_stake_amount())

    def _open_notional(self) -> float:
        return sum(t.stake_amount * t.leverage for t in Trade.get_trades_proxy(is_open=True))

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        wanted = STOPLOSS_RATIO / self._stop_distance(pair)
        return float(max(1.0, min(wanted, MAX_LEVERAGE, max_leverage)))

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        equity = self._equity()
        risk = min(BASE_RISK_PER_TRADE * self._risk_mult(pair), MAX_RISK_PER_TRADE)
        stake = equity * risk / STOPLOSS_RATIO
        headroom = MAX_ACCOUNT_LEVERAGE * equity - self._open_notional()
        stake = min(stake, max(headroom, 0.0) / max(leverage, 1.0), max_stake)
        if stake <= 0 or (min_stake and stake < min_stake):
            # Taking min_stake instead would exceed the risk budget.
            return 0.0
        return stake

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str | None,
                            side: str, **kwargs) -> bool:
        starting = float(self.wallets.get_starting_balance())
        equity = self._equity()
        if starting > 0 and equity < starting * EQUITY_FLOOR_RATIO:
            logger.warning("Equity floor hit (%.2f < %.2f), refusing %s entry on %s",
                           equity, starting * EQUITY_FLOOR_RATIO, side, pair)
            return False
        return True
