"""
SMT Divergence Strategy (Smart Money Technique)

Ported from Azalyst-FundingPips-Signals. Adapted for Binance crypto.

Logic:
  Compares the current symbol's swing structure against BTC/USDT.
  
  Bearish SMT: BTC makes a Higher High, but the altcoin makes a Lower High
  -> SHORT the altcoin (it's showing relative weakness).

  Bullish SMT: BTC makes a Lower Low, but the altcoin makes a Higher Low
  -> LONG the altcoin (it's showing relative strength).

  The diverging pivot must be recent (within FRESH_BARS) to avoid stale signals.
  Uses swing detection with configurable strength.

NOTE: This strategy requires BTC data to compare against. The signal() function
uses only the current symbol's dataframe. The BTC comparison is done via the
swing highs/lows already present in the dataframe (local_swing_high/low).
Since we can't fetch BTC data inside a strategy, we approximate using the
symbol's own structure: we detect internal divergence between price making
new highs/lows and RSI/momentum failing to confirm (a structural proxy for
cross-asset divergence).
"""
import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD

FRESH_BARS = 12
SWING_WINDOW = 5


def signal(df: pd.DataFrame) -> int:
    """
    Detect hidden/regular divergence between price swings and RSI.
    This is the single-symbol adaptation of SMT divergence.
    """
    if len(df) < 60:
        return HOLD

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    rsi = df.get("rsi_14")

    if rsi is None:
        return HOLD

    rsi_vals = rsi.values

    # Find recent swing highs and swing lows
    swing_highs = _find_swings(high, SWING_WINDOW, kind="high")
    swing_lows = _find_swings(low, SWING_WINDOW, kind="low")

    n = len(df)

    # --- Bearish Divergence (price HH but RSI LH -> SHORT) ---
    if len(swing_highs) >= 2:
        sh1_idx, sh1_val = swing_highs[-2]
        sh2_idx, sh2_val = swing_highs[-1]
        # Must be recent
        if (n - 1 - sh2_idx) <= FRESH_BARS and sh2_idx > sh1_idx:
            price_hh = sh2_val > sh1_val
            rsi_lh = rsi_vals[sh2_idx] < rsi_vals[sh1_idx]
            if price_hh and rsi_lh:
                return SELL

    # --- Bullish Divergence (price LL but RSI HL -> LONG) ---
    if len(swing_lows) >= 2:
        sl1_idx, sl1_val = swing_lows[-2]
        sl2_idx, sl2_val = swing_lows[-1]
        # Must be recent
        if (n - 1 - sl2_idx) <= FRESH_BARS and sl2_idx > sl1_idx:
            price_ll = sl2_val < sl1_val
            rsi_hl = rsi_vals[sl2_idx] > rsi_vals[sl1_idx]
            if price_ll and rsi_hl:
                return BUY

    return HOLD


def _find_swings(data, window, kind="high"):
    """Find swing highs or lows using a rolling window approach."""
    swings = []
    for i in range(window, len(data) - window):
        if kind == "high":
            if data[i] == max(data[i - window:i + window + 1]):
                swings.append((i, data[i]))
        else:
            if data[i] == min(data[i - window:i + window + 1]):
                swings.append((i, data[i]))
    return swings
