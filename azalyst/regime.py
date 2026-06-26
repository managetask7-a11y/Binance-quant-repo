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


# ═══════════════════════════════════════════════════════════════════════════
# FULLY STATELESS REGIME DETECTION
# ═══════════════════════════════════════════════════════════════════════════
# detect() has ZERO global mutable state. The regime is computed purely from
# the passed-in dataframe every call. This guarantees backtest and live agree
# on identical data: same BTC bars → same regime.
#
# The detector replays a lookback window of smoothed scores through a
# hysteresis chain with hold-counter logic, all computed from data — no
# accumulated deque or global current_regime.
# ═══════════════════════════════════════════════════════════════════════════

_SMOOTHING_PERIOD = 12
_REGIME_MIN_HOLD = 16
_LOOKBACK_BARS = 100

_HYSTERESIS = {
    MarketRegime.STRONG_UPTREND:   {"enter": 0.40, "exit": 0.25},
    MarketRegime.WEAK_UPTREND:     {"enter": 0.15, "exit": -0.05},
    MarketRegime.SIDEWAYS:         {"enter": -0.10, "exit": 0.10},
    MarketRegime.WEAK_DOWNTREND:   {"enter": -0.40, "exit": -0.15},
    MarketRegime.STRONG_DOWNTREND: {"enter": -0.45, "exit": -0.25},
}

_REGIME_ORDER = [
    MarketRegime.STRONG_DOWNTREND,
    MarketRegime.WEAK_DOWNTREND,
    MarketRegime.SIDEWAYS,
    MarketRegime.WEAK_UPTREND,
    MarketRegime.STRONG_UPTREND,
]


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
    bbw_pct = row.get("bb200_squeeze", 0.5)

    if np.isnan(bbw_pct):
        return 0.0

    if bbw_pct < 0.15:
        return 0.0
    if bbw_pct > 0.80:
        price = row["close"]
        ema50 = row.get("ema_50", price)
        return 0.8 if price > ema50 else -0.8
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

    if "ema_50" in htf_df.columns and "ema_200" in htf_df.columns:
        ema50 = last["ema_50"]
        ema200 = last["ema_200"]
    else:
        ema50 = htf_df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = htf_df["close"].ewm(span=200, adjust=False).mean().iloc[-1]

    price = last["close"]

    if price > ema200 and ema50 > ema200:
        return 1.0
    if price < ema200 and ema50 < ema200:
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


def detect(df: pd.DataFrame, htf_df: pd.DataFrame = None, symbol: str = None) -> MarketRegime:
    """Fully stateless regime detection. Same data → same regime, always.

    Computes smoothed composite scores over the last _LOOKBACK_BARS bars,
    then replays a hysteresis chain with hold-counter from SIDEWAYS.
    No global state — result depends only on the data passed in.

    Args:
        df: 15m BTC dataframe with indicators computed (>=200 rows).
        htf_df: 4h BTC dataframe (optional).
        symbol: ignored (kept for API backward-compatibility).
    """
    if len(df) < 200:
        return MarketRegime.SIDEWAYS

    htf_s = _htf_score(htf_df)

    # Build a history of smoothed composite scores over the lookback window.
    # At each step, the smoothed value is the mean of the last _SMOOTHING_PERIOD
    # raw composite scores — exactly like the old deque approach, but computed
    # from data instead of accumulated state.
    lookback = min(len(df), _LOOKBACK_BARS)
    smoothed_history = []
    for offset in range(lookback):
        idx = len(df) - lookback + offset
        chunk = df.iloc[max(0, idx - _SMOOTHING_PERIOD + 1):idx + 1]
        if len(chunk) < 1:
            smoothed_history.append(0.0)
            continue
        last_n = chunk.tail(_SMOOTHING_PERIOD)
        comps = []
        for _, bar in last_n.iterrows():
            c = (
                _ema_stack_score(bar) * 0.25 +
                _adx_di_score(bar) * 0.20 +
                _supertrend_score(bar) * 0.15 +
                _bbw_score(bar) * 0.10 +
                _macd_slope_score(bar) * 0.10 +
                htf_s * 0.20
            )
            comps.append(c)
        smoothed_history.append(float(np.mean(comps)))

    # Replay hysteresis with hold counter (all from data — no global state).
    # Start from SIDEWAYS and walk forward through the score history.
    current = MarketRegime.SIDEWAYS
    hold = 0
    for smoothed in smoothed_history:
        candidate = _raw_score_to_candidate(smoothed)

        if candidate == current:
            hold = 0
            continue

        # STRONG trends can override the hold lock
        is_strong = candidate in (MarketRegime.STRONG_DOWNTREND, MarketRegime.STRONG_UPTREND)
        if hold > 0 and not is_strong:
            hold -= 1
            continue

        entry_thresh = _HYSTERESIS[candidate]["enter"]
        exit_thresh = _HYSTERESIS[current]["exit"]
        current_idx = _REGIME_ORDER.index(current)
        candidate_idx = _REGIME_ORDER.index(candidate)

        if candidate_idx > current_idx:
            if smoothed >= entry_thresh:
                current = candidate
                hold = _REGIME_MIN_HOLD
        else:
            if smoothed <= exit_thresh:
                current = candidate
                hold = _REGIME_MIN_HOLD

    return current


def reset_regime_state():
    """No-op. Kept for backward compatibility — detector is now stateless."""
    return


def detect_market_wide(btc_df: pd.DataFrame, btc_htf_df: pd.DataFrame = None) -> MarketRegime:
    return detect(btc_df, htf_df=btc_htf_df, symbol="__MARKET__")


def get_regime_details(df: pd.DataFrame, htf_df: pd.DataFrame = None) -> dict:
    if len(df) < 200:
        return {"regime": MarketRegime.SIDEWAYS.value, "composite": 0.0, "factors": {}}

    last = df.iloc[-1]
    factors = {
        "ema_stack": round(_ema_stack_score(last), 3),
        "adx_di": round(_adx_di_score(last), 3),
        "supertrend": round(_supertrend_score(last), 3),
        "bb_width": round(_bbw_score(last), 3),
        "macd_slope": round(_macd_slope_score(last), 3),
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

    regime = detect(df, htf_df=htf_df)

    return {
        "regime": regime.value,
        "composite": round(raw, 4),
        "factors": factors,
    }
