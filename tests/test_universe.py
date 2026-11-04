from datetime import date

import pandas as pd

from build_universe import daily_members, eligible, load_quote_volume


def market(base, **overrides):
    m = {"swap": True, "linear": True, "active": True, "quote": "USDT", "settle": "USDT",
         "base": base, "info": {"contractType": "PERPETUAL"}}
    m.update(overrides)
    return m


def test_eligible_keeps_active_usdt_perpetuals():
    markets = {
        "BTC/USDT:USDT": market("BTC"),
        "USDC/USDT:USDT": market("USDC"),
        "OLD/USDC:USDC": market("OLD", quote="USDC", settle="USDC"),
        "DEAD/USDT:USDT": market("DEAD", active=False),
        "QTR/USDT:USDT": market("QTR", info={"contractType": "CURRENT_QUARTER"}),
        "NEW/USDT:USDT": market("NEW"),
    }
    assert eligible(markets) == ["BTC/USDT:USDT", "NEW/USDT:USDT"]


def volumes(rows: dict[str, list[float]], start="2025-08-01") -> pd.DataFrame:
    n = len(next(iter(rows.values())))
    return pd.DataFrame(rows, index=pd.date_range(start, periods=n, freq="D", tz="UTC"))


def test_each_day_ranks_only_earlier_days():
    # B overtakes A on day 3 (index 2); the list for day 3 must not know that yet.
    qv = volumes({"A": [10, 10, 10, 10, 10], "B": [1, 1, 100, 100, 100], "C": [5, 5, 5, 5, 5]})
    members = daily_members(qv, top=1, lookback=2, start=date(2025, 8, 1), end=date(2025, 8, 6))
    assert members == {"2025-08-01": [], "2025-08-02": [], "2025-08-03": ["A"],
                       "2025-08-04": ["B"], "2025-08-05": ["B"], "2025-08-06": ["B"]}


def test_pairs_need_a_full_lookback_and_lists_extend_to_today():
    # N lists from its second day; a missing day blocks it until the window is full again.
    qv = volumes({"A": [10, 10, 10, 10, 10], "N": [None, 50, 50, None, 50]})
    members = daily_members(qv, top=2, lookback=1, start=date(2025, 8, 2), end=date(2025, 8, 7))
    assert members["2025-08-02"] == ["A"]
    assert members["2025-08-03"] == ["A", "N"]
    assert members["2025-08-05"] == ["A"]
    assert members["2025-08-06"] == ["A", "N"]
    assert members["2025-08-07"] == []  # no candles for the 6th yet


def test_load_quote_volume_reads_daily_candles(tmp_path):
    pd.DataFrame({"date": pd.date_range("2025-08-01", periods=2, freq="D", tz="UTC"),
                  "close": [2.0, 3.0], "volume": [10.0, 20.0]}).to_feather(
        tmp_path / "BTC_USDT_USDT-1d-futures.feather")
    qv = load_quote_volume(["BTC/USDT:USDT", "GONE/USDT:USDT"], tmp_path)
    assert list(qv.columns) == ["BTC/USDT:USDT"] and qv["BTC/USDT:USDT"].tolist() == [20.0, 60.0]
