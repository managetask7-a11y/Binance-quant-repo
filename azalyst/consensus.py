from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from azalyst.config import BUY, SELL, MIN_AGREEMENT, WEIGHTED_THRESHOLD, MULTI_WEIGHTS
from azalyst.strategies import MULTI_STRATEGIES
from azalyst.strategies.htf_filter import get_htf_trend
from azalyst.personalities import Personality, DEFAULT_PERSONALITY


def _check_entry_quality(df: pd.DataFrame, direction: int) -> bool:
    last = df.iloc[-1]

    adx = last.get("adx", 0)

    if not np.isnan(adx) and adx < 15:
        return False

    vol = last.get("volume", 0)
    vol_ma = last.get("vol_ma_20", 0)
    if vol_ma > 0 and vol < vol_ma * 0.6:
        return False

    rsi = last.get("rsi_14", 50)
    if not np.isnan(rsi):
        if direction == BUY and rsi > 70:
            return False
        elif direction == SELL and rsi < 30:
            return False

    return True


def multi_strategy_scan(
    df: pd.DataFrame,
    htf_df: Optional[pd.DataFrame] = None,
    personality: Optional[Personality] = None,
) -> Optional[dict]:
    if len(df) < 200:
        return None

    p = personality or DEFAULT_PERSONALITY

    htf_trend = 0
    if htf_df is not None and not htf_df.empty:
        htf_trend = get_htf_trend(htf_df)

    last = df.iloc[-1]

    buy_count = 0
    sell_count = 0
    buy_weight = 0.0
    sell_weight = 0.0
    buy_strategies = []
    sell_strategies = []

    for name, func in MULTI_STRATEGIES.items():
        sig = func(df)
        weight = p.weights.get(name, 0.0)

        if weight <= 0.0:
            continue

        adx_val = last.get("adx", 20)
        adx_50_val = last.get("adx_50", 20)

        if not np.isnan(adx_val) and adx_val > 25:
            weight *= 1.2

        if not np.isnan(adx_50_val) and adx_50_val < 10:
            weight *= 0.5

        if sig == BUY:
            if htf_trend == -1:
                continue
            if p.directional_bias == -1:
                continue
            buy_count += 1
            buy_weight += weight
            buy_strategies.append(name)
        elif sig == SELL:
            if htf_trend == 1:
                continue
            if p.directional_bias == 1:
                continue
            sell_count += 1
            sell_weight += weight
            sell_strategies.append(name)

    atr_val = df["atr_14"].iloc[-1]
    rsi = last.get("rsi_14", 50)
    if np.isnan(atr_val) or atr_val <= 0:
        return None

    if buy_count >= p.min_agreement and buy_weight >= p.weighted_threshold and buy_count > sell_count:
        if htf_trend == -1:
            return None
        if not np.isnan(rsi) and rsi > 85:
            return None
        if not _check_entry_quality(df, BUY):
            return None

        return {
            "direction": BUY,
            "atr": float(atr_val),
            "signal": f"CONSENSUS({buy_count} agree, w={buy_weight:.1f})",
            "strategies": buy_strategies,
        }

    if sell_count >= p.min_agreement and sell_weight >= p.weighted_threshold and sell_count > buy_count:
        if htf_trend == 1:
            return None
        if not np.isnan(rsi) and rsi < 15:
            return None
        if not _check_entry_quality(df, SELL):
            return None

        return {
            "direction": SELL,
            "atr": float(atr_val),
            "signal": f"CONSENSUS({sell_count} agree, w={sell_weight:.1f})",
            "strategies": sell_strategies,
        }

    return None
