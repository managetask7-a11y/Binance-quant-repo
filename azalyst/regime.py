from __future__ import annotations

from enum import Enum
from collections import deque

import numpy as np
import pandas as pd


class MarketRegime(Enum):
    STRONG_UPTREND = "strong_uptrend"
    WEAK_UPTREND = "weak_uptrend"
    SIDEWAYS = "sideways"
    WEAK_DOWNTREND = "weak_downtrend"
    STRONG_DOWNTREND = "strong_downtrend"


_SMOOTHING_PERIOD = 12
_composite_history: deque = deque(maxlen=_SMOOTHING_PERIOD)
_per_symbol_history: dict[str, deque] = {}


def _ema_stack_score(df: pd.DataFrame) -> float:
    last = df.iloc[-1]
    ema9 = last.get("ema_9", last["close"])
    ema21 = last.get("ema_21", last["close"])
    ema50 = last.get("ema_50", last["close"])
    ema200 = last.get("ema_200", last["close"])
    price = last["close"]

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


def _adx_di_score(df: pd.DataFrame) -> float:
    last = df.iloc[-1]
    adx = last.get("adx", 20)
    pdi = last.get("pdi", 0)
    mdi = last.get("mdi", 0)

    if np.isnan(adx) or np.isnan(pdi) or np.isnan(mdi):
        return 0.0

    if adx < 18:
        return 0.0

    di_spread = pdi - mdi
    normalized = np.clip(di_spread / 40.0, -1.0, 1.0)

    if adx > 30:
        normalized *= 1.3

    return float(np.clip(normalized, -1.0, 1.0))


def _supertrend_score(df: pd.DataFrame) -> float:
    last = df.iloc[-1]
    st_dir = last.get("supertrend_dir", 0)
    if st_dir == 1:
        return 1.0
    elif st_dir == -1:
        return -1.0
    return 0.0


def _bbw_score(df: pd.DataFrame) -> float:
    last = df.iloc[-1]
    bbw = last.get("bb_width", 0.1)
    bbw_pct = last.get("bb200_squeeze", 0.5)

    if np.isnan(bbw) or np.isnan(bbw_pct):
        return 0.0

    if bbw_pct < 0.15:
        return 0.0
    if bbw_pct > 0.80:
        price = last["close"]
        ema50 = last.get("ema_50", price)
        if price > ema50:
            return 0.8
        else:
            return -0.8
    return 0.0


def _macd_slope_score(df: pd.DataFrame) -> float:
    last = df.iloc[-1]
    hist = last.get("macd_hist", 0)
    accel = last.get("macd_hist_accel", 0)

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


def _vwap_score(df: pd.DataFrame) -> float:
    last = df.iloc[-1]
    price = last["close"]
    vwap = last.get("vwap", price)

    if np.isnan(vwap) or vwap == 0:
        return 0.0

    deviation = (price - vwap) / vwap
    return float(np.clip(deviation * 20, -1.0, 1.0))


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


def _composite_to_regime(score: float) -> MarketRegime:
    if score > 0.5:
        return MarketRegime.STRONG_UPTREND
    if score > 0.15:
        return MarketRegime.WEAK_UPTREND
    if score > -0.15:
        return MarketRegime.SIDEWAYS
    if score > -0.5:
        return MarketRegime.WEAK_DOWNTREND
    return MarketRegime.STRONG_DOWNTREND


def detect(df: pd.DataFrame, htf_df: pd.DataFrame = None, symbol: str = None) -> MarketRegime:
    if len(df) < 200:
        return MarketRegime.SIDEWAYS

    ema_s = _ema_stack_score(df)
    adx_s = _adx_di_score(df)
    st_s = _supertrend_score(df)
    bbw_s = _bbw_score(df)
    macd_s = _macd_slope_score(df)
    vwap_s = _vwap_score(df)
    htf_s = _htf_score(htf_df)

    raw_composite = (
        ema_s * 0.25 +
        adx_s * 0.20 +
        st_s * 0.15 +
        bbw_s * 0.15 +
        macd_s * 0.10 +
        vwap_s * 0.10 +
        htf_s * 0.05
    )

    if symbol:
        if symbol not in _per_symbol_history:
            _per_symbol_history[symbol] = deque(maxlen=_SMOOTHING_PERIOD)
        _per_symbol_history[symbol].append(raw_composite)
        smoothed = float(np.mean(list(_per_symbol_history[symbol])))
    else:
        _composite_history.append(raw_composite)
        smoothed = float(np.mean(list(_composite_history)))

    return _composite_to_regime(smoothed)


def detect_market_wide(btc_df: pd.DataFrame, btc_htf_df: pd.DataFrame = None) -> MarketRegime:
    return detect(btc_df, htf_df=btc_htf_df, symbol="__MARKET__")


def get_regime_details(df: pd.DataFrame, htf_df: pd.DataFrame = None) -> dict:
    if len(df) < 200:
        return {"regime": MarketRegime.SIDEWAYS.value, "composite": 0.0, "factors": {}}

    factors = {
        "ema_stack": round(_ema_stack_score(df), 3),
        "adx_di": round(_adx_di_score(df), 3),
        "supertrend": round(_supertrend_score(df), 3),
        "bb_width": round(_bbw_score(df), 3),
        "macd_slope": round(_macd_slope_score(df), 3),
        "vwap": round(_vwap_score(df), 3),
        "htf": round(_htf_score(htf_df), 3),
    }

    raw = sum(v * w for v, w in zip(
        factors.values(),
        [0.25, 0.20, 0.15, 0.15, 0.10, 0.10, 0.05]
    ))

    regime = _composite_to_regime(raw)

    return {
        "regime": regime.value,
        "composite": round(raw, 4),
        "factors": factors,
    }
