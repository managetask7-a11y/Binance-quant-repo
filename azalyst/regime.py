from __future__ import annotations

from enum import Enum
import numpy as np
import pandas as pd


class MarketRegime(Enum):
    STRONG_UPTREND = "strong_uptrend"
    WEAK_UPTREND = "weak_uptrend"
    SIDEWAYS = "sideways"
    WEAK_DOWNTREND = "weak_downtrend"
    STRONG_DOWNTREND = "strong_downtrend"


_SMOOTHING_PERIOD = 6

_HYSTERESIS = {
    MarketRegime.STRONG_UPTREND:   {"enter": 0.40, "exit": 0.25},
    MarketRegime.WEAK_UPTREND:     {"enter": 0.15, "exit": -0.05},
    MarketRegime.SIDEWAYS:         {"enter": -0.10, "exit": 0.10},
    MarketRegime.WEAK_DOWNTREND:   {"enter": -0.40, "exit": -0.15},
    MarketRegime.STRONG_DOWNTREND: {"enter": -0.45, "exit": -0.25},
}


def _ema_stack_score(row: pd.Series) -> float:
    ema9 = row.get("ema_9", row["close"])
    ema21 = row.get("ema_21", row["close"])
    ema50 = row.get("ema_50", row["close"])
    ema200 = row.get("ema_200", row["close"])
    price = row["close"]

    if price > ema9 > ema21 > ema50 > ema200:
        return 1.0
    if price > ema21 > ema50 > ema200:
        return 0.7
    if price > ema50 > ema200:
        return 0.4
    if price < ema9 < ema21 < ema50 < ema200:
        return -1.0
    if price < ema21 < ema50 < ema200:
        return -0.7
    if price < ema50 < ema200:
        return -0.4
    return 0.0


def _adx_di_score(row: pd.Series) -> float:
    adx = row.get("adx", 20)
    pdi = row.get("pdi", 0)
    mdi = row.get("mdi", 0)

    if np.isnan(adx) or np.isnan(pdi) or np.isnan(mdi):
        return 0.0

    if adx < 18:
        return 0.0

    di_spread = pdi - mdi
    normalized = np.clip(di_spread / 40.0, -1.0, 1.0)

    if adx > 30:
        normalized *= 1.3

    return float(np.clip(normalized, -1.0, 1.0))


def _supertrend_score(row: pd.Series) -> float:
    st_dir = row.get("supertrend_dir", 0)
    if st_dir == 1:
        return 1.0
    elif st_dir == -1:
        return -1.0
    return 0.0


def _bbw_score(row: pd.Series) -> float:
    bbw = row.get("bb_width", 0.1)
    bbw_pct = row.get("bb200_squeeze", 0.5)

    if np.isnan(bbw) or np.isnan(bbw_pct):
        return 0.0

    if bbw_pct < 0.15:
        return 0.0
    if bbw_pct > 0.80:
        price = row["close"]
        ema50 = row.get("ema_50", price)
        if price > ema50:
            return 0.8
        else:
            return -0.8
    return 0.0


def _macd_slope_score(row: pd.Series) -> float:
    hist = row.get("macd_hist", 0)
    accel = row.get("macd_hist_accel", 0)

    if np.isnan(hist) or np.isnan(accel):
        return 0.0

    if hist > 0 and accel > 0:
        return 1.0
    if hist > 0 and accel <= 0:
        return 0.3
    if hist < 0 and accel < 0:
        return -1.0
    if hist < 0 and accel >= 0:
        return -0.3
    return 0.0


def _htf_score(htf_df: pd.DataFrame) -> float:
    if htf_df is None or htf_df.empty or len(htf_df) < 200:
        return 0.0

    last = htf_df.iloc[-1]

    if "ema_50" not in htf_df.columns or "ema_200" not in htf_df.columns:
        ema50 = htf_df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = htf_df["close"].ewm(span=200, adjust=False).mean().iloc[-1]
    else:
        ema50 = last["ema_50"]
        ema200 = last["ema_200"]

    price = last["close"]

    if price > ema200 and ema50 > ema200:
        return 1.0
    elif price < ema200 and ema50 < ema200:
        return -1.0
    return 0.0


