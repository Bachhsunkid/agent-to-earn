import numpy as np
import pytest
from conftest import STRATEGY_CONFIG, make_ohlcv

from trend_regime_v1 import TrendRegimeV1


@pytest.fixture(scope="module")
def analyzed():
    strategy = TrendRegimeV1(dict(STRATEGY_CONFIG))
    df = make_ohlcv()
    meta = {"pair": "TEST/USDT:USDT"}
    df = strategy.populate_indicators(df, meta)
    df = strategy.populate_entry_trend(df, meta)
    return strategy.populate_exit_trend(df, meta)


def test_signal_columns_present(analyzed):
    warm = analyzed.iloc[TrendRegimeV1.startup_candle_count:]
    assert warm["stop_dist"].between(0, 1).all()
    assert set(warm["risk_mult"].unique()) <= {0.0, 0.5, 1.0}


def test_entries_only_in_active_regime(analyzed):
    entries = analyzed[(analyzed.get("enter_long") == 1) | (analyzed.get("enter_short") == 1)]
    assert len(entries) > 0
    assert (entries["risk_mult"] > 0).all()


def test_no_long_and_short_on_same_candle(analyzed):
    both = (analyzed.get("enter_long") == 1) & (analyzed.get("enter_short") == 1)
    assert not both.any()


def test_indicators_do_not_look_ahead():
    """Values at candle i must not change when later candles are removed."""
    strategy = TrendRegimeV1(dict(STRATEGY_CONFIG))
    full = make_ohlcv()
    meta = {"pair": "TEST/USDT:USDT"}
    cols = ["dc_high", "dc_low", "exit_high", "exit_low", "stop_dist", "risk_mult"]
    full_ind = strategy.populate_indicators(full.copy(), meta)
    for cut in (900, 1200):
        part = strategy.populate_indicators(full.iloc[:cut].copy(), meta)
        np.testing.assert_allclose(part[cols].iloc[-50:].to_numpy(dtype=float),
                                   full_ind[cols].iloc[cut - 50:cut].to_numpy(dtype=float),
                                   rtol=1e-6, equal_nan=True)
