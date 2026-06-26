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
        self._exchange = self._build_exchange(testnet=testnet)
        self._public_exchange = self._build_exchange(testnet=False)
        self._trading_markets = None

    def _build_exchange(self, testnet: bool) -> ccxt.binance:
        exchange = ccxt.binanceusdm({
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "enableRateLimit": True,
        })
        if testnet:
            exchange.enable_demo_trading(True)
        return exchange

    @property
    def is_live(self) -> bool:
        return True

    @property
    def testnet(self) -> bool:
        return self._testnet

    def get_trading_markets(self) -> list:
        if self._trading_markets is None:
            try:
                self._trading_markets = list(self._exchange.load_markets().keys())
            except Exception as e:
                logger.error(f"Failed to load trading markets: {e}")
                self._trading_markets = []
        return self._trading_markets

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
            exc_str = str(exc).lower()
            if "banned" in exc_str or "1003" in exc_str or "teapot" in exc_str:
                now = time.time()
                last_alert = getattr(self, "_last_ban_alert_time", 0)
                if now - last_alert > 3600:  # 1 hour cooldown
                    from azalyst.notifications import send_alerts
                    send_alerts("🚨 BINANCE API IP BAN", f"Your IP has been banned/rate-limited by Binance!\n\nDetails:\n`{exc}`")
                    self._last_ban_alert_time = now
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

    def set_margin_mode(self, symbol: str, margin_mode: str) -> None:
        try:
            # margin_mode should be 'ISOLATED' or 'CROSS'
            self._exchange.set_margin_mode(margin_mode, symbol)
            logger.info(f"🛡️ Set margin mode for {symbol} to {margin_mode}")
        except Exception as exc:
            # Binance often errors if the mode is already set, so we treat it as a warning
            if "No need to change" not in str(exc):
                logger.warning(f"Could not set margin mode for {symbol}: {exc}")

    def place_native_orders(self, symbol: str, entry_side: str, qty: float, sl_price: float, tp_price: float, callback_rate: float, activation_price: float = None) -> dict:
        """
        Submits physical STOP_MARKET, TAKE_PROFIT_MARKET and TRAILING_STOP_MARKET orders to Binance.
        """
        # The exit side is opposite of the entry side
        exit_side = "sell" if entry_side.lower() == "buy" else "buy"
        
        sl_order = None
        tp_order = None
        trail_order = None
        
        try:
            # 1. Hard Stop Loss
            sl_order = self._exchange.create_order(
                symbol=symbol,
                type="STOP_MARKET",
                side=exit_side,
                amount=qty,
                params={
                    "stopPrice": sl_price,
                    "reduceOnly": True
                }
            )
            logger.info(f"📍 Native SL set for {symbol} at ${sl_price:.4f}")
        except Exception as e:
            logger.error(f"Failed to place Native SL for {symbol}: {e}")

        try:
            # 2. Take Profit
            tp_order = self._exchange.create_order(
                symbol=symbol,
                type="TAKE_PROFIT_MARKET",
                side=exit_side,
                amount=qty,
                params={
                    "stopPrice": tp_price,
                    "reduceOnly": True
                }
            )
            logger.info(f"📍 Native TP set for {symbol} at ${tp_price:.4f}")
        except Exception as e:
            logger.error(f"Failed to place Native TP for {symbol}: {e}")

        try:
            # 3. Trailing Stop Loss (Activates in profit)
            trail_params = {
                "callbackRate": round(callback_rate, 1),
                "reduceOnly": True
            }
            if activation_price:
                trail_params["activationPrice"] = activation_price
                
            trail_order = self._exchange.create_order(
                symbol=symbol,
                type="TRAILING_STOP_MARKET",
                side=exit_side,
                amount=qty,
                params=trail_params
            )
            logger.info(f"📍 Native Trailing SL set | Activation: ${activation_price:.4f} | Callback: {callback_rate:.1f}%")
        except Exception as e:
            logger.error(f"Failed to place Native Trailing SL for {symbol}: {e}")

        return {"sl": sl_order, "tp": tp_order, "trail": trail_order}

    def cancel_symbol_orders(self, symbol: str) -> None:
        """Cancel all open orders for a specific symbol (clean up SL/TP)"""
        try:
            self._exchange.cancel_all_orders(symbol)
            logger.info(f"🧹 Cancelled all open orders for {symbol}")
        except Exception as e:
            logger.error(f"Failed to cancel orders for {symbol}: {e}")

    def load_markets(self) -> dict:
        return self._public_exchange.load_markets()

    def fetch_tickers(self) -> dict:
        return self._public_exchange.fetch_tickers()

    def fetch_ticker(self, symbol: str) -> dict:
        # --- ANTI-BAN DELAY: 2s cooldown per ticker fetch ---
        time.sleep(2)
        return self._public_exchange.fetch_ticker(symbol)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list:
        return self._public_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

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
