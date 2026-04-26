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
    
    # Use the established levels BEFORE this candle started
    level_low = prev["local_swing_low"]
    level_high = prev["local_swing_high"]
    mfi = last["mfi_14"]
    vol_ma = last.get("vol_ma_20", 0)
    
    # ── 1. Bullish Sweep (Long) ──
    # Low pierced the previous established level in the last 3 bars
    swept_low = any(df.iloc[-i]["low"] < level_low for i in range(1, 4))
    # Currently recovered back above the level (The Trap)
    recovered_low = last["close"] > level_low
    # Money Flow suggests value
    mfi_bottom = mfi < 35 
    # Rejection quality
    bullish_rejection = last["close"] > last["open"] or last["conviction"] > 0.6
    
    if swept_low and recovered_low and mfi_bottom and bullish_rejection:
        return BUY

    # ── 2. Bearish Sweep (Short) ──
    # High pierced the previous established level in the last 3 bars
    swept_high = any(df.iloc[-i]["high"] > level_high for i in range(1, 4))
    # Currently fallen back below the level
    fell_back_high = last["close"] < level_high
    # Money Flow suggests peak
    mfi_top = mfi > 65 
    # Rejection quality
    bearish_rejection = last["close"] < last["open"] or last["conviction"] < 0.4

    if swept_high and fell_back_high and mfi_top and bearish_rejection:
        if last["volume"] > vol_ma * 1.2 if vol_ma > 0 else True:
            return SELL

    return HOLD
