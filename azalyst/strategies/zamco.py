import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 55:
        return HOLD

    last = df.iloc[-1]

    bull_stack = (df["ema_9"] > df["ema_21"]).tail(3).all() and \
                 (df["ema_21"] > df["ema_50"]).tail(3).all()

    if bull_stack:
        pullback_to_ema21 = abs(last["close"] - last["ema_21"]) <= 0.3 * last["atr_14"]
        bullish_candle = last["close"] > last["open"]
        supertrend_bull = last["supertrend_dir"] == 1
        rsi_ok = last["rsi_14"] > 45

        if pullback_to_ema21 and bullish_candle and supertrend_bull and rsi_ok:
            return BUY

    bear_stack = (df["ema_9"] < df["ema_21"]).tail(3).all() and \
                 (df["ema_21"] < df["ema_50"]).tail(3).all()

    if bear_stack:
        bounce_to_ema21 = abs(last["close"] - last["ema_21"]) <= 0.3 * last["atr_14"]
        bearish_candle = last["close"] < last["open"]
        supertrend_bear = last["supertrend_dir"] == -1
        rsi_ok = last["rsi_14"] < 55

        if bounce_to_ema21 and bearish_candle and supertrend_bear and rsi_ok:
            return SELL

    return HOLD
