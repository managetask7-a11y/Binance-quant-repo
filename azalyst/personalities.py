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


PERSONALITIES: dict[MarketRegime, Personality] = {

    MarketRegime.STRONG_UPTREND: Personality(
        name="Momentum Rider",
        regime=MarketRegime.STRONG_UPTREND,
        weights={
            "bnf": 3.0,
            "nbb": 4.0,
            "kane": 0.0,
            "umar": 4.0,
            "zamco": 0.0,
            "jadecap": 3.0,
            "marci": 0.0,
            "fvg": 0.0,
            "ote": 0.0,
            "cvd_divergence": 0.0,
            "wyckoff": 0.0,
            "cbg": 0.0,
            "bb_trend": 0.0,
            "band_rider": 3.5,
            "liquidity_hunter": 0.0,
            "alpha_x": 0.0,
        },
        atr_mult=1.8,
        tp_rr_ratio=3.0,
        sl_min_pct=0.015,
        sl_max_pct=0.04,
        trailing_enabled=True,
        trail_trigger_pct=0.025,
        trail_distance_pct=0.015,
        max_open_trades=10,
        max_same_direction=8,
        risk_multiplier=3.0,
        min_agreement=2,
        weighted_threshold=5.0,
        directional_bias=1,
        scan_limit=20,
        leverage=20,
    ),

    MarketRegime.WEAK_UPTREND: Personality(
        name="Cautious Bull",
        regime=MarketRegime.WEAK_UPTREND,
        weights={
            "bnf": 3.0,
            "nbb": 0.0,
            "kane": 0.0,
            "umar": 4.0,
            "zamco": 0.0,
            "jadecap": 3.0,
            "marci": 0.0,
            "fvg": 0.0,
            "ote": 0.0,
            "cvd_divergence": 0.0,
            "wyckoff": 0.0,
            "cbg": 0.0,
            "bb_trend": 0.0,
            "band_rider": 2.5,
            "liquidity_hunter": 3.0,
            "alpha_x": 0.0,
        },
        atr_mult=1.4,
        tp_rr_ratio=2.5,
        sl_min_pct=0.015,
        sl_max_pct=0.03,
        trailing_enabled=True,
        trail_trigger_pct=0.025,
        trail_distance_pct=0.015,
        max_open_trades=8,
        max_same_direction=6,
        risk_multiplier=1.5,
        min_agreement=2,
        weighted_threshold=5.0,
        directional_bias=1,
        scan_limit=20,
        leverage=20,
    ),

    MarketRegime.SIDEWAYS: Personality(
        name="Range Sniper",
        regime=MarketRegime.SIDEWAYS,
        weights={
            "bnf": 3.0,
            "nbb": 0.0,
            "kane": 0.0,
            "umar": 4.0,
            "zamco": 0.0,
            "jadecap": 3.0,
            "marci": 0.0,
            "fvg": 0.0,
            "ote": 0.0,
            "cvd_divergence": 0.0,
            "wyckoff": 0.0,
            "cbg": 0.0,
            "bb_trend": 0.0,
            "band_rider": 0.0,
            "liquidity_hunter": 4.0,
            "alpha_x": 0.0,
        },
        atr_mult=0.8,
        tp_rr_ratio=2.0,
        sl_min_pct=0.015,
        sl_max_pct=0.03,
        trailing_enabled=False,
        trail_trigger_pct=0.0,
        trail_distance_pct=0.0,
        max_open_trades=5,
        max_same_direction=3,
        risk_multiplier=1.0,
        min_agreement=2,
        weighted_threshold=5.0,
        directional_bias=0,
        scan_limit=15,
        leverage=20,
    ),

    MarketRegime.WEAK_DOWNTREND: Personality(
        name="Defensive Bear",
        regime=MarketRegime.WEAK_DOWNTREND,
        weights={
            "bnf": 3.0,
            "nbb": 0.0,
            "kane": 0.0,
            "umar": 4.0,
            "zamco": 0.0,
            "jadecap": 3.0,
            "marci": 0.0,
            "fvg": 0.0,
            "ote": 0.0,
            "cvd_divergence": 0.0,
            "wyckoff": 0.0,
            "cbg": 0.0,
            "bb_trend": 0.0,
            "band_rider": 0.3,
            "liquidity_hunter": 3.0,
            "alpha_x": 0.0,
        },
        atr_mult=1.2,
        tp_rr_ratio=2.5,
        sl_min_pct=0.015,
        sl_max_pct=0.025,
        trailing_enabled=True,
        trail_trigger_pct=0.025,
        trail_distance_pct=0.015,
        max_open_trades=6,
        max_same_direction=5,
        risk_multiplier=1.5,
        min_agreement=2,
        weighted_threshold=5.0,
        directional_bias=-1,
        scan_limit=10,
        leverage=20,
    ),

    MarketRegime.STRONG_DOWNTREND: Personality(
        name="Crisis Alpha",
        regime=MarketRegime.STRONG_DOWNTREND,
        weights={
            "bnf": 3.0,
            "nbb": 4.0,
            "kane": 0.0,
            "umar": 4.0,
            "zamco": 0.0,
            "jadecap": 3.0,
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
        },
        atr_mult=1.0,
        tp_rr_ratio=3.0,
        sl_min_pct=0.015,
        sl_max_pct=0.02,
        trailing_enabled=True,
        trail_trigger_pct=0.020,
        trail_distance_pct=0.010,
        max_open_trades=4,
        max_same_direction=4,
        risk_multiplier=3.0,
        min_agreement=2,
        weighted_threshold=5.0,
        directional_bias=-1,
        scan_limit=10,
        leverage=20,
    ),
}


def get_personality(regime: MarketRegime) -> Personality:
    return PERSONALITIES[regime]


DEFAULT_PERSONALITY = PERSONALITIES[MarketRegime.SIDEWAYS]
