import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 25:
        return HOLD

    last = df.iloc[-1]
    prev = df.iloc[-2]

    prior_low = df["low"].tail(20).iloc[:-1].min()
    sweep_low = last["low"] < prior_low and last["close"] > prior_low

    bullish_engulfing = last["close"] > last["open"] and \
                        prev["close"] < prev["open"] and \
                        last["close"] > prev["open"]

    pin_bar_low = (min(last["close"], last["open"]) - last["low"]) > \
                  2 * abs(last["close"] - last["open"])

    if sweep_low:
        ema_ok = last["ema_9"] > last["ema_20"] and last["close"] > df["ema_50"].iloc[-1]
        rsi_ok = last["rsi_14"] >= 40

        if (bullish_engulfing or pin_bar_low) and ema_ok and rsi_ok:
            return BUY

    prior_high = df["high"].tail(20).iloc[:-1].max()
    sweep_high = last["high"] > prior_high and last["close"] < prior_high

    bearish_engulfing = last["close"] < last["open"] and \
                        prev["close"] > prev["open"] and \
                        last["close"] < prev["open"]

    pin_bar_high = (last["high"] - max(last["close"], last["open"])) > \
                   2 * abs(last["close"] - last["open"])

    if sweep_high:
        ema_ok = last["ema_9"] < last["ema_20"] and last["close"] < df["ema_50"].iloc[-1]
        rsi_ok = last["rsi_14"] <= 60

        if (bearish_engulfing or pin_bar_high) and ema_ok and rsi_ok:
            return SELL

    return HOLD
