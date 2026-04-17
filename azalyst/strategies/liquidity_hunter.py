import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD

def signal(df: pd.DataFrame) -> int:
    """
    LIQUIDITY HUNTER (Institutional Sweep)
    Logic:
    1. Bulls: Sweep below local swing low -> Recover -> MFI oversold/divergence.
    2. Bears: Sweep above local swing high -> Fall back -> MFI overbought/divergence.
    """
    if len(df) < 25:
        return HOLD

    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    swing_low = last["local_swing_low"]
    swing_high = last["local_swing_high"]
    mfi = last["mfi_14"]
    vol_ma = last.get("vol_ma_20", 0)
    
    # ── 1. Bullish Sweep (Long) ──
    # Low pierced the level recently
    swept_low = last["low"] < swing_low or prev["low"] < swing_low
    # Currently recovered back above the level (The Trap)
    recovered_low = last["close"] > swing_low
    # Money Flow suggests value (Institutions buying the dip)
    mfi_bottom = mfi < 35 # Oversold zone
    # Rejection quality
    bullish_rejection = last["close"] > last["open"] or last["close"] > prev["close"]
    
    if swept_low and recovered_low and mfi_bottom and bullish_rejection:
        # Final Volume Filter
        if last["volume"] > vol_ma * 1.2 if vol_ma > 0 else True:
            return BUY

    # ── 2. Bearish Sweep (Short) ──
    # High pierced the level
    swept_high = last["high"] > swing_high or prev["high"] > swing_high
    # Currently fallen back below the level
    fell_back_high = last["close"] < swing_high
    # Money Flow suggests peak (Institutions dumping)
    mfi_top = mfi > 65 # Overbought zone
    # Rejection quality
    bearish_rejection = last["close"] < last["open"] or last["close"] < prev["close"]

    if swept_high and fell_back_high and mfi_top and bearish_rejection:
        if last["volume"] > vol_ma * 1.2 if vol_ma > 0 else True:
            return SELL

    return HOLD
