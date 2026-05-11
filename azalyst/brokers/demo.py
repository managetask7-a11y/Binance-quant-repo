from __future__ import annotations

from azalyst.brokers.base import BaseBroker


class DemoBroker(BaseBroker):

    def __init__(self):
        import ccxt
        # Use a public exchange instance for data fetching in demo mode
        self._exchange = ccxt.binance({"options": {
            "defaultType": "future",
            "fetchCurrencies": False
        }})
        
        # Add proxy support for demo mode too
        import os
        host = os.getenv("PROXY_HOST", "dc.oxylabs.io")
        user = os.getenv("PROXY_USER")
        pw = os.getenv("PROXY_PASS")
        if user and pw:
            proxy = f"http://{user}:{pw}@{host}:8001"
            self._exchange.proxies = {"http": proxy, "https": proxy}

    @property
    def is_live(self) -> bool:
        return False

    def validate_connection(self) -> dict:
        return {"success": True, "balance": 0.0, "mode": "demo"}

    def fetch_ohlcv(self, symbol: str, tf: str = "15m", limit: int = 250):
        try:
            return self._exchange.fetch_ohlcv(symbol, tf, limit=limit)
        except Exception:
            return []

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        return {"id": "DEMO", "symbol": symbol, "side": side, "qty": qty, "status": "filled"}

    def set_leverage(self, symbol: str, leverage: int) -> None:
        pass

    def cancel_symbol_orders(self, symbol: str) -> None:
        pass

    def load_markets(self) -> dict:
        try:
            return self._exchange.load_markets()
        except Exception:
            return {}
