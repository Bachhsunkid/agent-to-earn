import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data" / "strategies"
for path in (STRATEGIES, STRATEGIES / "live", ROOT / "scripts", ROOT / "agent"):
    sys.path.insert(0, str(path))

STRATEGY_CONFIG = {"stake_currency": "USDT", "dry_run": True, "trading_mode": "futures"}
SECRET_ENV = ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "API_USERNAME", "API_PASSWORD", "CLAUDE_CODE_OAUTH_TOKEN")


@pytest.fixture(autouse=True)
def no_real_secrets(monkeypatch):
    """The gate runs the suite inside the research container: never use its real secrets."""
    for name in SECRET_ENV:
        monkeypatch.delenv(name, raising=False)


class FakeDataProvider:
    def __init__(self, row: dict | None):
        self.row = row

    def get_analyzed_dataframe(self, pair, timeframe):
        if self.row is None:
            return pd.DataFrame(), None
        return pd.DataFrame([self.row]), None


class FakeWallets:
    def __init__(self, equity: float = 340.0, starting: float = 340.0):
        self.equity = equity
        self.starting = starting

    def get_total_stake_amount(self):
        return self.equity

    def get_starting_balance(self):
        return self.starting


class FakeTrade:
    def __init__(self, stake_amount: float, leverage: float):
        self.stake_amount = stake_amount
        self.leverage = leverage


@pytest.fixture
def open_trades(monkeypatch):
    """Set the open trades seen by GuardedStrategy; empty by default."""
    import guarded_strategy

    trades: list[FakeTrade] = []
    monkeypatch.setattr(guarded_strategy.Trade, "get_trades_proxy",
                        staticmethod(lambda **kwargs: trades if kwargs.get("is_open") else []))
    return trades


def make_ohlcv(n: int = 1500, seed: int = 7) -> pd.DataFrame:
    """Synthetic hourly candles with alternating trend phases."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([-0.002, 0.0, 0.002], size=n // 100 + 1), 100)[:n]
    close = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.006, n)))
    spread = np.abs(rng.normal(0, 0.004, n)) * close
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC"),
        "open": open_,
        "high": np.maximum(open_, close) + spread,
        "low": np.minimum(open_, close) - spread,
        "close": close,
        "volume": rng.uniform(100, 1000, n),
    })
