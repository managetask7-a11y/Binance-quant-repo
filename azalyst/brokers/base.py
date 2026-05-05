from __future__ import annotations

from abc import ABC, abstractmethod


class BaseBroker(ABC):

    @abstractmethod
    def validate_connection(self) -> dict:
        ...

    @abstractmethod
    def fetch_wallet_balance(self) -> float:
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
    def fetch_tickers(self) -> dict:
        ...

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> dict:
        ...

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list:
        ...

    @abstractmethod
    def fetch_trade_history(self, symbol: str, limit: int) -> list:
        ...

    @abstractmethod
    def fetch_position(self, symbol: str) -> dict:
        ...

    @property
    @abstractmethod
    def is_live(self) -> bool:
        ...
