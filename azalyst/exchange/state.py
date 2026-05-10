from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, Optional

import pandas as pd


_KLINE_BUFFER = 350


class StateManager:

    def __init__(self):
        self._lock = threading.Lock()
        self._tickers: Dict[str, dict] = {}
        self._klines: Dict[str, Dict[str, deque]] = {}
        self._balance: dict = {"total": 0.0, "available": 0.0, "ts": 0.0}
        self._positions: Dict[str, dict] = {}
        self._order_updates: deque = deque(maxlen=500)
        self._symbol_map: Dict[str, str] = {}
        self._reverse_map: Dict[str, str] = {}
        self._last_ticker_ts: float = 0.0
        self._last_kline_ts: Dict[str, float] = {}
        self._last_user_ts: float = 0.0

    def build_symbol_maps(self, markets: dict):
        with self._lock:
            for ccxt_sym, info in markets.items():
                if not ccxt_sym.endswith("/USDT:USDT"):
                    continue
                binance_id = info.get("id", "")
                if not binance_id:
                    binance_id = ccxt_sym.split(":")[0].replace("/", "").upper()
                lower = binance_id.lower()
                self._symbol_map[lower] = ccxt_sym
                self._reverse_map[ccxt_sym] = lower

    def ccxt_to_ws(self, ccxt_symbol: str) -> str:
        with self._lock:
            cached = self._reverse_map.get(ccxt_symbol)
            if cached:
                return cached
        raw = ccxt_symbol.split(":")[0].replace("/", "").lower()
        with self._lock:
            self._reverse_map[ccxt_symbol] = raw
            self._symbol_map[raw] = ccxt_symbol
        return raw

    def ws_to_ccxt(self, ws_symbol: str) -> Optional[str]:
        with self._lock:
            return self._symbol_map.get(ws_symbol.lower())

    def seed_klines(self, ccxt_symbol: str, tf: str, ohlcv_rows: list):
        with self._lock:
            if ccxt_symbol not in self._klines:
                self._klines[ccxt_symbol] = {}
            buf = deque(maxlen=_KLINE_BUFFER)
            for row in ohlcv_rows:
                buf.append(list(row))
            self._klines[ccxt_symbol][tf] = buf
            key = f"{ccxt_symbol}:{tf}"
            self._last_kline_ts[key] = time.time()

    def update_ticker(self, ws_symbol: str, price: float, volume: float = 0.0):
        ccxt_sym = self.ws_to_ccxt(ws_symbol)
        if not ccxt_sym:
            return
        with self._lock:
            self._tickers[ccxt_sym] = {
                "last": price,
                "bid": price,
                "ask": price,
                "quoteVolume": volume,
                "timestamp": time.time(),
            }
            self._last_ticker_ts = time.time()

    def update_kline(self, ws_symbol: str, tf: str, kline: dict, is_closed: bool):
        ccxt_sym = self.ws_to_ccxt(ws_symbol)
        if not ccxt_sym:
            return
        row = [
            int(kline["t"]),
            float(kline["o"]),
            float(kline["h"]),
            float(kline["l"]),
            float(kline["c"]),
            float(kline["v"]),
        ]
        with self._lock:
            if ccxt_sym not in self._klines:
                self._klines[ccxt_sym] = {}
            if tf not in self._klines[ccxt_sym]:
                self._klines[ccxt_sym][tf] = deque(maxlen=_KLINE_BUFFER)
            buf = self._klines[ccxt_sym][tf]
            if is_closed:
                if buf and buf[-1][0] == row[0]:
                    buf[-1] = row
                else:
                    buf.append(row)
                key = f"{ccxt_sym}:{tf}"
                self._last_kline_ts[key] = time.time()
            else:
                if buf and buf[-1][0] == row[0]:
                    buf[-1] = row

    def update_balance(self, total: float, available: float):
        with self._lock:
            self._balance = {"total": total, "available": available, "ts": time.time()}
            self._last_user_ts = time.time()

    def update_position(self, ws_symbol: str, side: str, qty: float,
                        entry_price: float, unrealized_pnl: float):
        ccxt_sym = self.ws_to_ccxt(ws_symbol)
        if not ccxt_sym:
            return
        with self._lock:
            if qty == 0.0:
                self._positions.pop(ccxt_sym, None)
            else:
                self._positions[ccxt_sym] = {
                    "symbol": ccxt_sym,
                    "side": side,
                    "contracts": qty,
                    "size": qty,
                    "entryPrice": entry_price,
                    "unrealizedPnl": unrealized_pnl,
                }

    def add_order_update(self, update: dict):
        with self._lock:
            self._order_updates.append(update)

    def get_ticker(self, ccxt_symbol: str) -> Optional[dict]:
        with self._lock:
            data = self._tickers.get(ccxt_symbol)
            return dict(data) if data else None

    def get_all_tickers(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._tickers.items()}

    def get_ohlcv_df(self, ccxt_symbol: str, tf: str, limit: int = 250) -> pd.DataFrame:
        with self._lock:
            sym_klines = self._klines.get(ccxt_symbol, {})
            buf = sym_klines.get(tf)
            if not buf:
                return pd.DataFrame()
            rows = list(buf)

        if len(rows) > limit:
            rows = rows[-limit:]

        if not rows:
            return pd.DataFrame()

        now_ms = int(time.time() * 1000)
        tf_ms = self._tf_to_ms(tf)
        if rows and (rows[-1][0] + tf_ms) > now_ms:
            rows = rows[:-1]

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df

    def get_balance(self) -> Optional[float]:
        with self._lock:
            if self._balance["ts"] == 0.0:
                return None
            return self._balance["total"]

    def get_position(self, ccxt_symbol: str) -> Optional[dict]:
        with self._lock:
            data = self._positions.get(ccxt_symbol)
            return dict(data) if data else None

    def has_klines(self, ccxt_symbol: str, tf: str, min_bars: int = 200) -> bool:
        with self._lock:
            sym_klines = self._klines.get(ccxt_symbol, {})
            buf = sym_klines.get(tf)
            if not buf:
                return False
            return len(buf) >= min_bars

    def get_stale_streams(self, max_age: float = 120.0) -> list:
        now = time.time()
        stale = []
        with self._lock:
            if self._last_ticker_ts > 0 and (now - self._last_ticker_ts) > max_age:
                stale.append("tickers")
            for key, ts in self._last_kline_ts.items():
                if (now - ts) > max_age * 10:
                    stale.append(f"kline:{key}")
        return stale

    @staticmethod
    def _tf_to_ms(tf: str) -> int:
        if tf.endswith("m"):
            return int(tf[:-1]) * 60 * 1000
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600 * 1000
        if tf.endswith("d"):
            return int(tf[:-1]) * 86400 * 1000
        return 15 * 60 * 1000
