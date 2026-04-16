import pandas as pd

from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 200:
        return HOLD

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # ── Global Armor Filter ──
    ema_200 = last.get("ema_200", last["close"])
    vol_ma = last.get("vol_ma_20", 0)
    # Mean reversion requires extreme institutional volume exhaustion
    high_conviction_vol = last["volume"] > vol_ma * 2.0 if vol_ma > 0 else True

    # ── Stochastic RSI Confluence (Range Reversals) ──
    # Oversold: < 0.2, Overbought: > 0.8
    stoch_k = last.get("stoch_rsi_k", 0.5)
    stoch_d = last.get("stoch_rsi_d", 0.5)

    # ── Range Hunter Logic (Buy Low, Sell High) ──
    if stoch_k < 0.2 and stoch_d < 0.2: 
        # Price must pierce the band
        at_bb_lower = last["low"] <= last["bb_lower"]
        below_vwap = last["close"] < last.get("vwap", last["close"])
        
        # Wick Rejection confirm: Close > Middle of candle range
        wick_rejection = (last["close"] - last["low"]) > (last["high"] - last["close"])

        if at_bb_lower and below_vwap and wick_rejection and high_conviction_vol:
            return BUY

    if stoch_k > 0.8 and stoch_d > 0.8:
        at_bb_upper = last["high"] >= last["bb_upper"]
        above_vwap = last["close"] > last.get("vwap", last["close"])
        
        wick_rejection = (last["high"] - last["close"]) > (last["close"] - last["low"])

        if at_bb_upper and above_vwap and wick_rejection and high_conviction_vol:
            return SELL

    return HOLD
