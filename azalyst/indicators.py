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

    df["swing_high"] = df["high"].rolling(5, center=True).max()
    df["swing_low"] = df["low"].rolling(5, center=True).min()

    df["momentum_9"] = df["close"].diff(9)

    return df
