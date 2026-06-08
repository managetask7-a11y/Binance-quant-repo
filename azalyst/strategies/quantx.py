"""
QUANT-X Multi-Agent Consensus Strategy

Ported from Azalyst-FundingPips-Signals. Adapted for Binance crypto on 15m candles.

Logic:
  4 virtual "agents" each vote BUY (+1), SELL (-1), or NEUTRAL (0):
    1. Market Agent: EMA 20/50 cross + MACD histogram direction
    2. Sentiment Agent: RSI position + price vs VWAP
    3. Liquidity Agent: Current volume vs 20-bar average (confirms participation)
    4. Risk Agent: ATR/price ratio blocks trades if volatility is extreme (>5%)

  A trade fires only when >= 3 agents agree on the same direction.
  SL = 1.5x ATR(14), TP = 3x ATR(14) -> 1:2 Risk/Reward.
"""
import pandas as pd
import numpy as np
from azalyst.config import BUY, SELL, HOLD


def signal(df: pd.DataFrame) -> int:
    if len(df) < 60:
        return HOLD

    last = df.iloc[-1]

    # --- Extract indicators (already computed by compute_indicators) ---
    ema20 = last.get("ema_20", np.nan)
    ema50 = last.get("ema_50", np.nan)
    rsi = last.get("rsi_14", np.nan)
    macd_hist = last.get("macd_hist", np.nan)
    vwap = last.get("vwap", np.nan)
    close = last["close"]
    volume = last.get("volume", 0)
    atr = last.get("atr_14", np.nan)

    if any(np.isnan(v) for v in [ema20, ema50, rsi, macd_hist, vwap, atr]):
        return HOLD
    if atr <= 0:
        return HOLD

    vol_avg = df["volume"].iloc[-20:].mean()

    # --- Agent 1: Market Trend (EMA cross + MACD confirmation) ---
    if ema20 > ema50 and macd_hist > 0:
        market = 1
    elif ema20 < ema50 and macd_hist < 0:
        market = -1
    else:
        market = 0

    # --- Agent 2: Sentiment (RSI zone + VWAP position) ---
    if rsi > 55 and close > vwap:
        sentiment = 1
    elif rsi < 45 and close < vwap:
        sentiment = -1
    else:
        sentiment = 0

    # --- Agent 3: Liquidity (volume confirms participation) ---
    liquidity = 1 if volume > vol_avg else 0

    # --- Agent 4: Risk (ATR/price too high = stand aside) ---
    risk_high = (atr / close) > 0.05
    if risk_high:
        return HOLD

    # --- Consensus ---
    direction = market + sentiment
    agree_bull = sum(v == 1 for v in (market, sentiment)) + (1 if liquidity and direction > 0 else 0)
    agree_bear = sum(v == -1 for v in (market, sentiment)) + (1 if liquidity and direction < 0 else 0)

    if agree_bull >= 3:
        return BUY
    if agree_bear >= 3:
        return SELL

    return HOLD
