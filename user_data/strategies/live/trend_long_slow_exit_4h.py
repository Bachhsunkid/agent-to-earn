import talib.abstract as ta
from pandas import DataFrame

from guarded_strategy import GuardedStrategy


class TrendLongSlowExit4hV1(GuardedStrategy):
    """TrendLong4hV1 entries with a slower exit: the 20-bar Donchian low instead of the 10-bar.

    The live strategy's profit comes from a few long runs (and the funding they collect),
    while the 10-bar exit cuts them at the first pullback. A wider exit lets winners run.
    Entries, stop and regime are unchanged.
    """

    timeframe = "4h"
    startup_candle_count = 250

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df["ema_fast"] = ta.EMA(df, timeperiod=50)
        df["ema_slow"] = ta.EMA(df, timeperiod=200)
        df["adx"] = ta.ADX(df, timeperiod=14)
        df["atr"] = ta.ATR(df, timeperiod=14)
        df["dc_high"] = df["high"].rolling(20).max().shift(1)
        df["exit_low"] = df["low"].rolling(20).min().shift(1)

        atr_pct = df["atr"] / df["close"]
        df["atr_rank"] = atr_pct.rolling(500, min_periods=100).rank(pct=True)
        df["stop_dist"] = 2 * atr_pct
        df["risk_mult"] = 0.0
        df.loc[df["adx"] >= 20, "risk_mult"] = 0.5
        df.loc[(df["adx"] >= 30) & (df["atr_rank"] >= 0.5), "risk_mult"] = 1.0
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        active = (df["risk_mult"] > 0) & (df["volume"] > 0)
        trend_up = (df["close"] > df["ema_slow"]) & (df["ema_fast"] > df["ema_slow"])
        df.loc[active & trend_up & (df["close"] > df["dc_high"]),
               ["enter_long", "enter_tag"]] = (1, "breakout_long")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[df["close"] < df["exit_low"], ["exit_long", "exit_tag"]] = (1, "donchian_exit")
        return df
