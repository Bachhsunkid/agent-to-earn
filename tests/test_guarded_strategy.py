from datetime import UTC, datetime

import pytest
from conftest import STRATEGY_CONFIG, FakeDataProvider, FakeTrade, FakeWallets

import guarded_strategy as gs
from guarded_strategy import GuardedStrategy

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Probe(GuardedStrategy):
    def populate_indicators(self, dataframe, metadata):
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        return dataframe


def make_probe(row=None, equity=340.0, starting=340.0) -> Probe:
    strategy = Probe(dict(STRATEGY_CONFIG))
    strategy.dp = FakeDataProvider(row)
    strategy.wallets = FakeWallets(equity, starting)
    return strategy


def lev(strategy, max_leverage=125.0):
    return strategy.leverage("BTC/USDT:USDT", NOW, 100.0, 1.0, max_leverage, None, "long")


def stake(strategy, leverage, min_stake=1.0, max_stake=10_000.0):
    return strategy.custom_stake_amount("BTC/USDT:USDT", NOW, 100.0, 50.0, min_stake, max_stake,
                                        leverage, None, "long")


# --- subclass restrictions ---------------------------------------------------

@pytest.mark.parametrize("member", sorted(gs.GUARDED_MEMBERS))
def test_subclass_cannot_override_guarded_member(member):
    with pytest.raises(TypeError, match="guarded members"):
        type("Bad", (Probe,), {member: None})


@pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1d"])
def test_subclass_timeframe_must_be_allowed(timeframe):
    with pytest.raises(TypeError, match="timeframe"):
        type("Bad", (Probe,), {"timeframe": timeframe})


def test_subclass_may_define_signal_members():
    cls = type("Ok", (Probe,), {"timeframe": "4h", "startup_candle_count": 300,
                                "minimal_roi": {"0": 0.5}})
    assert cls.timeframe == "4h"


def test_fixed_risk_attributes():
    assert Probe.stoploss == -gs.STOPLOSS_RATIO
    assert Probe.can_short is True
    assert Probe.position_adjustment_enable is False
    assert Probe.use_custom_stoploss is False
    assert Probe.trailing_stop is False


# --- leverage ----------------------------------------------------------------

def test_leverage_capped_at_max_when_stop_is_tight():
    assert lev(make_probe({"stop_dist": 0.001})) == gs.MAX_LEVERAGE


def test_leverage_follows_stop_distance():
    assert lev(make_probe({"stop_dist": 0.04})) == pytest.approx(gs.STOPLOSS_RATIO / 0.04)


def test_leverage_respects_exchange_max():
    assert lev(make_probe({"stop_dist": 0.01}), max_leverage=3.0) == 3.0


def test_leverage_never_below_one():
    assert lev(make_probe({"stop_dist": 0.9})) == 1.0


@pytest.mark.parametrize("row", [None, {}, {"stop_dist": float("nan")}, {"stop_dist": "bad"}])
def test_leverage_uses_default_stop_when_signal_missing(row):
    assert lev(make_probe(row)) == pytest.approx(gs.STOPLOSS_RATIO / gs.DEFAULT_STOP_DISTANCE)


@pytest.mark.parametrize("stop_dist", [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5])
def test_price_stop_never_tighter_than_signal_and_far_from_liquidation(stop_dist):
    leverage = lev(make_probe({"stop_dist": stop_dist}))
    price_stop = gs.STOPLOSS_RATIO / leverage
    assert leverage <= gs.MAX_LEVERAGE
    assert price_stop >= min(max(stop_dist, gs.MIN_STOP_DISTANCE), gs.MAX_STOP_DISTANCE) - 1e-12
    # Isolated liquidation sits roughly 1/leverage away; the stop must hit well before it.
    assert price_stop <= 0.5 * (1 / leverage)


# --- position size -----------------------------------------------------------

def test_stake_matches_risk_budget(open_trades):
    strategy = make_probe({"stop_dist": 0.02, "risk_mult": 1.0})
    expected = 340 * gs.BASE_RISK_PER_TRADE / gs.STOPLOSS_RATIO
    assert stake(strategy, 10.0) == pytest.approx(expected)


def test_loss_at_stop_never_exceeds_max_risk(open_trades):
    for mult in (0.1, 0.5, 1.0, 5.0):
        strategy = make_probe({"risk_mult": mult})
        assert stake(strategy, 10.0) * gs.STOPLOSS_RATIO <= 340 * gs.MAX_RISK_PER_TRADE + 1e-9


def test_risk_mult_scales_stake(open_trades):
    full = stake(make_probe({"risk_mult": 1.0}), 5.0)
    half = stake(make_probe({"risk_mult": 0.5}), 5.0)
    assert half == pytest.approx(full / 2)


@pytest.mark.parametrize("mult", [0.0, -1.0])
def test_zero_regime_means_no_trade(open_trades, mult):
    assert stake(make_probe({"risk_mult": mult}), 5.0) == 0.0


def test_missing_regime_uses_default(open_trades):
    expected = 340 * gs.BASE_RISK_PER_TRADE * gs.DEFAULT_RISK_MULT / gs.STOPLOSS_RATIO
    assert stake(make_probe({}), 5.0) == pytest.approx(expected)


def test_stake_below_exchange_minimum_is_skipped(open_trades):
    assert stake(make_probe({"risk_mult": 1.0}), 10.0, min_stake=1_000.0) == 0.0


def test_stake_capped_by_max_stake(open_trades):
    assert stake(make_probe({"risk_mult": 1.0}), 10.0, max_stake=5.0) == 5.0


def test_account_leverage_cap_limits_new_stake(open_trades):
    # 3300 of 3400 allowed notional already used -> 100 notional left -> 10 margin at 10x.
    open_trades.append(FakeTrade(stake_amount=330.0, leverage=10.0))
    assert stake(make_probe({"risk_mult": 1.0}), 10.0) == pytest.approx(10.0)


def test_account_leverage_cap_blocks_when_full(open_trades):
    open_trades.append(FakeTrade(stake_amount=400.0, leverage=10.0))
    assert stake(make_probe({"risk_mult": 1.0}), 10.0) == 0.0


# --- equity floor ------------------------------------------------------------

def confirm(strategy):
    return strategy.confirm_trade_entry("BTC/USDT:USDT", "market", 1.0, 100.0, "GTC", NOW, None,
                                        "long")


def test_entry_allowed_above_equity_floor():
    assert confirm(make_probe(equity=250.0, starting=340.0)) is True


def test_entry_refused_below_equity_floor():
    assert confirm(make_probe(equity=199.0, starting=340.0)) is False


def test_equity_floor_scales_with_starting_balance():
    assert confirm(make_probe(equity=60.0, starting=115.0)) is False
    assert confirm(make_probe(equity=80.0, starting=115.0)) is True


def test_equity_floor_ignored_without_starting_balance():
    assert confirm(make_probe(equity=10.0, starting=0.0)) is True


# --- protections ---------------------------------------------------------------

def test_drawdown_breakers_cover_day_week_month():
    breakers = {(p["lookback_period"], p["max_allowed_drawdown"])
                for p in make_probe().protections if p["method"] == "MaxDrawdown"}
    assert breakers == {(1440, 0.05), (10080, 0.10), (43200, 0.20)}
    assert all(p.get("calculation_mode") == "equity"
               for p in make_probe().protections if p["method"] == "MaxDrawdown")


def test_cooldown_present():
    methods = {p["method"] for p in make_probe().protections}
    assert "CooldownPeriod" in methods
