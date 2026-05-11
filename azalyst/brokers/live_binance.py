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
        
        # Smart Proxy Rotation Config (Loaded from .env)
        import os
        self._proxy_host = os.getenv("PROXY_HOST", "dc.oxylabs.io")
        self._proxy_user = os.getenv("PROXY_USER")
        self._proxy_pass = os.getenv("PROXY_PASS")
        self._proxy_ports = [8001, 8002, 8003, 8004, 8005]
        self._current_proxy_idx = 0
        
        self._exchange = self._build_exchange()

    @property
    def is_live(self) -> bool:
        return True

    def _build_exchange(self) -> ccxt.binance:
        config = {
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "enableRateLimit": True,
            "adjustForTimeDifference": True,
            "options": {
                "defaultType": "future",
                "warnOnFetchBalance": False
            }
        }
        
        # Initialize first proxy
        if self._proxy_user and self._proxy_pass:
            port = self._proxy_ports[self._current_proxy_idx]
            proxy = f"http://{self._proxy_user}:{self._proxy_pass}@{self._proxy_host}:{port}"
            logger.info(f"Connecting via Oxylabs Proxy (Port {port})")
            
            config["proxies"] = {
                "http": proxy,
                "https": proxy,
            }
            
        exchange = ccxt.binanceusdm(config)
        if self._testnet:
            exchange.set_sandbox_mode(True)
        return exchange

    def _rotate_proxy(self):
        """Switches to the next available proxy port in the pool."""
        self._current_proxy_idx = (self._current_proxy_idx + 1) % len(self._proxy_ports)
        port = self._proxy_ports[self._current_proxy_idx]
        proxy = f"http://{self._proxy_user}:{self._proxy_pass}@{self._proxy_host}:{port}"
        
        self._exchange.proxies = {
            "http": proxy,
            "https": proxy,
        }
        logger.info(f"🔄 IP Block detected. Rotating to Oxylabs Proxy Port {port}...")

    def _safe_execute(self, func_name: str, *args, **kwargs):
        """Executes a method with automatic proxy rotation if blocked."""
        endpoints = [
            "https://fapi.binance.com",
            "https://fapi1.binance.com",
            "https://fapi2.binance.com",
            "https://fapi3.binance.com",
            "https://fapi4.binance.com",
            "https://fapi5.binance.com"
        ]
        
        for url in endpoints:
            try:
                # Update only the relevant fapi and public/private endpoints
                self._exchange.urls['api']['fapi'] = url
                self._exchange.urls['api']['public'] = url
                self._exchange.urls['api']['private'] = url
                
                method = getattr(self._exchange, func_name)
                return method(*args, **kwargs)
            except Exception as e:
                err_msg = str(e).lower()
                # If it's a rate limit or IP ban, rotate PROXY first, then try next endpoint
                if any(x in err_msg for x in ["418", "1003", "ddos", "blocked", "teapot"]):
                    self._rotate_proxy()
                    logger.debug(f"Endpoint {url} blocked, trying next...")
                    time.sleep(1.5)
                    continue
                raise e
        
        # If we reach here, ALL endpoints AND all proxies might be struggling
        msg = f"CRITICAL: All Binance endpoints and current proxy port are blocked. Skipping {func_name}."
        logger.warning(msg)
        raise RuntimeError(msg)

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
            balance_data = self._safe_execute("fetch_balance")
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

    def fetch_ohlcv(self, symbol: str, tf: str = "15m", limit: int = 250):
        return self._safe_execute("fetch_ohlcv", symbol, tf, limit=limit)

    def fetch_balance(self) -> float:
        try:
            balance_data = self._safe_execute("fetch_balance")
            return float(
                balance_data.get("USDT", {}).get("total", 0.0) or
                balance_data.get("total", {}).get("USDT", 0.0)
            )
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0

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
