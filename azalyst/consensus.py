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
            # HTF Filter: Ignore long signals if macro trend is bearish
            if htf_trend == -1:
                continue
            buy_count += 1
            buy_weight += weight
            buy_strategies.append(name)
        elif sig == SELL:
             # HTF Filter: Ignore short signals if macro trend is bullish
            if htf_trend == 1:
                continue
            sell_count += 1
            sell_weight += weight
            sell_strategies.append(name)

    atr_val = df["atr_14"].iloc[-1]
    rsi = last.get("rsi_14", 50)
    if np.isnan(atr_val) or atr_val <= 0:
        return None

    if buy_count >= min_agreement and buy_weight >= WEIGHTED_THRESHOLD and buy_count > sell_count:
        # HTF Filter: Ignore long signals if macro trend is bearish
        if htf_trend == -1: return None
        # RSI Guard: Only block at extreme exhaustion levels (>85)
        if not np.isnan(rsi) and rsi > 85: return None
        
        return {
            "direction": BUY,
            "atr": float(atr_val),
            "signal": f"CONSENSUS({buy_count} agree, w={buy_weight:.1f})",
            "strategies": buy_strategies,
        }

    if sell_count >= min_agreement and sell_weight >= WEIGHTED_THRESHOLD and sell_count > buy_count:
        # HTF Filter: Ignore short signals if macro trend is bullish
        if htf_trend == 1: return None
        # RSI Guard: Only block at extreme exhaustion levels (<15)
        if not np.isnan(rsi) and rsi < 15: return None

        return {
            "direction": SELL,
            "atr": float(atr_val),
            "signal": f"CONSENSUS({sell_count} agree, w={sell_weight:.1f})",
            "strategies": sell_strategies,
        }

    return None

