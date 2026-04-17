import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD
from azalyst.candlestick import is_hammer, is_inverted_hammer, is_bullish_engulfing, is_bearish_engulfing

def signal(df: pd.DataFrame) -> int:
    """
    Surgical BAND RIDER
    Logic:
    1. Breakout: Price was strictly ABOVE Upper Band recently.
    2. Separation: Price MUST have pulled back away from the band (Prev Low > Upper Band).
    3. Retest: Current Low touches BB Upper.
    4. Rejection: Strong Rejection pattern (Hammer or Bullish Engulfing) + Volume.
    """
    if len(df) < 10:
        return HOLD

    last = df.iloc[-1]
    prev1 = df.iloc[-2]
    
    # --- Indicators ---
    upper = last["bb_upper"]
    lower = last["bb_lower"]
    vol_ma = last.get("vol_ma_20", 0)
    
    # --- 1. Long (Buy) logic ---
    # Phase 1: Institutional Breakout (Must have been clearly above in recent history)
    was_above = any(df["high"].iloc[-5:-2] > df["bb_upper"].iloc[-5:-2])
    
    # Phase 2: Separation (The 'Come back' part)
    # Price must have been strictly above the band in the previous bar (The gap)
    is_separated = prev1["low"] > prev1["bb_upper"]
    
    # Phase 3: The Retest Touch
    is_touching = last["low"] <= upper and last["close"] >= upper
    
    # Phase 4: Rejection & Volume Confirmation
    rejection_up = is_hammer(last) or is_bullish_engulfing(last, prev1)
    vol_climax = last["volume"] > vol_ma * 1.2 if vol_ma > 0 else True
    
    if was_above and is_separated and is_touching and rejection_up and vol_climax:
        return BUY

    # --- 2. Short (Sell) logic ---
    # Phase 1: Breakout Below
    was_below = any(df["low"].iloc[-5:-2] < df["bb_lower"].iloc[-5:-2])
    
    # Phase 2: Separation
    is_separated_short = prev1["high"] < prev1["bb_lower"]
    
    # Phase 3: Retest Touch
    is_touching_short = last["high"] >= lower and last["close"] <= lower
    
    # Phase 4: Rejection
    rejection_down = is_inverted_hammer(last) or is_bearish_engulfing(last, prev1)
    
    if was_below and is_separated_short and is_touching_short and rejection_down and vol_climax:
        return SELL

    return HOLD
