from __future__ import annotations

import time

import ccxt

from azalyst.brokers.base import BaseBroker
from azalyst.logger import logger

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

    def _safe_execute(self, func_name: str, *args, **kwargs):
        """Executes a method with automatic fallback to stealth endpoint if blocked."""
        endpoints = [
            "https://fapi.binance.com",
            "https://fapi1.binance.com",
            "https://fapi2.binance.com"
        ]
        
        last_exception = None
        for i, url in enumerate(endpoints):
            try:
                self._exchange.urls['api']['fapi'] = url
                method = getattr(self._exchange, func_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                # If it's a rate limit or IP ban, try the next endpoint
                if "418" in err_msg or "1003" in err_msg or "ddos" in err_msg:
                    logger.debug(f"Endpoint {url} blocked, trying next...")
                    continue
                # For other errors (like balance or leverage limits), don't retry on other endpoints
                raise e
        
        # If we reach here, ALL endpoints are blocked. 
        # Log it and return None instead of crashing.
        logger.warning(f"CRITICAL: All Binance endpoints are currently blocking IP {self._exchange.enableRateLimit}. Skipping {func_name}.")
        return None

    @property
    def is_live(self) -> bool:
        return True

    @property
    def testnet(self) -> bool:
        return self._testnet

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def api_secret(self) -> str:
        return self._api_secret

    def validate_connection(self) -> dict:
        try:
            balance_data = self._exchange.fetch_balance()
            usdt_balance = float(
                balance_data.get("USDT", {}).get("total", 0.0) or
                balance_data.get("total", {}).get("USDT", 0.0)
            )
            permissions = set(getattr(self._exchange, "apiPermissions", None) or [])
            missing = {"TRADE", "FUTURES"} - permissions if permissions else set()
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

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        return self._safe_execute("create_market_order", symbol, side, qty)

    def set_leverage(self, symbol: str, leverage: int = 10):
        # We still want the 15->10->5 fallback logic inside the safe_execute
        leverages = [leverage, 10, 5, 1]
        for lev in leverages:
            if lev > leverage: continue
            try:
                res = self._safe_execute("set_leverage", lev, symbol)
                if res is None: break # All endpoints blocked, stop trying for this cycle
                return
            except Exception as e:
                if "4028" in str(e) or "invalid" in str(e).lower():
                    continue
                # For other errors, we can log it but don't crash
                logger.warning(f"Leverage error for {symbol}: {e}")
                break

    def place_sl_tp(self, symbol: str, side: str, qty: float, sl_price: float, tp_price: float) -> dict:
        logger.info(f"Virtual SL/TP set for {symbol} | SL: ${sl_price:.4f} | TP: ${tp_price:.4f}")
        return {"sl": None, "tp": None}

    def cancel_symbol_orders(self, symbol: str) -> None:
        try:
            self._safe_execute("cancel_all_orders", symbol)
        except Exception as e:
            logger.error(f"Failed to cancel orders for {symbol}: {e}")

    def load_markets(self) -> dict:
        return self._safe_execute("load_markets")
