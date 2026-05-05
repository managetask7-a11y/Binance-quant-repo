from __future__ import annotations

import time

import ccxt

from azalyst.brokers.base import BaseBroker
from azalyst.logger import logger

_REQUIRED_PERMISSIONS = {"TRADE", "FUTURES"}
_MAX_RETRIES = 3


class LiveBinanceBroker(BaseBroker):

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._exchange = self._build_exchange()

    def _build_exchange(self) -> ccxt.binance:
        exchange = ccxt.binanceusdm({
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "enableRateLimit": True,
        })
        if self._testnet:
            exchange.set_sandbox_mode(True)
        return exchange

    @property
    def is_live(self) -> bool:
        return True

    @property
    def testnet(self) -> bool:
        return self._testnet

    def validate_connection(self) -> dict:
        try:
            balance_data = self._exchange.fetch_balance()
            usdt_balance = float(
                balance_data.get("USDT", {}).get("total", 0.0) or
                balance_data.get("total", {}).get("USDT", 0.0)
            )
            permissions = set(getattr(self._exchange, "apiPermissions", None) or [])
            missing = _REQUIRED_PERMISSIONS - permissions if permissions else set()
            return {
                "success": True,
                "balance": usdt_balance,
                "permissions": list(permissions),
                "missing_permissions": list(missing),
                "testnet": self._testnet,
            }
        except ccxt.AuthenticationError as exc:
            return {"success": False, "error": "Invalid API key or secret.", "detail": str(exc)}
        except ccxt.InsufficientFunds as exc:
            return {"success": False, "error": "Insufficient funds.", "detail": str(exc)}
        except Exception as exc:
            return {"success": False, "error": "Connection failed.", "detail": str(exc)}

    def fetch_wallet_balance(self) -> float:
        try:
            balance_data = self._exchange.fetch_balance()
            # CCXT binanceusdm balance format can vary. We check 'total' and currency keys.
            total = balance_data.get("total", {})
            val = total.get("USDT")
            if val is None:
                # Try nested format
                val = balance_data.get("USDT", {}).get("total")
            
            return float(val) if val is not None else 0.0
        except Exception as exc:
            logger.error(f"Failed to fetch wallet balance: {exc}")
            return None

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        for attempt in range(_MAX_RETRIES):
            try:
                order = self._exchange.create_market_order(symbol, side, qty)
                return order
            except ccxt.InsufficientFunds as exc:
                raise
            except Exception as exc:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise

    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self._exchange.set_leverage(leverage, symbol)
        except Exception as exc:
            logger.warning(f"Could not set leverage for {symbol}: {exc}")

    def place_sl_tp(self, symbol: str, side: str, qty: float, sl_price: float, tp_price: float) -> dict:
        """
        Virtual Stop Loss and Take Profit tracking.
        We no longer place physical resting orders on Binance. The engine tracks these locally.
        """
        logger.info(f"📍 Virtual SL/TP set for {symbol} | SL: ${sl_price:.4f} | TP: ${tp_price:.4f}")
        return {"sl": None, "tp": None}

    def cancel_symbol_orders(self, symbol: str) -> None:
        """Cancel all open orders for a specific symbol (clean up SL/TP)"""
        try:
            self._exchange.cancel_all_orders(symbol)
            logger.info(f"🧹 Cancelled all open orders for {symbol}")
        except Exception as e:
            logger.error(f"Failed to cancel orders for {symbol}: {e}")

    def load_markets(self) -> dict:
        return self._exchange.load_markets()

    def fetch_tickers(self) -> dict:
        return self._exchange.fetch_tickers()

    def fetch_ticker(self, symbol: str) -> dict:
        return self._exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list:
        return self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_trade_history(self, symbol: str, limit: int) -> list:
        try:
            return self._exchange.fetch_my_trades(symbol, limit=limit)
        except Exception as exc:
            logger.error(f"Failed to fetch trade history for {symbol}: {exc}")
            return []

    def fetch_position(self, symbol: str) -> dict:
        try:
            positions = self._exchange.fetch_positions([symbol])
            if positions:
                return positions[0]
            return None
        except Exception as exc:
            logger.error(f"Failed to fetch position for {symbol}: {exc}")
            return None
