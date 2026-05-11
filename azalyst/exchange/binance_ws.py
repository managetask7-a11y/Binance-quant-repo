from __future__ import annotations

import asyncio
import json
import time
import hashlib
import hmac
from enum import Enum
from typing import Callable, Dict, List, Optional

import aiohttp

from azalyst.exchange.state import StateManager
from azalyst.logger import logger


_BASE_WS_LIVE = "wss://fstream.binance.com"
_BASE_WS_TESTNET = "wss://stream.binancefuture.com"
_BASE_REST_LIVE = "https://fapi.binance.com"
_BASE_REST_TESTNET = "https://testnet.binancefuture.com"

_MAX_STREAMS_PER_CONN = 190
_HEARTBEAT_INTERVAL = 30
_STALE_THRESHOLD = 90
_LISTEN_KEY_REFRESH = 1800
_MAX_BACKOFF = 60
_INITIAL_BACKOFF = 1


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


class BinanceWebSocketManager:

    def __init__(self, state: StateManager, api_key: str = "",
                 api_secret: str = "", testnet: bool = False):
        self._state = state
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._base_ws = _BASE_WS_TESTNET if testnet else _BASE_WS_LIVE
        self._base_rest = _BASE_REST_TESTNET if testnet else _BASE_REST_LIVE
        self._running = False
        self._public_state = ConnectionState.DISCONNECTED
        self._user_state = ConnectionState.DISCONNECTED
        self._listen_key: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._tasks: List[asyncio.Task] = []
        self._public_backoff = _INITIAL_BACKOFF
        self._user_backoff = _INITIAL_BACKOFF
        self._streams: List[str] = []
        self._subscribed_symbols: set = set()
        
        # Proxy Configuration
        import os
        self._proxy_host = os.getenv("PROXY_HOST", "dc.oxylabs.io")
        self._proxy_user = os.getenv("PROXY_USER")
        self._proxy_pass = os.getenv("PROXY_PASS")
        self._proxy_ports = [8001, 8002, 8003, 8004, 8005]
        self._current_proxy_idx = 0

    def _get_current_proxy(self) -> Optional[str]:
        if not self._proxy_user or not self._proxy_pass:
            return None
        port = self._proxy_ports[self._current_proxy_idx]
        return f"http://{self._proxy_user}:{self._proxy_pass}@{self._proxy_host}:{port}"

    def _rotate_proxy(self):
        self._current_proxy_idx = (self._current_proxy_idx + 1) % len(self._proxy_ports)
        logger.info(f"🔄 Rotating WS proxy to port {self._proxy_ports[self._current_proxy_idx]}...")

    @property
    def is_connected(self) -> bool:
        return self._public_state == ConnectionState.CONNECTED

    @property
    def public_state(self) -> str:
        return self._public_state.value

    @property
    def user_state(self) -> str:
        return self._user_state.value

    async def start(self, streams: List[str]):
        self._running = True
        self._streams = streams
        self._session = aiohttp.ClientSession()

        self._tasks.append(asyncio.create_task(self._run_public(streams)))

        if self._api_key and self._api_secret:
            self._tasks.append(asyncio.create_task(self._run_user_data()))
            self._tasks.append(asyncio.create_task(self._listen_key_keepalive()))

        self._tasks.append(asyncio.create_task(self._health_monitor()))

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        if self._session and not self._session.closed:
            await self._session.close()
        self._public_state = ConnectionState.CLOSED
        self._user_state = ConnectionState.CLOSED
        logger.info("WebSocket manager shut down")

    async def _run_public(self, streams: List[str]):
        while self._running:
            try:
                self._public_state = ConnectionState.CONNECTING
                url = self._build_combined_url(streams)
                proxy = self._get_current_proxy()
                
                async with self._session.ws_connect(
                    url,
                    proxy=proxy,
                    heartbeat=_HEARTBEAT_INTERVAL,
                    timeout=aiohttp.ClientWSTimeout(ws_close=10),
                ) as ws:
                    self._public_state = ConnectionState.CONNECTED
                    self._public_backoff = _INITIAL_BACKOFF
                    logger.info(f"WS public connected ({len(streams)} streams)")

                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_public_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WS public error: {ws.exception()}")
                            break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                            break

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"WS public connection failed: {e}")

            if not self._running:
                return

            self._public_state = ConnectionState.RECONNECTING
            wait = min(self._public_backoff, _MAX_BACKOFF)
            logger.info(f"WS public reconnecting in {wait}s")
            await asyncio.sleep(wait)
            self._public_backoff = min(self._public_backoff * 2, _MAX_BACKOFF)

    async def _run_user_data(self):
        while self._running:
            try:
                self._user_state = ConnectionState.CONNECTING
                listen_key = await self._create_listen_key()
                if not listen_key:
                    await asyncio.sleep(5)
                    continue

                self._listen_key = listen_key
                url = f"{self._base_ws}/ws/{listen_key}"
                proxy = self._get_current_proxy()
                logger.info(f"WS user data stream connecting via proxy {self._proxy_ports[self._current_proxy_idx]}")

                async with self._session.ws_connect(
                    url,
                    proxy=proxy,
                    heartbeat=_HEARTBEAT_INTERVAL,
                    timeout=aiohttp.ClientWSTimeout(ws_close=10),
                ) as ws:
                    self._user_state = ConnectionState.CONNECTED
                    self._user_backoff = _INITIAL_BACKOFF
                    logger.info("WS user data stream connected")

                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_user_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WS user error: {ws.exception()}")
                            break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                            break

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"WS user data connection failed: {e}")
                if "418" in str(e) or "1003" in str(e):
                    self._rotate_proxy()

            if not self._running:
                return

            self._user_state = ConnectionState.RECONNECTING
            wait = min(self._user_backoff, _MAX_BACKOFF)
            logger.info(f"WS user data reconnecting in {wait}s")
            await asyncio.sleep(wait)
            self._user_backoff = min(self._user_backoff * 2, _MAX_BACKOFF)

    async def _handle_public_message(self, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        if "stream" not in data or "data" not in data:
            return

        stream = data["stream"]
        payload = data["data"]

        if stream == "!miniTicker@arr":
            for item in payload:
                sym = item.get("s", "").lower()
                price = float(item.get("c", 0))
                volume = float(item.get("q", 0))
                self._state.update_ticker(sym, price, volume)
            return

        if "@kline_" in stream:
            kline = payload.get("k", {})
            ws_sym = kline.get("s", "").lower()
            tf = kline.get("i", "")
            is_closed = kline.get("x", False)
            self._state.update_kline(ws_sym, tf, kline, is_closed)
            return

        if "@miniTicker" in stream and "@arr" not in stream:
            sym = payload.get("s", "").lower()
            price = float(payload.get("c", 0))
            volume = float(payload.get("q", 0))
            self._state.update_ticker(sym, price, volume)

    async def _handle_user_message(self, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        event_type = data.get("e", "")

        if event_type == "ACCOUNT_UPDATE":
            account = data.get("a", {})
            balances = account.get("B", [])
            for b in balances:
                if b.get("a") == "USDT":
                    total = float(b.get("wb", 0))
                    available = float(b.get("cw", 0))
                    self._state.update_balance(total, available)
                    break

            positions = account.get("P", [])
            for p in positions:
                ws_sym = p.get("s", "").lower()
                qty = abs(float(p.get("pa", 0)))
                side = "long" if float(p.get("pa", 0)) > 0 else "short"
                entry = float(p.get("ep", 0))
                upnl = float(p.get("up", 0))
                self._state.update_position(ws_sym, side, qty, entry, upnl)

        elif event_type == "ORDER_TRADE_UPDATE":
            order = data.get("o", {})
            self._state.add_order_update({
                "symbol": order.get("s", ""),
                "side": order.get("S", ""),
                "type": order.get("o", ""),
                "status": order.get("X", ""),
                "price": float(order.get("p", 0)),
                "qty": float(order.get("q", 0)),
                "filled_qty": float(order.get("z", 0)),
                "avg_price": float(order.get("ap", 0)),
                "realized_pnl": float(order.get("rp", 0)),
                "timestamp": int(order.get("T", 0)),
            })

        elif event_type == "listenKeyExpired":
            logger.warn("WS listenKey expired, will reconnect")

    async def _create_listen_key(self) -> Optional[str]:
        try:
            url = f"{self._base_rest}/fapi/v1/listenKey"
            headers = {"X-MBX-APIKEY": self._api_key}
            proxy = self._get_current_proxy()
            async with self._session.post(url, headers=headers, proxy=proxy) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("listenKey")
                if resp.status == 418:
                    self._rotate_proxy()
                logger.error(f"Failed to create listenKey: HTTP {resp.status}")
                return None
        except Exception as e:
            logger.error(f"Failed to create listenKey: {e}")
            return None

    async def _refresh_listen_key(self):
        if not self._listen_key:
            return
        try:
            url = f"{self._base_rest}/fapi/v1/listenKey"
            headers = {"X-MBX-APIKEY": self._api_key}
            proxy = self._get_current_proxy()
            async with self._session.put(url, headers=headers, proxy=proxy) as resp:
                if resp.status != 200:
                    if resp.status == 418:
                        self._rotate_proxy()
                    logger.warn(f"listenKey refresh failed: HTTP {resp.status}")
        except Exception as e:
            logger.warn(f"listenKey refresh error: {e}")

    async def _listen_key_keepalive(self):
        while self._running:
            try:
                await asyncio.sleep(_LISTEN_KEY_REFRESH)
                if self._running and self._listen_key:
                    await self._refresh_listen_key()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"listenKey keepalive error: {e}")

    async def _health_monitor(self):
        while self._running:
            try:
                await asyncio.sleep(60)
                stale = self._state.get_stale_streams()
                if stale:
                    logger.warn(f"Stale streams detected: {stale}")
            except asyncio.CancelledError:
                return
            except Exception:
                pass

    def _build_combined_url(self, streams: List[str]) -> str:
        stream_path = "/".join(streams[:_MAX_STREAMS_PER_CONN])
        return f"{self._base_ws}/stream?streams={stream_path}"

    @staticmethod
    def build_stream_list(ws_symbols: List[str], timeframes: List[str]) -> List[str]:
        streams = []
        for sym in ws_symbols:
            for tf in timeframes:
                streams.append(f"{sym}@kline_{tf}")
        streams.append("!miniTicker@arr")
        return streams
