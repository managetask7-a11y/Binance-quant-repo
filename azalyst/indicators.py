import numpy as np
import pandas as pd


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    df["rsi_14"] = 100.0 - (100.0 / (1.0 + rs))

    avg_gain_9 = gain.ewm(alpha=1.0 / 9, adjust=False).mean()
    avg_loss_9 = loss.ewm(alpha=1.0 / 9, adjust=False).mean()
    rs_9 = avg_gain_9 / avg_loss_9.replace(0.0, float("nan"))
    df["rsi_9"] = 100.0 - (100.0 / (1.0 + rs_9))

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr_14"] = tr.ewm(alpha=1.0 / 14, adjust=False).mean()
    df["atr_ma_20"] = df["atr_14"].rolling(20).mean()

    df["bb_mid"] = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2.0 * bb_std
    df["bb_lower"] = df["bb_mid"] - 2.0 * bb_std

    # --- Alpha-X Institutional BB (200, SD 1.5) ---
    # SD 1.5 is the institutional standard for filtering false breakouts.
    df["bb200_mid"] = df["close"].rolling(200).mean()
    bb200_std = df["close"].rolling(200).std()
    df["bb200_upper"] = df["bb200_mid"] + 1.5 * bb200_std
    df["bb200_lower"] = df["bb200_mid"] - 1.5 * bb200_std
    # Bandwidth for Alpha-X filter
    df["bb200_width"] = (df["bb200_upper"] - df["bb200_lower"]) / df["bb200_mid"].replace(0.0, float("nan"))
    
    # --- Squeeze Detector (Volatility Quantile) ---
    # Tracks how tight the bands are relative to the last 100 candles.
    # A value of 0.2 means the bands are tighter than they were 80% of the time.
    df["bb200_squeeze"] = df["bb200_width"].rolling(100).rank(pct=True)

    fast_ema = df["close"].ewm(span=12, adjust=False).mean()
    slow_ema = df["close"].ewm(span=26, adjust=False).mean()
    df["macd_line"] = fast_ema - slow_ema
    df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd_line"] - df["macd_signal"]
    df["macd_hist_accel"] = df["macd_hist"].diff()

    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_smooth = df["atr_14"]
    df["pdi"] = 100.0 * plus_dm.ewm(alpha=1.0 / 14, adjust=False).mean() / atr_smooth.replace(0.0, float("nan"))
    df["mdi"] = 100.0 * minus_dm.ewm(alpha=1.0 / 14, adjust=False).mean() / atr_smooth.replace(0.0, float("nan"))
    dx = ((df["pdi"] - df["mdi"]).abs() / (df["pdi"] + df["mdi"]).replace(0.0, float("nan"))) * 100.0
    df["adx"] = dx.ewm(alpha=1.0 / 14, adjust=False).mean()
    
    # --- Slow ADX (Market Sentiment) ---
    # Used to detect long-term structural trends for 180-day stability.
    df["adx_50"] = dx.ewm(alpha=1.0 / 50, adjust=False).mean()

    hl2 = (df["high"] + df["low"]) / 2.0
    upper_band = hl2 + 3.0 * df["atr_14"]
    lower_band = hl2 - 3.0 * df["atr_14"]

    supertrend = pd.Series(index=df.index, dtype=float)
    supertrend_dir = pd.Series(index=df.index, dtype=float)
    for i in range(len(df)):
        if i == 0:
            supertrend.iloc[i] = upper_band.iloc[i]
            supertrend_dir.iloc[i] = 1
        else:
            if df["close"].iloc[i] > supertrend.iloc[i - 1]:
                supertrend.iloc[i] = max(lower_band.iloc[i], supertrend.iloc[i - 1])
                supertrend_dir.iloc[i] = 1
            else:
                supertrend.iloc[i] = min(upper_band.iloc[i], supertrend.iloc[i - 1])
                supertrend_dir.iloc[i] = -1
    df["supertrend"] = supertrend
    df["supertrend_dir"] = supertrend_dir

    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    tpv = tp * df["volume"]
    df["vwap"] = tpv.cumsum() / df["volume"].replace(0.0, float("nan")).cumsum()

    df["vol_ma_20"] = df["volume"].rolling(20).mean()

    # Institutional Swing Points (Alpha-X 60-period spec)
    # Changed from center=True to standard rolling (backward-looking) for Live compatibility
    df["local_swing_high"] = df["high"].rolling(60).max()
    df["local_swing_low"] = df["low"].rolling(60).min()
    df["swing_high"] = df["high"].rolling(5).max()
    df["swing_low"] = df["low"].rolling(5).min()

    df["momentum_9"] = df["close"].diff(9)

    # Bollinger Band Width (Regime Detector)
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"].replace(0.0, float("nan"))

    # Stochastic RSI (Range Timing)
    # Uses 14-period RSI as the base
    rsi_min = df["rsi_14"].rolling(14).min()
    rsi_max = df["rsi_14"].rolling(14).max()
    df["stoch_rsi_k"] = (df["rsi_14"] - rsi_min) / (rsi_max - rsi_min).replace(0.0, 1e-8)
    df["stoch_rsi_d"] = df["stoch_rsi_k"].rolling(3).mean()

    # CVD (Cumulative Volume Delta) approximation
    range_hl = (df["high"] - df["low"]).replace(0.0, 1e-8)
    buy_vol = df["volume"] * (df["close"] - df["low"]) / range_hl
    sell_vol = df["volume"] * (df["high"] - df["close"]) / range_hl
    delta = buy_vol - sell_vol
    df["cvd"] = delta.cumsum()

    # ADX (Average Directional Index) - Trend Strength
    # Standard 14-period Welles Wilder method
    df["plus_dm"] = np.where((df["high"] - df["high"].shift(1)) > (df["low"].shift(1) - df["low"]), 
                             np.maximum(df["high"] - df["high"].shift(1), 0), 0)
    df["minus_dm"] = np.where((df["low"].shift(1) - df["low"]) > (df["high"] - df["high"].shift(1)), 
                              np.maximum(df["low"].shift(1) - df["low"], 0), 0)
    
    tr = pd.concat([df["high"] - df["low"], 
                    (df["high"] - df["close"].shift(1)).abs(), 
                    (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
    
    # Wilder's Smoothing
    atr_smooth = tr.rolling(14).mean()
    plus_di = 100 * (df["plus_dm"].rolling(14).mean() / atr_smooth)
    minus_di = 100 * (df["minus_dm"].rolling(14).mean() / atr_smooth)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, 1e-8)
    df["adx_14"] = dx.rolling(14).mean()

    # Money Flow Index (Institutional Volume)
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    mf = tp * df["volume"]
    mf_dir = np.where(tp > tp.shift(1), 1, -1)
    pos_mf = pd.Series(np.where(mf_dir == 1, mf, 0.0), index=df.index).rolling(14).sum()
    neg_mf = pd.Series(np.where(mf_dir == -1, mf, 0.0), index=df.index).rolling(14).sum()
    mfr = pos_mf / neg_mf.replace(0.0, float("nan"))
    df["mfi_14"] = 100.0 - (100.0 / (1.0 + mfr))

    # Candle Conviction (Institutional Strength)
    candle_range = (df["high"] - df["low"]).replace(0.0, 1e-8)
    df["conviction"] = (df["close"] - df["low"]) / candle_range # 0 (bearish) to 1 (bullish)
    df["body_ratio"] = (df["close"] - df["open"]).abs() / candle_range

    return df
