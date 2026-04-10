import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 200:
        return HOLD

    last = df.iloc[-1]

    if last["rsi_9"] < 35:
        near_bb_lower = (last["close"] - last["bb_lower"]) <= last["atr_14"]
        below_vwap = last["close"] < last["vwap"]
        above_ema200 = last["close"] > last["ema_200"]

        if near_bb_lower and below_vwap and above_ema200:
            return BUY

    if last["rsi_9"] > 65:
        near_bb_upper = (last["bb_upper"] - last["close"]) <= last["atr_14"]
        above_vwap = last["close"] > last["vwap"]
        below_ema200 = last["close"] < last["ema_200"]

        if near_bb_upper and above_vwap and below_ema200:
            return SELL

    return HOLD
