from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ccxt
import pandas as pd

from azalyst.config import (
    EXCLUDE_SYMBOLS, MIN_VOLUME_MA, CANDLE_TF_MIN, CACHE_DIR,
    HTF_EMA_FAST, HTF_EMA_SLOW,
)
from azalyst.indicators import compute_indicators


def _cache_path(symbol: str, tf: str, start: str, end: str) -> Path:
    safe_sym = symbol.replace("/", "_").replace(":", "_")
    return CACHE_DIR / f"{safe_sym}_{tf}_{start}_{end}.parquet"


def _fetch_paginated(exchange, symbol: str, tf: str, since_ms: int, end_ms: int, limit_per_call: int = 1000) -> pd.DataFrame:
    all_rows = []
    current_since = since_ms

    while True:
        if current_since > end_ms:
            break

        try:
            ohlcv = exchange.fetch_ohlcv(symbol, tf, since=current_since, limit=limit_per_call)
        except Exception:
            break

        if not ohlcv:
            break

        valid_rows = [row for row in ohlcv if row[0] <= end_ms]
        if not valid_rows:
            break
            
        all_rows.extend(valid_rows)
        
        last_ts = ohlcv[-1][0]
        if last_ts <= current_since or last_ts >= end_ms:
            break
        current_since = last_ts + 1

        if len(ohlcv) < limit_per_call:
            break

        time.sleep(0.15)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    return df


def _fetch_single_symbol(exchange, symbol: str, tf: str, since_ms: int, end_ms: int, start_str: str, end_str: str) -> tuple:
    cache = _cache_path(symbol, tf, start_str, end_str)

    if cache.exists():
        try:
            df = pd.read_parquet(cache)
            df.index = pd.to_datetime(df.index, utc=True)
            if not df.empty and len(df) > 200:
                return symbol, df
        except Exception:
            pass

    df = _fetch_paginated(exchange, symbol, tf, since_ms, end_ms)
    if df.empty or len(df) <= 200:
        return symbol, pd.DataFrame()

    try:
        df.to_parquet(cache)
    except Exception:
        pass

    return symbol, df


class DataProvider:

    def __init__(self, exchange=None):
        self.exchange = exchange or ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

    def get_top_symbols(self, n: int = 25) -> list:
        print(f"Fetching market data from Binance...")
        markets = self.exchange.load_markets()

        usdt_symbols = [
            s for s, m in markets.items()
            if s.endswith("/USDT:USDT") and m.get("active", True)
        ]

        filtered = []
        for s in usdt_symbols:
            base = s.split("/")[0]
            full_name = s.replace("/USDT", "").replace(":", "")
            if full_name not in EXCLUDE_SYMBOLS and base not in EXCLUDE_SYMBOLS:
                filtered.append(s)

        print(f"  Found {len(filtered)} active futures pairs. Fetching volumes...")
        tickers = self.exchange.fetch_tickers()

        ranked = []
        for sym in filtered:
            if sym in tickers:
                vol = tickers[sym].get("quoteVolume", 0) or 0
                if vol > MIN_VOLUME_MA:
                    ranked.append((sym, vol))

        ranked.sort(key=lambda x: x[1], reverse=True)
        symbols = [s for s, _ in ranked[:n]]
        print(f"  Selected top {len(symbols)} symbols by volume.")
        return symbols

    def fetch_all(
        self,
        symbols: list,
        tf: str,
        start_date: datetime,
        end_date: datetime,
        lookback_bars: int = 250,
        max_workers: int = 4,
        label: str = "Data",
    ) -> dict:
        tf_minutes = int(tf.replace("m", "")) if "m" in tf else int(tf.replace("h", "")) * 60
        lookback_delta = timedelta(minutes=tf_minutes * lookback_bars)
        fetch_start = start_date - lookback_delta
        since_ms = int(fetch_start.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        all_data = {}
        completed = 0
        total = len(symbols)
        t0 = time.time()

        print(f"\n  Fetching {tf} data for {total} symbols...")

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_fetch_single_symbol, self.exchange, sym, tf, since_ms, end_ms, start_str, end_str): sym
                for sym in symbols
            }

            for future in as_completed(futures):
                completed += 1
                sym, df = future.result()
                if not df.empty and len(df) > 200:
                    all_data[sym] = df
                elapsed = time.time() - t0
                eta = elapsed / completed * (total - completed) if completed > 0 else 0
                print(f"\r  [{label}] {completed}/{total} | {sym:<20} | ETA: {int(eta)}s   ", end="", flush=True)

        print(f"\n  Fetched {len(all_data)}/{total} symbols in {time.time() - t0:.1f}s")
        return all_data

    def prepare_backtest_data(
        self,
        symbols: list,
        start_date: datetime,
        end_date: datetime,
    ) -> tuple:
        tf_str = f"{CANDLE_TF_MIN}m"

        all_data_raw = self.fetch_all(symbols, tf_str, start_date, end_date, label="Primary")

        print(f"\n  Computing indicators for {len(all_data_raw)} symbols...")
        all_data = {}
        for sym, df in all_data_raw.items():
            try:
                df = compute_indicators(df)
                all_data[sym] = df
            except Exception:
                pass

        htf_data_raw = self.fetch_all(
            list(all_data.keys()), "4h", start_date, end_date,
            lookback_bars=250, label="HTF",
        )

        htf_data = {}
        for sym, df in htf_data_raw.items():
            if len(df) >= 200:
                df["ema_50"] = df["close"].ewm(span=HTF_EMA_FAST, adjust=False).mean()
                df["ema_200"] = df["close"].ewm(span=HTF_EMA_SLOW, adjust=False).mean()
                htf_data[sym] = df

        print(f"\n  Ready: {len(all_data)} symbols with {tf_str}, {len(htf_data)} with 4h HTF")
        return all_data, htf_data

    @staticmethod
    def clear_cache():
        count = 0
        for f in CACHE_DIR.glob("*.parquet"):
            f.unlink()
            count += 1
        print(f"  Cleared {count} cached files.")
