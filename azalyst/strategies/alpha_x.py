import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD

def signal(df: pd.DataFrame) -> int:
    """
    ALPHA-X Professional Breakout-Pullback
    Logic from Azalyst Alpha-X (250% Annual Return)
    1. Breakout: Price closed ABOVE BB(200, 1.0).
    2. Pullback: Price retraced and touched the band.
    3. Trigger: Current close > Pullback close.
    """
    if len(df) < 5:
        return HOLD

    # Alpha-X Config Constants (Mirrored from main.py)
    MIN_BREAKOUT_PCT = 0.002
    MIN_BANDWIDTH_PCT = 0.008
    TOUCH_TOL = 0.0025 # 0.25%

    current = df.iloc[-1]
    pullback = df.iloc[-2]
    breakout = df.iloc[-3]

    # --- 1. Sideways / Sniper Filters (ALL must pass) ---
    bandwidth_pct = (current["bb200_upper"] - current["bb200_lower"]) / current["bb200_mid"]
    if bandwidth_pct < MIN_BANDWIDTH_PCT:
        return HOLD
    
    # Sniper: Candle Conviction & Body Ratio
    is_strong_body = current["body_ratio"] >= 0.5
    rsi_val = current.get("rsi_9", 50)
    
    # --- 2. Long Logic (Upper Band) ---
    # Step A: Meaningful Breakout (3 candles ago)
    breakout_distance = (breakout["close"] - breakout["bb200_upper"]) / breakout["bb200_upper"]
    
    # Step B: Pullback Touch (2 candles ago)
    tol_u = pullback["bb200_upper"] * TOUCH_TOL
    touched_upper = (
        pullback["low"] <= pullback["bb200_upper"] + tol_u
        and pullback["high"] >= pullback["bb200_upper"] - tol_u
        and pullback["close"] < breakout["close"] # Retracing
    )
    
    # Step C: Sniper Momentum Trigger (Current candle)
    # Price must be above middle band (SMA 200)
    is_above_mid = current["close"] > current["bb200_mid"]
    is_bullish = current["close"] > current["open"]
    momentum_up = current["close"] > pullback["close"]
    rsi_safe_long = rsi_val < 70 # Not overbought
    
    if (breakout["close"] > breakout["bb200_upper"] and 
        breakout_distance >= MIN_BREAKOUT_PCT and 
        touched_upper and 
        momentum_up and 
        is_above_mid and
        is_strong_body and
        is_bullish and
        rsi_safe_long):
        return BUY

    # --- 3. Short Logic (Lower Band) ---
    # Step A: Meaningful Breakdown
    breakdown_distance = (breakout["bb200_lower"] - breakout["close"]) / breakout["bb200_lower"]

    # Step B: Bounce Touch
    tol_l = abs(pullback["bb200_lower"]) * TOUCH_TOL
    touched_lower = (
        pullback["high"] >= pullback["bb200_lower"] - tol_l
        and pullback["low"] <= pullback["bb200_lower"] + tol_l
        and pullback["close"] > breakout["close"] # Bouncing
    )

    # Step C: Sniper Momentum Trigger
    is_below_mid = current["close"] < current["bb200_mid"]
    is_bearish = current["close"] < current["open"]
    momentum_down = current["close"] < pullback["close"]
    rsi_safe_short = rsi_val > 30 # Not oversold

    if (breakout["close"] < breakout["bb200_lower"] and 
        breakdown_distance >= MIN_BREAKOUT_PCT and 
        touched_lower and 
        momentum_down and 
        is_below_mid and
        is_strong_body and
        is_bearish and
        rsi_safe_short):
        return SELL

    return HOLD

    return HOLD

    return HOLD
