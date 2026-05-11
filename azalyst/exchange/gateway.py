from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, List, Optional

import ccxt
import pandas as pd

from azalyst.exchange.state import StateManager
from azalyst.exchange.binance_ws import BinanceWebSocketManager
from azalyst.logger import logger


_BOOTSTRAP_DELAY = 3.0
_RECONCILE_INTERVAL = 600
_KLINE_HISTORY_LIMIT = 260


class ExchangeGateway:

    def __init__(self, api_key: str = "", api_secret: str = "",
                 testnet: bool = False, is_live: bool = False):
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._is_live = is_live
        self._state = StateManager()
        self._ws: Optional[BinanceWebSocketManager] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._markets: dict = {}
        self._exchange = self._build_exchange()
        self._symbols: List[str] = []
        self._timeframes: List[str] = []

    @property
    def state(self) -> StateManager:
        return self._state

    @property
    def is_connected(self) -> bool:
        if self._ws:
            return self._ws.is_connected
        return False

    def _build_exchange(self) -> ccxt.binanceusdm:
        config = {"enableRateLimit": True}
        if self._api_key and self._api_secret:
            config["apiKey"] = self._api_key
            config["secret"] = self._api_secret
        exchange = ccxt.binanceusdm(config)
        if self._testnet:
            exchange.set_sandbox_mode(True)
        return exchange

    def _safe_execute(self, func_name: str, *args, **kwargs):
        endpoints = [
            "https://fapi.binance.com",
            "https://fapi1.binance.com",
            "https://fapi2.binance.com"
        ]
        last_exception = None
        for url in endpoints:
            try:
                self._exchange.urls['api']['fapi'] = url
                method = getattr(self._exchange, func_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                if "418" in err_msg or "1003" in err_msg or "ddos" in err_msg:
                    logger.debug(f"Gateway endpoint {url} blocked, trying next...")
                    continue
                raise e
        logger.warning(f"Gateway: All endpoints blocked. Skipping {func_name}.")
        return None

    def load_markets(self) -> dict:
        for attempt in range(3):
            try:
                self._markets = self._safe_execute("load_markets")
                self._state.build_symbol_maps(self._markets)
                return self._markets
            except Exception as e:
                logger.error(f"load_markets attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return {}

    def start(self, symbols: List[str], timeframes: List[str]):
        if self._running:
            return

        self._symbols = symbols
        self._timeframes = timeframes
        self._running = True

        if not self._markets:
            self.load_markets()

        logger.info(f"Gateway bootstrapping {len(symbols)} symbols with {len(timeframes)} timeframes")
        self._bootstrap_kline_history(symbols, timeframes)

        if self._is_live and self._api_key:
            self._bootstrap_balance()

        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

        deadline = time.time() + 30
        while time.time() < deadline:
            if self._ws and self._ws.is_connected:
                logger.info("Gateway WebSocket connected")
                return
            time.sleep(0.5)
        logger.warn("Gateway WS connection timed out, continuing anyway")

    def stop(self):
        self._running = False
        if self._loop and self._ws:
            future = asyncio.run_coroutine_threadsafe(self._ws.stop(), self._loop)
            try:
                future.result(timeout=10)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Gateway shut down")

    def update_symbols(self, symbols: List[str]):
        self._symbols = symbols
        new_syms = [s for s in symbols if not self._state.has_klines(s, self._timeframes[0])]
        if new_syms:
            logger.info(f"Gateway bootstrapping {len(new_syms)} new symbols")
            self._bootstrap_kline_history(new_syms, self._timeframes)
            if self._loop and self._ws:
                ws_syms = [self._state.ccxt_to_ws(s) for s in new_syms]
                streams = BinanceWebSocketManager.build_stream_list(ws_syms, self._timeframes)
                asyncio.run_coroutine_threadsafe(
                    self._ws.stop(), self._loop
                ).result(timeout=10)
                all_ws_syms = [self._state.ccxt_to_ws(s) for s in self._symbols]
                all_streams = BinanceWebSocketManager.build_stream_list(all_ws_syms, self._timeframes)
                self._ws = BinanceWebSocketManager(
                    self._state,
                    api_key=self._api_key if self._is_live else "",
                    api_secret=self._api_secret if self._is_live else "",
                    testnet=self._testnet,
                )
                asyncio.run_coroutine_threadsafe(
                    self._ws.start(all_streams), self._loop
                )

    def get_ohlcv_df(self, symbol: str, tf: str, limit: int = 250) -> pd.DataFrame:
        return self._state.get_ohlcv_df(symbol, tf, limit)

    def get_ticker(self, symbol: str) -> Optional[dict]:
        return self._state.get_ticker(symbol)

    def get_balance(self) -> Optional[float]:
        return self._state.get_balance()

    def get_position(self, symbol: str) -> Optional[dict]:
        return self._state.get_position(symbol)

    def get_health(self) -> dict:
        return {
            "running": self._running,
            "ws_public": self._ws.public_state if self._ws else "not_started",
            "ws_user": self._ws.user_state if self._ws else "not_started",
            "stale_streams": self._state.get_stale_streams(),
            "symbols_tracked": len(self._symbols),
        }

    def _bootstrap_kline_history(self, symbols: List[str], timeframes: List[str]):
        total = len(symbols) * len(timeframes)
        done = 0
        for symbol in symbols:
            for tf in timeframes:
                done += 1
                for attempt in range(3):
                    try:
                        ohlcv = self._safe_execute(
                            "fetch_ohlcv", symbol, tf, limit=_KLINE_HISTORY_LIMIT
                        )
                        if ohlcv:
                            self._state.seed_klines(symbol, tf, ohlcv)
                        elif ohlcv is None: # All endpoints blocked
                            break 
                        break
                    except Exception as e:
                        if attempt < 2:
                            wait = (attempt + 1) * 1.5
                            logger.warn(f"Bootstrap {symbol} {tf} retry {attempt + 1}: {e}")
                            time.sleep(wait)
                        else:
                            logger.error(f"Bootstrap {symbol} {tf} failed: {e}")
                time.sleep(_BOOTSTRAP_DELAY)

                if done % 10 == 0:
                    logger.info(f"Bootstrap progress: {done}/{total}")

        logger.info(f"Bootstrap complete: {done}/{total} kline sets loaded")

    def _bootstrap_balance(self):
        try:
            balance = self._exchange.fetch_balance()
            total = float(balance.get("total", {}).get("USDT", 0) or 0)
            available = float(balance.get("free", {}).get("USDT", 0) or 0)
            self._state.update_balance(total, available)
            logger.info(f"Bootstrap balance: ${total:.2f}")
        except Exception as e:
            logger.error(f"Bootstrap balance failed: {e}")

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        ws_symbols = [self._state.ccxt_to_ws(s) for s in self._symbols]
        streams = BinanceWebSocketManager.build_stream_list(ws_symbols, self._timeframes)

        self._ws = BinanceWebSocketManager(
            self._state,
            api_key=self._api_key if self._is_live else "",
            api_secret=self._api_secret if self._is_live else "",
            testnet=self._testnet,
        )

        async def _main():
            await self._ws.start(streams)
            while self._running:
                await asyncio.sleep(1)
            await self._ws.stop()

        try:
            self._loop.run_until_complete(_main())
        except Exception as e:
            if self._running:
                logger.error(f"WS event loop error: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
