from __future__ import annotations

import pandas as pd

from azalyst.brokers.base import BaseBroker


class DemoBroker(BaseBroker):

    def __init__(self, exchange):
        self._exchange = exchange

    @property
    def is_live(self) -> bool:
        return False

    def validate_connection(self) -> dict:
        return {"success": True, "balance": 0.0, "mode": "demo"}

    def fetch_wallet_balance(self) -> float:
        return 0.0

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        return {"id": "DEMO", "symbol": symbol, "side": side, "qty": qty, "status": "filled"}

    def place_native_orders(self, symbol: str, entry_side: str, qty: float, tp_price: float, callback_rate: float) -> dict:
        """Paper trades use virtual SL/TP tracking in the engine, so we just return None here."""
        return {"tp": None, "trail": None}

    def set_leverage(self, symbol: str, leverage: int) -> None:
        pass

    def load_markets(self) -> dict:
        return self._exchange.load_markets()

    def fetch_tickers(self) -> dict:
        return self._exchange.fetch_tickers()

    def fetch_ticker(self, symbol: str) -> dict:
        return self._exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list:
        return self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_trade_history(self, symbol: str, limit: int) -> list:
        return []

    def fetch_position(self, symbol: str) -> dict:
        return None
