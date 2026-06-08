"""
5 EMA Mean Reversion / Alert Candle Break Strategy

Ported from Azalyst-FundingPips-Signals. Adapted for Binance crypto on 15m candles.

Logic:
  SELL setup: An "alert candle" closes ABOVE the 5 EMA and its LOW does not touch
  the EMA. When a later candle breaks the alert candle's low -> SHORT.

  BUY setup: An "alert candle" closes BELOW the 5 EMA and its HIGH does not touch
  the EMA. When a later candle breaks the alert candle's high -> LONG.

  The most recent closed bar must be the trigger bar (so each break fires once).
  ATR floor prevents micro-stops.
"""
import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD

LOOKBACK = 25
ATR_FLOOR_MULT = 0.6


def signal(df: pd.DataFrame) -> int:
    if len(df) < 30:
        return HOLD

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    ema5 = df["close"].ewm(span=5, adjust=False).mean().values
    atr = df.get("atr_14")
    if atr is None or np.isnan(atr.iloc[-1]) or atr.iloc[-1] <= 0:
        return HOLD

    atr_floor = ATR_FLOOR_MULT * float(atr.iloc[-1])
    n = len(df)
    last = n - 1

    # --- Check for SELL setup (alert candle above EMA5) ---
    sell_signal = _check_alert(close, high, low, ema5, last, "SELL", atr_floor)
    if sell_signal:
        return SELL

    # --- Check for BUY setup (alert candle below EMA5) ---
    buy_signal = _check_alert(close, high, low, ema5, last, "BUY", atr_floor)
    if buy_signal:
        return BUY

    return HOLD


def _check_alert(close, high, low, ema5, last, side, atr_floor):
    """Find the most recent active alert candle and check if the last bar triggers it."""
    alert = None
    for i in range(last - 1, max(0, last - LOOKBACK), -1):
        if side == "SELL":
            # Alert: closes above EMA5 and low doesn't touch EMA5
            is_alert = close[i] > ema5[i] and low[i] > ema5[i]
        else:
            # Alert: closes below EMA5 and high doesn't touch EMA5
            is_alert = close[i] < ema5[i] and high[i] < ema5[i]

        if is_alert:
            # Check if already triggered between alert and the bar before last
            triggered = False
            for j in range(i + 1, last):
                if side == "SELL" and low[j] < low[i]:
                    triggered = True
                    break
                if side == "BUY" and high[j] > high[i]:
                    triggered = True
                    break
            if not triggered:
                alert = i
            break

    if alert is None:
        return False

    # --- Trigger check: does the last bar break the alert level? ---
    if side == "SELL":
        trigger_level = low[alert]
        if low[last] < trigger_level:
            risk = high[alert] - trigger_level
            if risk <= 0 or risk < atr_floor:
                return False
            return True
    else:
        trigger_level = high[alert]
        if high[last] > trigger_level:
            risk = trigger_level - low[alert]
            if risk <= 0 or risk < atr_floor:
                return False
            return True

    return False
