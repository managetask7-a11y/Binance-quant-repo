from __future__ import annotations

from azalyst.brokers.base import BaseBroker


class DemoBroker(BaseBroker):

    def __init__(self):
        pass

    @property
    def is_live(self) -> bool:
        return False

    def validate_connection(self) -> dict:
        return {"success": True, "balance": 0.0, "mode": "demo"}

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        return {"id": "DEMO", "symbol": symbol, "side": side, "qty": qty, "status": "filled"}

    def set_leverage(self, symbol: str, leverage: int) -> None:
        pass

    def cancel_symbol_orders(self, symbol: str) -> None:
        pass

    def load_markets(self) -> dict:
        return {}
