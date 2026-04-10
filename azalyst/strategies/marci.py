import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 30:
        return HOLD

    last = df.iloc[-1]

    macd_accel_up = last["macd_hist_accel"] > 0 and last["macd_hist"] > 0
    adx_strong = last["adx"] >= 25 and last["adx"] > df["adx"].iloc[-2]
    atr_expanding = last["atr_14"] > df["atr_ma_20"].iloc[-1]
    above_vwap = last["close"] > last["vwap"]
    ema_bullish = last["ema_20"] > last["ema_50"]

    if macd_accel_up and adx_strong and atr_expanding and above_vwap and ema_bullish:
        return BUY

    macd_accel_down = last["macd_hist_accel"] < 0 and last["macd_hist"] < 0
    below_vwap = last["close"] < last["vwap"]
    ema_bearish = last["ema_20"] < last["ema_50"]

    if macd_accel_down and adx_strong and atr_expanding and below_vwap and ema_bearish:
        return SELL

    return HOLD