def _raw_score_to_candidate(score: float) -> MarketRegime:
    if score > 0.40:
        return MarketRegime.STRONG_UPTREND
    if score > 0.12:
        return MarketRegime.WEAK_UPTREND
    if score > -0.12:
        return MarketRegime.SIDEWAYS
    if score > -0.40:
        return MarketRegime.WEAK_DOWNTREND
    return MarketRegime.STRONG_DOWNTREND


def _apply_hysteresis(candidate: MarketRegime, smoothed: float, current: MarketRegime) -> MarketRegime:
    if candidate == current:
        return current

    entry_thresh = _HYSTERESIS[candidate]["enter"]

    regime_order = [
        MarketRegime.STRONG_DOWNTREND,
        MarketRegime.WEAK_DOWNTREND,
        MarketRegime.SIDEWAYS,
        MarketRegime.WEAK_UPTREND,
        MarketRegime.STRONG_UPTREND,
    ]
    current_idx = regime_order.index(current)
    candidate_idx = regime_order.index(candidate)

    if candidate_idx > current_idx:
        if smoothed >= entry_thresh:
            return candidate
    else:
        if smoothed <= -abs(entry_thresh) if entry_thresh > 0 else smoothed <= entry_thresh:
            return candidate

    return current


def detect(df: pd.DataFrame, htf_df: pd.DataFrame = None, symbol: str = None, current_regime: MarketRegime = MarketRegime.SIDEWAYS) -> MarketRegime:
    if len(df) < 200:
        return MarketRegime.SIDEWAYS

    htf_s = _htf_score(htf_df)
    
    recent_df = df.iloc[-_SMOOTHING_PERIOD:]
    raw_scores = []
    
    for i in range(len(recent_df)):
        row = recent_df.iloc[i]
        ema_s = _ema_stack_score(row)
        adx_s = _adx_di_score(row)
        st_s = _supertrend_score(row)
        bbw_s = _bbw_score(row)
        macd_s = _macd_slope_score(row)
        
        raw_composite = (
            ema_s * 0.25 +
            adx_s * 0.20 +
            st_s * 0.15 +
            bbw_s * 0.10 +
            macd_s * 0.10 +
            htf_s * 0.20
        )
        raw_scores.append(raw_composite)
        
    smoothed = float(np.mean(raw_scores))
    candidate = _raw_score_to_candidate(smoothed)
    
    return _apply_hysteresis(candidate, smoothed, current_regime)


def reset_regime_state():
    pass


def detect_market_wide(btc_df: pd.DataFrame, btc_htf_df: pd.DataFrame = None, current_regime: MarketRegime = MarketRegime.SIDEWAYS) -> MarketRegime:
    return detect(btc_df, htf_df=btc_htf_df, symbol="__MARKET__", current_regime=current_regime)


def get_regime_details(df: pd.DataFrame, htf_df: pd.DataFrame = None) -> dict:
    if len(df) < 200:
        return {"regime": MarketRegime.SIDEWAYS.value, "composite": 0.0, "factors": {}}

    last_row = df.iloc[-1]
    factors = {
        "ema_stack": round(_ema_stack_score(last_row), 3),
        "adx_di": round(_adx_di_score(last_row), 3),
        "supertrend": round(_supertrend_score(last_row), 3),
        "bb_width": round(_bbw_score(last_row), 3),
        "macd_slope": round(_macd_slope_score(last_row), 3),
        "htf": round(_htf_score(htf_df), 3),
    }

    raw = sum(v * w for v, w in zip(
        factors.values(),
        [0.25, 0.20, 0.15, 0.10, 0.10, 0.20]
    ))

    # WATERFALL OVERRIDE: Bypass HTF drag if 15m trend is unanimous
    if factors["ema_stack"] == -1.0 and factors["adx_di"] == -1.0 and factors["supertrend"] == -1.0:
        raw = max(-1.0, raw * 1.2)
    elif factors["ema_stack"] == 1.0 and factors["adx_di"] == 1.0 and factors["supertrend"] == 1.0:
        raw = min(1.0, raw * 1.2)

    regime = _raw_score_to_candidate(raw)

    return {
        "regime": regime.value,
        "composite": round(raw, 4),
        "factors": factors,
    }
