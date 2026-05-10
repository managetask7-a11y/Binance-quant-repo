from __future__ import annotations

from abc import ABC, abstractmethod


class BaseBroker(ABC):

    @abstractmethod
    def validate_connection(self) -> dict:
        ...

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        ...

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> None:
        ...

    @abstractmethod
    def load_markets(self) -> dict:
        ...

    @abstractmethod
    def cancel_symbol_orders(self, symbol: str) -> None:
        ...

    @property
    @abstractmethod
    def is_live(self) -> bool:
        ...
