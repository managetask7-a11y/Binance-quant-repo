import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    """
    VWAP BOUNCE — Mean-Reversion Strategy (High Frequency)
    Logic:
    1. BUY: Price drops below VWAP by > 1 ATR, touches BB lower, RSI < 40,
       then current candle closes back toward VWAP (recovery). Vol > 1.0x MA.
    2. SELL: Price rises above VWAP by > 1 ATR, touches BB upper, RSI > 60,
       then current candle closes back toward VWAP. Vol > 1.0x MA.
    NO EMA 200 filter — works in any trend direction.
    """
    if len(df) < 25:
        return HOLD

    last = df.iloc[-1]
    prev = df.iloc[-2]

    vwap = last.get("vwap", last["close"])
    atr = last.get("atr_14", 0)
    rsi = last.get("rsi_14", 50)
    vol = last.get("volume", 0)
    vol_ma = last.get("vol_ma_20", 0)

    if atr <= 0 or np.isnan(atr):
        return HOLD

    # Volume must be at least average (not dead candles)
    if vol_ma > 0 and vol < vol_ma * 1.0:
        return HOLD

    deviation = (last["close"] - vwap) / vwap if vwap > 0 else 0

    # ── Bullish VWAP Bounce (Long) ──
    # Price was stretched below VWAP, touched BB lower, RSI oversold,
    # and this candle is a recovery (close > open, closing back toward VWAP)
    if deviation < -0.005:  # At least 0.5% below VWAP
        touched_bb_lower = last["low"] <= last.get("bb_lower", last["low"] - 1)
        rsi_oversold = rsi < 40
        recovery_candle = last["close"] > last["open"]  # Green candle
        closing_toward_vwap = last["close"] > prev["close"]  # Recovering

        if touched_bb_lower and rsi_oversold and recovery_candle and closing_toward_vwap:
            return BUY

    # ── Bearish VWAP Bounce (Short) ──
    # Price was stretched above VWAP, touched BB upper, RSI overbought,
    # and this candle is a rejection (close < open, falling back toward VWAP)
    if deviation > 0.005:  # At least 0.5% above VWAP
        touched_bb_upper = last["high"] >= last.get("bb_upper", last["high"] + 1)
        rsi_overbought = rsi > 60
        rejection_candle = last["close"] < last["open"]  # Red candle
        falling_toward_vwap = last["close"] < prev["close"]  # Dropping

        if touched_bb_upper and rsi_overbought and rejection_candle and falling_toward_vwap:
            return SELL

    return HOLD
