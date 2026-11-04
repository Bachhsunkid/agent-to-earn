"""Sanity checks for whatever strategy is live, so a gate promotion never breaks the suite."""

import importlib.util
import json

import numpy as np
import pytest
from conftest import ROOT, STRATEGY_CONFIG, make_ohlcv

from guarded_strategy import GuardedStrategy

LIVE = ROOT / "user_data" / "strategies" / "live"
META = {"pair": "TEST/USDT:USDT"}


def live_class() -> type[GuardedStrategy]:
    name = json.loads((ROOT / "user_data" / "config.strategy.json").read_text())["strategy"]
    for path in LIVE.glob("*.py"):
        spec = importlib.util.spec_from_file_location(f"live_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if isinstance(getattr(module, name, None), type):
            return getattr(module, name)
    raise AssertionError(f"live strategy {name} not found in {LIVE}")


@pytest.fixture(scope="module")
def strategy_cls():
    return live_class()


@pytest.fixture(scope="module")
def analyzed(strategy_cls):
    strategy = strategy_cls(dict(STRATEGY_CONFIG))
    df = strategy.populate_indicators(make_ohlcv(), META)
    df = strategy.populate_entry_trend(df, META)
    return strategy.populate_exit_trend(df, META)


def test_live_strategy_is_guarded(strategy_cls):
    assert issubclass(strategy_cls, GuardedStrategy)


def test_signal_columns_present(strategy_cls, analyzed):
    warm = analyzed.iloc[strategy_cls.startup_candle_count:]
    assert warm["stop_dist"].between(0, 1).all()
    assert warm["risk_mult"].between(0, 1).all()


def test_entries_only_in_active_regime(analyzed):
    entries = analyzed[(analyzed.get("enter_long") == 1) | (analyzed.get("enter_short") == 1)]
    assert len(entries) > 0
    assert (entries["risk_mult"] > 0).all()


def test_no_long_and_short_on_same_candle(analyzed):
    both = (analyzed.get("enter_long") == 1) & (analyzed.get("enter_short") == 1)
    assert not both.any()


def test_indicators_do_not_look_ahead(strategy_cls):
    """Values at candle i must not change when later candles are removed."""
    strategy = strategy_cls(dict(STRATEGY_CONFIG))
    full = make_ohlcv()
    full_ind = strategy.populate_indicators(full.copy(), META)
    cols = [c for c in full_ind.select_dtypes("number").columns if c not in full.columns]
    for cut in (900, 1200):
        part = strategy.populate_indicators(full.iloc[:cut].copy(), META)
        np.testing.assert_allclose(part[cols].iloc[-50:].to_numpy(dtype=float),
                                   full_ind[cols].iloc[cut - 50:cut].to_numpy(dtype=float),
                                   rtol=1e-6, equal_nan=True)
