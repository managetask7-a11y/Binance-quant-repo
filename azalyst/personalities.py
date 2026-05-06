from __future__ import annotations

from dataclasses import dataclass, field
from azalyst.regime import MarketRegime


@dataclass
class Personality:
    name: str
    regime: MarketRegime
    weights: dict[str, float]
    atr_mult: float
    tp_rr_ratio: float
    sl_min_pct: float
    sl_max_pct: float
    trailing_enabled: bool
    trail_trigger_pct: float
    trail_distance_pct: float
    max_open_trades: int
    max_same_direction: int
    risk_multiplier: float
    min_agreement: int
    weighted_threshold: float
    directional_bias: int
    scan_limit: int
    leverage: int = 20


_ZERO_WEIGHTS = {
    "bnf": 0.0,
    "nbb": 0.0,
    "kane": 0.0,
    "umar": 0.0,
    "zamco": 0.0,
    "jadecap": 0.0,
    "marci": 0.0,
    "fvg": 0.0,
    "ote": 0.0,
    "cvd_divergence": 0.0,
    "wyckoff": 0.0,
    "cbg": 0.0,
    "bb_trend": 0.0,
    "band_rider": 0.0,
    "liquidity_hunter": 0.0,
    "alpha_x": 0.0,
    "vwap_bounce": 0.0,
    "rsi_divergence": 0.0,
}


PERSONALITIES: dict[MarketRegime, Personality] = {

    # ═══════════════════════════════════════════════════════════════════
    # STRONG UPTREND — Momentum Rider
    # Base = exact old settings that produced $141 in April.
    # Changes from original:
    #   - band_rider killed (was net -$30 loser)
    #   - risk_multiplier 2.0 → 3.5 (1.75x larger positions)
    #   - max_open_trades 6 → 8 (more concurrent bets)
    #   - bnf weight 3.0 → 4.0 (stronger mean-reversion pullbacks)
    #   - Everything else IDENTICAL to the $141 config
    # ═══════════════════════════════════════════════════════════════════
    MarketRegime.STRONG_UPTREND: Personality(
        name="Momentum Rider",
        regime=MarketRegime.STRONG_UPTREND,
        weights={
            **_ZERO_WEIGHTS,
            "nbb": 5.0,         # Primary — reliable candlestick patterns
            "bnf": 5.0,         # Solid mean-reversion pullbacks
            "bb_trend": 1.6,    # KILLED — was in every big loss, toxic in this regime
            "umar": 2.8,        # Boosted — achieved 100% win rate when filtered
            "jadecap": 2.0,     # Sweep signals for diversification
        },
        atr_mult=2.5,           # RESTORED from 2.0 — original value
        tp_rr_ratio=3.5,        # RESTORED from 4.0 — original value
        sl_min_pct=0.02,        # RESTORED
        sl_max_pct=0.05,        # RESTORED
        trailing_enabled=True,
        trail_trigger_pct=0.04, # RESTORED from 0.03 — original value
        trail_distance_pct=0.035, # RESTORED from 0.02 — THIS WAS THE KILLER
        max_open_trades=8,      # was 6 — more concurrent trades
        max_same_direction=7,   # was 5
        risk_multiplier=2.5,    # was 3.5 — reduced to prevent $100+ single-trade losses
        min_agreement=2,
        weighted_threshold=5.0,
        directional_bias=1,
        scan_limit=20,
        leverage=20,
    ),

    # ═══════════════════════════════════════════════════════════════════
    # WEAK UPTREND — Cautious Bull
    # Conservative. This regime was NET NEGATIVE in original backtest.
    # ═══════════════════════════════════════════════════════════════════
    MarketRegime.WEAK_UPTREND: Personality(
        name="Cautious Bull",
        regime=MarketRegime.WEAK_UPTREND,
        weights={
            **_ZERO_WEIGHTS,
            "nbb": 5.0,
            "umar": 3.0,
            "jadecap": 3.0,
            "bnf": 2.0,
        },
        atr_mult=2.0,
        tp_rr_ratio=3.0,
        sl_min_pct=0.015,
        sl_max_pct=0.04,
        trailing_enabled=True,
        trail_trigger_pct=0.03,
        trail_distance_pct=0.02,
        max_open_trades=4,
        max_same_direction=4,
        risk_multiplier=0.7,
        min_agreement=2,
        weighted_threshold=5.0,
        directional_bias=1,
        scan_limit=20,
        leverage=20,
    ),

    # ═══════════════════════════════════════════════════════════════════
    # SIDEWAYS — Range Sniper (DISABLED)
    # ═══════════════════════════════════════════════════════════════════
    MarketRegime.SIDEWAYS: Personality(
        name="Range Sniper",
        regime=MarketRegime.SIDEWAYS,
        weights={**_ZERO_WEIGHTS},
        atr_mult=1.2,
        tp_rr_ratio=2.0,
        sl_min_pct=0.015,
        sl_max_pct=0.03,
        trailing_enabled=False,
        trail_trigger_pct=0.0,
        trail_distance_pct=0.0,
        max_open_trades=0,
        max_same_direction=0,
        risk_multiplier=0.0,
        min_agreement=1,
        weighted_threshold=99.0,
        directional_bias=0,
        scan_limit=15,
        leverage=20,
    ),

    # ═══════════════════════════════════════════════════════════════════
    # WEAK DOWNTREND — Defensive Bear
    # ═══════════════════════════════════════════════════════════════════
    MarketRegime.WEAK_DOWNTREND: Personality(
        name="Defensive Bear",
        regime=MarketRegime.WEAK_DOWNTREND,
        weights={
            **_ZERO_WEIGHTS,
            "jadecap": 5.0,
            "liquidity_hunter": 5.0,
            "nbb": 3.0,
        },
        atr_mult=1.5,
        tp_rr_ratio=2.5,
        sl_min_pct=0.015,
        sl_max_pct=0.03,
        trailing_enabled=True,
        trail_trigger_pct=0.025,
        trail_distance_pct=0.015,
        max_open_trades=3,
        max_same_direction=3,
        risk_multiplier=0.2,
        min_agreement=1,
        weighted_threshold=5.0,
        directional_bias=-1,
        scan_limit=10,
        leverage=20,
    ),

    # ═══════════════════════════════════════════════════════════════════
    # STRONG DOWNTREND — Crisis Alpha (DISABLED)
    # ═══════════════════════════════════════════════════════════════════
    MarketRegime.STRONG_DOWNTREND: Personality(
        name="Crisis Alpha",
        regime=MarketRegime.STRONG_DOWNTREND,
        weights={**_ZERO_WEIGHTS},
        atr_mult=1.8,
        tp_rr_ratio=2.5,
        sl_min_pct=0.015,
        sl_max_pct=0.035,
        trailing_enabled=False,
        trail_trigger_pct=0.0,
        trail_distance_pct=0.0,
        max_open_trades=0,
        max_same_direction=0,
        risk_multiplier=0.0,
        min_agreement=1,
        weighted_threshold=99.0,
        directional_bias=-1,
        scan_limit=10,
        leverage=20,
    ),
}


def get_personality(regime: MarketRegime) -> Personality:
    return PERSONALITIES[regime]


DEFAULT_PERSONALITY = PERSONALITIES[MarketRegime.SIDEWAYS]
