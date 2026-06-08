"""
JadeCap Liquidity Sweep Strategy (Enhanced)

Ported from Azalyst-FundingPips-Signals. Adapted for Binance crypto on 15m candles.

Logic:
  1. Identify key liquidity levels: Previous Day High/Low (PDH/PDL) using 
     the last 96 bars (= 1 day of 15m candles).
  2. Detect a liquidity sweep: price pierces above/below the level in the 
     last few bars, then pulls back.
  3. Confirm the reversal with either:
     - A Fair Value Gap (FVG): 3 candle imbalance where candle 1's high < candle 3's low (bullish)
     - A Market Structure Shift (MSS): price breaks the recent opposite extreme
  4. Enter the trade against the sweep direction.

Direction: Both Long & Short.
"""
import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD

SWEEP_LOOKBACK = 8      # How many bars back to look for the sweep
PDH_PDL_LOOKBACK = 96   # 1 day of 15m bars


def signal(df: pd.DataFrame) -> int:
    if len(df) < PDH_PDL_LOOKBACK + 10:
        return HOLD

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)
    last = n - 1

    # --- 1. Calculate Previous Day High / Low ---
    # Use bars from -PDH_PDL_LOOKBACK to -SWEEP_LOOKBACK as "previous session"
    session_slice = slice(last - PDH_PDL_LOOKBACK, last - SWEEP_LOOKBACK)
    pdh = float(np.max(high[session_slice]))
    pdl = float(np.min(low[session_slice]))

    current_close = close[last]

    # --- 2. Detect Bearish Sweep (price pierced above PDH, then fell back below) ---
    recent = slice(last - SWEEP_LOOKBACK, last)
    swept_high = any(high[i] > pdh for i in range(last - SWEEP_LOOKBACK, last))
    if swept_high and current_close < pdh:
        # Sweep peak for stop loss
        sweep_peak = max(high[i] for i in range(last - SWEEP_LOOKBACK, last + 1))

        # --- 3a. Confirm with bearish FVG ---
        if _bearish_fvg(high, low, last):
            return SELL

        # --- 3b. Confirm with MSS (break below recent lows) ---
        recent_low = min(low[i] for i in range(last - 4, last))
        if current_close < recent_low:
            return SELL

    # --- 2b. Detect Bullish Sweep (price pierced below PDL, then rose back above) ---
    swept_low = any(low[i] < pdl for i in range(last - SWEEP_LOOKBACK, last))
    if swept_low and current_close > pdl:
        sweep_trough = min(low[i] for i in range(last - SWEEP_LOOKBACK, last + 1))

        # --- 3a. Confirm with bullish FVG ---
        if _bullish_fvg(high, low, last):
            return BUY

        # --- 3b. Confirm with MSS (break above recent highs) ---
        recent_high = max(high[i] for i in range(last - 4, last))
        if current_close > recent_high:
            return BUY

    return HOLD


def _bearish_fvg(high, low, idx):
    """Bearish Fair Value Gap: candle[idx-2] low > candle[idx] high (gap down)."""
    if idx < 2:
        return False
    return low[idx - 2] > high[idx]


def _bullish_fvg(high, low, idx):
    """Bullish Fair Value Gap: candle[idx-2] high < candle[idx] low (gap up)."""
    if idx < 2:
        return False
    return high[idx - 2] < low[idx]
