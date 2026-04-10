import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 30:
        return HOLD

    last = df.iloc[-1]

    recent_lows = df["low"].tail(20).min()
    recent_highs = df["high"].tail(20).max()

    sweep_low = last["low"] < recent_lows and last["close"] > recent_lows
    sweep_high = last["high"] > recent_highs and last["close"] < recent_highs

    bos_bullish = last["close"] > df["swing_high"].tail(10).min()
    bos_bearish = last["close"] < df["swing_low"].tail(10).max()

    if sweep_low or bos_bullish:
        in_demand = last["close"] > df["ema_20"].iloc[-1]
        rsi_ok = last["rsi_14"] >= 40
        atr_expanding = last["atr_14"] > df["atr_ma_20"].iloc[-1]

        if in_demand and rsi_ok and atr_expanding:
            return BUY

    if sweep_high or bos_bearish:
        in_supply = last["close"] < df["ema_20"].iloc[-1]
        rsi_ok = last["rsi_14"] <= 60
        atr_expanding = last["atr_14"] > df["atr_ma_20"].iloc[-1]

        if in_supply and rsi_ok and atr_expanding:
            return SELL

    return HOLD
