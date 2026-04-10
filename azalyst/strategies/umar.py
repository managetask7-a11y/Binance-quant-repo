import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 25:
        return HOLD

    last = df.iloc[-1]

    day_open = df.iloc[-24]["open"] if len(df) >= 24 else df.iloc[0]["open"]
    day_high = df["high"].tail(24).max()
    day_low = df["low"].tail(24).min()

    if last["close"] > day_high + 0.5 * last["atr_14"]:
        above_vwap = last["close"] > last["vwap"]
        ema_bullish = last["ema_9"] > last["ema_20"]
        volume_ok = last["volume"] > 1.5 * last["vol_ma_20"]

        if above_vwap and ema_bullish and volume_ok:
            return BUY

    if last["close"] < day_low - 0.5 * last["atr_14"]:
        below_vwap = last["close"] < last["vwap"]
        ema_bearish = last["ema_9"] < last["ema_20"]
        volume_ok = last["volume"] > 1.5 * last["vol_ma_20"]

        if below_vwap and ema_bearish and volume_ok:
            return SELL

    return HOLD
