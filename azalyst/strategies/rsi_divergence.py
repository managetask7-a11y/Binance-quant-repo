import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    """
    RSI HIDDEN DIVERGENCE — Trend Continuation Strategy
    Logic:
    1. Bullish Hidden Div: Price makes HIGHER low (uptrend intact),
       but RSI makes LOWER low (momentum dip = buying opportunity).
       EMA 9 > EMA 21 confirms uptrend.
    2. Bearish Hidden Div: Price makes LOWER high (downtrend intact),
       but RSI makes HIGHER high (momentum spike = shorting opportunity).
       EMA 9 < EMA 21 confirms downtrend.
    This catches mid-trend pullback entries.
    """
    if len(df) < 25:
        return HOLD

    last = df.iloc[-1]

    ema_9 = last.get("ema_9", last["close"])
    ema_21 = last.get("ema_21", last["close"])
    rsi = last.get("rsi_14", 50)
    vol = last.get("volume", 0)
    vol_ma = last.get("vol_ma_20", 0)

    if np.isnan(rsi):
        return HOLD

    # Need decent volume
    if vol_ma > 0 and vol < vol_ma * 0.8:
        return HOLD

    # Compare recent 5-bar window vs previous 5-bar window
    recent = df.iloc[-6:-1]   # bars -6 to -2
    current = df.iloc[-1:]    # current bar

    prev_window = df.iloc[-12:-6]  # bars -12 to -7

    if len(prev_window) < 5 or len(recent) < 5:
        return HOLD

    # Price lows and highs
    recent_price_low = recent["low"].min()
    prev_price_low = prev_window["low"].min()
    recent_price_high = recent["high"].max()
    prev_price_high = prev_window["high"].max()

    # RSI lows and highs
    recent_rsi_low = recent["rsi_14"].min()
    prev_rsi_low = prev_window["rsi_14"].min()
    recent_rsi_high = recent["rsi_14"].max()
    prev_rsi_high = prev_window["rsi_14"].max()

    if any(np.isnan(x) for x in [recent_rsi_low, prev_rsi_low, recent_rsi_high, prev_rsi_high]):
        return HOLD

    # ── Bullish Hidden Divergence (Long) ──
    # Price: higher low (uptrend), RSI: lower low (momentum dip)
    price_higher_low = recent_price_low > prev_price_low
    rsi_lower_low = recent_rsi_low < prev_rsi_low

    if price_higher_low and rsi_lower_low:
        # Confirm uptrend: EMA 9 > EMA 21
        uptrend = ema_9 > ema_21
        # Current candle is bullish
        bullish_candle = last["close"] > last["open"]
        # RSI not extreme
        rsi_ok = 30 < rsi < 65

        if uptrend and bullish_candle and rsi_ok:
            return BUY

    # ── Bearish Hidden Divergence (Short) ──
    # Price: lower high (downtrend), RSI: higher high (momentum spike)
    price_lower_high = recent_price_high < prev_price_high
    rsi_higher_high = recent_rsi_high > prev_rsi_high

    if price_lower_high and rsi_higher_high:
        # Confirm downtrend: EMA 9 < EMA 21
        downtrend = ema_9 < ema_21
        # Current candle is bearish
        bearish_candle = last["close"] < last["open"]
        # RSI not extreme
        rsi_ok = 35 < rsi < 70

        if downtrend and bearish_candle and rsi_ok:
            return SELL

    return HOLD
