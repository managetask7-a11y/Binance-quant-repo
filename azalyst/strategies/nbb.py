import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 25:
        return HOLD

    last = df.iloc[-1]
    prev = df.iloc[-2]

    bullish_engulfing = (last["close"] > last["open"]) and \
                        (prev["close"] < prev["open"]) and \
                        (last["close"] > prev["open"]) and \
                        (last["open"] < prev["close"])

    body_size = abs(last["close"] - last["open"])
    lower_wick = min(last["close"], last["open"]) - last["low"]
    is_hammer = lower_wick > 2 * body_size and last["close"] > last["open"]

    if bullish_engulfing or is_hammer:
        in_demand = last["close"] > df["ema_20"].iloc[-1]
        volume_ok = last["volume"] > 1.2 * last["vol_ma_20"]

        if in_demand and volume_ok:
            return BUY

    bearish_engulfing = (last["close"] < last["open"]) and \
                        (prev["close"] > prev["open"]) and \
                        (last["close"] < prev["open"]) and \
                        (last["open"] > prev["close"])

    upper_wick = last["high"] - max(last["close"], last["open"])
    is_inv_hammer = upper_wick > 2 * body_size and last["close"] < last["open"]

    if bearish_engulfing or is_inv_hammer:
        in_supply = last["close"] < df["ema_20"].iloc[-1]
        volume_ok = last["volume"] > 1.2 * last["vol_ma_20"]

        if in_supply and volume_ok:
            return SELL

    return HOLD
