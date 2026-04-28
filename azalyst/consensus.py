from typing import Optional

import numpy as np
import pandas as pd

from azalyst.config import (
    BUY, SELL, MIN_AGREEMENT, WEIGHTED_THRESHOLD, MULTI_WEIGHTS,
)
from azalyst.strategies import MULTI_STRATEGIES
from azalyst.strategies.htf_filter import get_htf_trend


def _check_entry_quality(df: pd.DataFrame, direction: int) -> bool:
    """
    Entry confirmation gate — filters out weak signals.
    Keeps: ADX trending, Volume expansion, RSI guard.
    """
    last = df.iloc[-1]

    # ── 1. TREND STRENGTH GATE ──
    # Reduced floor to 15 to capture trends early.
    adx = last.get("adx", 0)
    adx_50 = last.get("adx_50", 0)
    
    if not np.isnan(adx) and adx < 15:
        return False

    # ── 3. VOLUME CONFIRMATION ──
    vol = last.get("volume", 0)
    vol_ma = last.get("vol_ma_20", 0)
    if vol_ma > 0 and vol < vol_ma * 0.6:
        return False

    # ── 4. RSI ZONE GUARD ──
    rsi = last.get("rsi_14", 50)
    if not np.isnan(rsi):
        if direction == BUY and rsi > 70:
            return False
        elif direction == SELL and rsi < 30:
            return False

    # ── 5. MARKET VELOCITY (Intelligence) ──
    # Don't trade if the price is 'flat' (last 4 bars < 0.2% move)
    if len(df) >= 5:
        recent_close = df["close"].iloc[-5]
        price_move = abs(last["close"] - recent_close) / recent_close
        if price_move < 0.002: # 0.2% floor
            return False

    # ── 6. EXPANSION GATE (Intelligence) ──
    # If bands are squeezed, require volume breakout
    bbw = last.get("bb_width", 0.1)
    if bbw < 0.05: # Extreme Squeeze
        vol = last.get("volume", 0)
        vol_ma = last.get("vol_ma_20", 0)
        if vol < vol_ma * 1.5: # Needs 150% volume to break a squeeze
            return False

    return True


def multi_strategy_scan(df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None, min_agreement: int = MIN_AGREEMENT) -> Optional[dict]:
    if len(df) < 200:
        return None
        
    htf_trend = 0
    if htf_df is not None and not htf_df.empty:
        htf_trend = get_htf_trend(htf_df)

    last = df.iloc[-1]
    # ── Regime Detection (BBW) ──
    # Narrow bands = Range/Sideways, Wide bands = Trend
    bbw = last.get("bb_width", 0.1)
    is_range = bbw < 0.08

    buy_count = 0
    sell_count = 0
    buy_weight = 0.0
    sell_weight = 0.0
    buy_strategies = []
    sell_strategies = []

    for name, func in MULTI_STRATEGIES.items():
        sig = func(df)
        weight = MULTI_WEIGHTS.get(name, 1.0)

        # ── Adaptive Regime Weighting ──
        adx_val = last.get("adx_14", 20)
        adx_50_val = last.get("adx_50", 20)
        
        # Boost during clear trends
        if adx_val > 15:
            weight *= 1.2
            
        # Penalize during directionless long-term markets
        if adx_50_val < 10:
            weight *= 0.5

        if is_range:
            if name in ["umar", "bb_trend", "nbb"]:
                weight *= 0.5 
            elif name in ["bnf", "wyckoff", "kane", "liquidity_hunter"]:
                weight *= 1.5 
        else:
            if name in ["umar", "bb_trend", "nbb", "band_rider"]:
                weight *= 1.5 
            elif name == "alpha_x":
                weight *= 2.0 # Boost Alpha-X during trend expansions

        if sig == BUY:
            buy_count += 1
            buy_weight += weight
            buy_strategies.append(name)
        elif sig == SELL:
            sell_count += 1
            sell_weight += weight
            sell_strategies.append(name)

    atr_val = df["atr_14"].iloc[-1]
    if np.isnan(atr_val) or atr_val <= 0:
        return None

    # ── ADAPTIVE CONFIDENCE ENGINE ──
    # Metrics: Trend (ADX), Volatility (BBW), Volume expansion
    adx_score = min(adx_val / 40.0, 1.0) # 40+ ADX is max trend
    bbw_score = min(bbw / 0.15, 1.0)     # 0.15+ BBW is high vol
    vol_ratio = last.get("volume", 0) / (last.get("vol_ma_20", 1) or 1)
    vol_score = min(vol_ratio / 2.0, 1.0) # 2x volume is max
    
    confidence = (adx_score * 0.4) + (bbw_score * 0.3) + (vol_score * 0.3)
    
    # ── Intelligence: Adaptive Strike Rules ──
    # High Confidence (>0.7) = Aggressive (2 agree, relaxed HTF)
    # Low Confidence (<0.4) = Conservative (3 agree, strict HTF)
    if confidence > 0.7:
        dynamic_min = 2
        htf_strict = False
    elif confidence < 0.4:
        dynamic_min = 3
        htf_strict = True
    else:
        dynamic_min = max(min_agreement, 2)
        htf_strict = True

    # ── Signal Generation ──
    if buy_count >= dynamic_min and buy_weight >= WEIGHTED_THRESHOLD and buy_count > sell_count:
        # HTF Filter: Adaptive
        if htf_strict:
            if htf_trend != 1: return None # Must be strictly bullish
        else:
            if htf_trend == -1: return None # Just don't be strictly bearish

        return {
            "direction": BUY,
            "atr": float(atr_val),
            "signal": f"CONFIDENCE strike ({confidence:.2f})",
            "strategies": buy_strategies,
        }

    if sell_count >= dynamic_min and sell_weight >= WEIGHTED_THRESHOLD and sell_count > buy_count:
        # HTF Filter: Adaptive
        if htf_strict:
            if htf_trend != -1: return None # Must be strictly bearish
        else:
            if htf_trend == 1: return None # Just don't be strictly bullish
            
        return {
            "direction": SELL,
            "atr": float(atr_val),
            "signal": f"CONFIDENCE strike ({confidence:.2f})",
            "strategies": sell_strategies,
        }

    return None

