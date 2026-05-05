from __future__ import annotations

import signal
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from azalyst.brokers.base import BaseBroker
from azalyst.brokers.demo import DemoBroker
from azalyst.brokers.live_binance import LiveBinanceBroker
from azalyst.config import (
    INITIAL_BALANCE, LEVERAGE, RISK_PER_TRADE, ATR_MULT, TP_RR_RATIO,
    SL_MIN_PCT, SL_MAX_PCT, MAX_OPEN_TRADES, MAX_HOLD_SCANS,
    BREAKEVEN_AFTER_SCANS, SCAN_INTERVAL_MIN, CANDLE_TF_MIN,
    PROP_MAX_DRAWDOWN_PCT, PROP_DAILY_LOSS_PCT, SLIPPAGE_BPS,
    BUY, SELL, EXCLUDE_SYMBOLS, MIN_VOLUME_MA, TOP_N_COINS,
    MAX_SAME_DIRECTION, HTF_TIMEFRAME, HTF_CANDLE_LIMIT,
    HTF_EMA_FAST, HTF_EMA_SLOW,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ORDER_CAP_TIERS,
    TRAILING_STOP_ENABLED, REGIME_BTC_SYMBOL,
)
from azalyst.logger import logger
from azalyst.indicators import compute_indicators
from azalyst.consensus import multi_strategy_scan
from azalyst.notifications import send_alerts
from azalyst.regime import MarketRegime, detect as detect_regime, get_regime_details
from azalyst.personalities import get_personality, DEFAULT_PERSONALITY, Personality
from azalyst import db


class LiveTrader:
    def __init__(self, broker: BaseBroker, user_id: str):
        self.broker = broker
        self.user_id = user_id
        self.dry_run = not broker.is_live
        self.balance = INITIAL_BALANCE
        self.initial_balance = INITIAL_BALANCE
        self.live_balance: Optional[float] = None
        self.open_trades: Dict[str, dict] = {}
        self.closed_trades: List[dict] = []
        self.daily_pnl = 0.0
        self.daily_start_balance = INITIAL_BALANCE
        self.scan_count = 0
        self.running = True
        self.paused = False
        self.symbols: List[str] = []
        self.last_scan_time = None
        self.next_scan_time = None
        self.last_symbol_refresh_time = 0.0
        self.equity_curve: List[dict] = []
        self.daily_profit_target = 0.0
        self.daily_target_reached = False
        self._live_prices: Dict[str, float] = {}
        self.current_regime: MarketRegime = MarketRegime.SIDEWAYS
        self.active_personality: Personality = DEFAULT_PERSONALITY

        self.config = {
            "leverage": LEVERAGE,
            "risk_per_trade": RISK_PER_TRADE,
            "atr_mult": ATR_MULT,
            "tp_rr_ratio": TP_RR_RATIO,
            "top_n_coins": TOP_N_COINS,
            "telegram_token": TELEGRAM_BOT_TOKEN,
            "telegram_chat_id": TELEGRAM_CHAT_ID,
        }

        self._load_state()
        self._refresh_config()

        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

        # Initial symbol refresh so we have coins to trade immediately
        self._refresh_top_coins()

    def _shutdown_handler(self, signum, frame):
        logger.info(f"Received shutdown signal. Closing {len(self.open_trades)} open trades...")
        self.running = False

    def _load_state(self):
        """Load last known state (balance, open trades) from DB"""
        if not self.user_id or self.user_id == "None":
            return # Safety guard for initial startup
        try:
            current_mode = "live" if self.broker.is_live else "dry_run"
            rows = db.fetch_open_trades(self.user_id, mode=current_mode)
            for row in rows:
                symbol = row["symbol"]
                self.open_trades[symbol] = {
                    "id": row["id"],
                    "symbol": symbol,
                    "direction": int(row["direction"]),
                    "entry_price": float(row["entry_price"]),
                    "qty": float(row["qty"]),
                    "sl_price": float(row["sl_price"]),
                    "tp_price": float(row["tp_price"]),
                    "sl_dist_pct": float(row.get("sl_dist_pct") or 0),
                    "entry_time": row["entry_time"],
                    "scan_count": int(row.get("scan_count") or 0),
                    "max_price": float(row.get("max_price") or 0),
                    "min_price": float(row.get("min_price") or 0),
                    "signal": row.get("signal", ""),
                    "strategies": row.get("strategies", ""),
                    "atr": float(row.get("atr") or 0),
                }

            closed_rows = db.fetch_closed_trades(self.user_id, mode=current_mode)
            self.closed_trades = closed_rows
            
            # Load historical equity curve for the chart
            equity_rows = db.fetch_equity(self.user_id, mode=current_mode)
            self.equity_curve = equity_rows
            
            # Recalculate historical balance
            historical_pnl = sum(float(row.get("pnl_usd", 0.0)) for row in self.closed_trades)
            self.balance = self.initial_balance + historical_pnl
            
            # If we have equity history, use the last point's balance as current
            if self.equity_curve:
                self.balance = float(self.equity_curve[-1]["balance"])

            # Recalculate daily PnL based on today's closed trades
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self.daily_pnl = sum(
                float(row.get("pnl_usd", 0.0))
                for row in self.closed_trades
                if str(row.get("exit_time", "")).startswith(today_str)
            )

            # Check if paused is saved
            paused = db.get_config(self.user_id, "paused", "false")
            self.paused = (paused == "true")

            logger.info(f"Loaded {len(self.open_trades)} open trades. Restored balance: ${self.balance:.2f}. Today's PnL: ${self.daily_pnl:.2f} for user {self.user_id}")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    def _save_trade(self, trade: dict, status: str = "open"):
        """Save trade to DB with retries for network stability"""
        current_mode = "live" if self.broker.is_live else "dry_run"
        for attempt in range(3):
            try:
                if status == "open" and "id" not in trade:
                    result = db.insert_trade(self.user_id, trade, mode=current_mode)
                    if result:
                        trade["id"] = result["id"]
                elif status == "open" and "id" in trade:
                    db.update_trade(self.user_id, trade["id"], {
                        "sl_price": trade["sl_price"],
                        "tp_price": trade["tp_price"],
                        "max_price": trade.get("max_price", trade["entry_price"]),
                        "min_price": trade.get("min_price", trade["entry_price"]),
                        "scan_count": trade.get("scan_count", 0),
                        "signal": trade.get("signal", "")
                    })
                elif status == "closed" and "id" in trade:
                    db.close_trade_db(
                        self.user_id,
                        trade["id"],
                        trade.get("exit_time", ""),
                        trade.get("exit_price", 0.0),
                        trade.get("pnl_pct", 0.0),
                        trade.get("pnl_usd", 0.0),
                        trade.get("reason", "")
                    )
                return # Success
            except Exception as e:
                if "10035" in str(e) or "non-blocking" in str(e):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                logger.error(f"Failed to save trade (attempt {attempt+1}): {e}")
                time.sleep(1)

    def _log_equity(self):
        """Log equity point to DB with retries for network stability"""
        point = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance": self.balance,
            "open_trades": len(self.open_trades),
            "daily_pnl": self.daily_pnl,
        }
        self.equity_curve.append(point)

        current_mode = "live" if self.broker.is_live else "dry_run"
        for attempt in range(3):
            try:
                db.insert_equity(self.user_id, point, mode=current_mode)
                return # Success
            except Exception as e:
                if "10035" in str(e) or "non-blocking" in str(e):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                logger.error(f"Failed to log equity (attempt {attempt+1}): {e}")
                time.sleep(1)

    def set_daily_profit_target(self, target: float):
        self.daily_profit_target = target
        self.daily_target_reached = False
        logger.info(f"Daily profit target set to ${target:.2f}")

    def pause(self) -> None:
        self.paused = True
        logger.info(f"Trading paused for user {self.user_id}")

    def resume(self) -> None:
        self.paused = False
        logger.info(f"Trading resumed for user {self.user_id}")

    def _apply_order_cap(self) -> int:
        balance = self.live_balance if (self.broker.is_live and self.live_balance is not None) else self.balance
        for threshold, cap in ORDER_CAP_TIERS:
            if balance <= threshold:
                return cap
        return self.config.get("max_open_trades", MAX_OPEN_TRADES)

    def _sync_live_balance(self) -> None:
        if not self.broker.is_live:
            return
        fetched = self.broker.fetch_wallet_balance()
        if fetched is not None:
            # Detect external deposits/withdrawals
            if self.live_balance is not None and fetched != self.live_balance:
                # If we have no open trades, any change is likely an external move
                # In a more complex version, we would subtract the current session's PnL here.
                if not self.open_trades:
                    diff = fetched - self.live_balance
                    logger.info(f"💰 External wallet move detected: {diff:+.2f}. Adjusting baselines.")
                    self.initial_balance += diff
                    self.daily_start_balance += diff

            # If this is the first time we're syncing live balance and we have no history,
            # use this as our starting point for all metrics.
            if self.live_balance is None and not self.equity_curve:
                # Fix for fresh accounts: if initial is still default 100, align it
                if self.initial_balance == 100.0 and fetched != 100.0:
                    logger.info(f"✨ Initializing balance from live wallet: ${fetched:.2f}")
                    self.initial_balance = fetched
                    self.daily_start_balance = fetched
                self.balance = fetched
            
            self.live_balance = fetched
            # Always sync main balance with live wallet in Live mode
            self.balance = fetched

    def reconfigure(self, broker: BaseBroker) -> None:
        self.broker = broker
        self.dry_run = not broker.is_live
        self.live_balance = None
        
        # Flush current internal state
        self.open_trades.clear()
        self.closed_trades.clear()
        self.equity_curve.clear()
        self.balance = self.initial_balance
        self.daily_pnl = 0.0
        
        # Reload state from database for the newly selected mode
        self._load_state()
        
        if self.broker.is_live:
            self._sync_live_balance()
            
        # Ensure we have symbols for the new mode immediately
        self._refresh_top_coins()
            
        logger.info(f"Trader reconfigured to {'LIVE' if broker.is_live else 'DRY RUN'} mode for user {self.user_id}")

    def _refresh_config(self):
        """Fetch user-specific config from DB with retries for network stability"""
        if not self.user_id:
            return
            
        for attempt in range(3):
            try:
                # Map common internal keys to DB keys
                key_map = {
                    "leverage": "leverage",
                    "risk_per_trade": "risk_per_trade",
                    "atr_mult": "atr_mult",
                    "tp_rr_ratio": "tp_rr_ratio",
                    "top_n_coins": "top_n_coins",
                    "prop_daily_loss_pct": "prop_daily_loss_pct",
                    "telegram_token": "telegram_bot_token",
                    "telegram_chat_id": "telegram_chat_id"
                }
                for internal_key, db_key in key_map.items():
                    val = db.get_config(self.user_id, db_key, None)
                    if val is not None:
                        if internal_key in ["leverage"]:
                            self.config[internal_key] = int(val)
                        elif internal_key in ["risk_per_trade", "atr_mult", "tp_rr_ratio", "prop_daily_loss_pct"]:
                            self.config[internal_key] = float(val)
                        elif internal_key in ["top_n_coins"]:
                            self.config[internal_key] = int(val)
                        else:
                            self.config[internal_key] = str(val)
                
                # Special case for daily target
                target = db.get_config(self.user_id, "daily_profit_target", None)
                if target:
                    self.daily_profit_target = float(target)
                
                # Re-evaluate daily target reached status
                if self.daily_profit_target > 0 and self.daily_pnl >= self.daily_profit_target:
                    self.daily_target_reached = True
                
                return # Success
            except Exception as e:
                if "10035" in str(e) or "non-blocking" in str(e):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                logger.error(f"Failed to refresh config (attempt {attempt+1}): {e}")
                time.sleep(1)
        
    def get_status(self) -> dict:
        current_drawdown = (self.initial_balance - self.balance) / self.initial_balance * 100
        return {
            "balance": round(self.balance, 2),
            "live_balance": round(self.live_balance, 2) if self.live_balance is not None else None,
            "initial_balance": round(self.initial_balance, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "drawdown_pct": round(current_drawdown, 2),
            "open_count": len(self.open_trades),
            "closed_count": len(self.closed_trades),
            "max_trades": self._apply_order_cap(),
            "last_scan": self.last_scan_time,
            "next_scan": self.next_scan_time,
            "running": self.running,
            "paused": self.paused,
            "dry_run": self.dry_run,
            "is_live": self.broker.is_live,
            "testnet": getattr(self.broker, "testnet", False),
            "scan_count": self.scan_count,
            "leverage": self.config["leverage"],
            "risk_per_trade": self.config["risk_per_trade"],
            "tp_rr_ratio": self.config["tp_rr_ratio"],
            "atr_mult": self.config["atr_mult"],
            "prop_max_dd": PROP_MAX_DRAWDOWN_PCT,
            "prop_daily_loss": self.config.get("prop_daily_loss_pct", PROP_DAILY_LOSS_PCT),
            "daily_profit_target": round(self.daily_profit_target, 2),
            "daily_target_reached": self.daily_target_reached,
            "regime": self.current_regime.value,
            "personality": self.active_personality.name,
            "scan_limit": self.active_personality.scan_limit,
            "order_cap": self._apply_order_cap(),
        }

    def get_open_trades(self) -> list:
        result = []
        for sym, t in self.open_trades.items():
            direction = t["direction"]
            entry = t["entry_price"]
            live_price = self._live_prices.get(sym, entry)
            if direction == BUY:
                pnl_pct = (live_price - entry) / entry * 100
            else:
                pnl_pct = (entry - live_price) / entry * 100
            pnl_usd = self.balance * pnl_pct / 100 * RISK_PER_TRADE * LEVERAGE
            result.append({
                "symbol": sym,
                "direction": "LONG" if direction == BUY else "SHORT",
                "entry_price": round(entry, 6),
                "live_price": round(live_price, 6),
                "pnl_pct": round(pnl_pct, 2),
                "pnl_usd": round(pnl_usd, 2),
                "sl_price": round(t["sl_price"], 6),
                "tp_price": round(t["tp_price"], 6),
                "sl_dist_pct": round(t.get("sl_dist_pct", 0), 4),
                "qty": round(t["qty"], 6),
                "notional": round(entry * t["qty"], 2),
                "current_value": round(live_price * t["qty"], 2),
                "entry_time": t["entry_time"],
                "scan_count": t["scan_count"],
                "max_hold": MAX_HOLD_SCANS,
                "max_price": round(t.get("max_price", entry), 6),
                "min_price": round(t.get("min_price", entry), 6),
                "strategies": t.get("strategies", ""),
                "signal": t.get("signal", ""),
            })
        return result

    def manual_close_trade(self, symbol: str) -> dict:
        if symbol not in self.open_trades:
            return {"error": f"{symbol} not found in open trades"}
        try:
            ticker = self.broker.fetch_ticker(symbol)
            current_price = ticker["last"]
            self.close_trade(symbol, current_price, "MANUAL_EXIT")
            return {"success": True, "symbol": symbol, "exit_price": current_price}
        except Exception as e:
            logger.error(f"Manual close failed for {symbol}: {e}")
            return {"error": str(e)}

    def get_closed_trades(self) -> list:
        result = []
        for t in self.closed_trades:
            result.append({
                "symbol": t.get("symbol", ""),
                "direction": "LONG" if str(t.get("direction", "1")) == "1" else "SHORT",
                "entry_price": t.get("entry_price", ""),
                "exit_price": t.get("exit_price", ""),
                "sl_price": t.get("sl_price", ""),
                "tp_price": t.get("tp_price", ""),
                "pnl_pct": t.get("pnl_pct", ""),
                "pnl_usd": t.get("pnl_usd", ""),
                "notional": round(float(t.get("entry_price", 0)) * float(t.get("qty", 0)), 2),
                "exit_value": round(float(t.get("exit_price", 0)) * float(t.get("qty", 0)), 2),
                "reason": t.get("reason", ""),
                "strategies": t.get("strategies", ""),
                "entry_time": t.get("entry_time", ""),
                "exit_time": t.get("exit_time", ""),
            })
        return result

    def get_equity_curve(self) -> list:
        return self.equity_curve

    def _detect_regime(self):
        try:
            btc_df = self.fetch_ohlcv(REGIME_BTC_SYMBOL, f"{CANDLE_TF_MIN}m", 250)
            if btc_df.empty or len(btc_df) < 200:
                return
            btc_df = compute_indicators(btc_df)
            btc_htf = self.fetch_ohlcv(REGIME_BTC_SYMBOL, HTF_TIMEFRAME, limit=HTF_CANDLE_LIMIT)
            if not btc_htf.empty:
                btc_htf["ema_50"] = btc_htf["close"].ewm(span=HTF_EMA_FAST, adjust=False).mean()
                btc_htf["ema_200"] = btc_htf["close"].ewm(span=HTF_EMA_SLOW, adjust=False).mean()
            old_regime = self.current_regime
            self.current_regime = detect_regime(btc_df, htf_df=btc_htf, symbol="__MARKET__")
            self.active_personality = get_personality(self.current_regime)
            if old_regime != self.current_regime:
                logger.info(f"REGIME SHIFT: {old_regime.value} -> {self.current_regime.value} | Personality: {self.active_personality.name}")
        except Exception as e:
            logger.error(f"Regime detection failed: {e}")

    def _refresh_top_coins(self):
        self.last_symbol_refresh_time = time.time()
        
        # [SYNCED WITH BACKTEST] Use the Gold List
        from azalyst.config import GOLD_COINS
        scan_limit = self.active_personality.scan_limit
        self.current_scan_limit = scan_limit
        
        logger.info(f"Using Gold List for top {scan_limit} coins...")
        
        # We still check if the markets exist, just to be safe
        logger.info("Loading markets from Binance to verify Gold List symbols...")
        markets = self.broker.load_markets()
        
        verified_symbols = []
        for s in GOLD_COINS:
            # Handle different symbol formats if needed (e.g. BTC/USDT vs BTC/USDT:USDT)
            # We assume GOLD_COINS are properly formatted for the broker
            if s in markets and markets[s].get("active", True):
                verified_symbols.append(s)
                
        self.symbols = verified_symbols[:scan_limit]

        logger.info(f"Selected top {len(self.symbols)} Gold List symbols:")
        for s in self.symbols[:5]:
            logger.info(f"  - {s}")
        if len(self.symbols) > 5:
            logger.info(f"  ... and {len(self.symbols) - 5} more")

        if self.broker.is_live:
            logger.info("Setting leverage...")
            for symbol in self.symbols:
                self.broker.set_leverage(symbol, LEVERAGE)

        logger.info(f"Symbol refresh complete. Actively tracking {len(self.symbols)} symbols...")

    def initialize(self):
        logger.info("=" * 80)
        logger.info("AZALYST ALPHA X — MULTI STRATEGY LIVE TRADER")
        logger.info("=" * 80)
        logger.info(f"Mode: {'DRY RUN (Paper Trading)' if self.dry_run else 'LIVE TRADING'}")
        logger.info(f"Leverage: {LEVERAGE}x | Risk/Trade: {RISK_PER_TRADE * 100}%")
        logger.info(f"Max DD: {PROP_MAX_DRAWDOWN_PCT}% | Daily Loss: {PROP_DAILY_LOSS_PCT}%")
        logger.info(f"Max Open Trades: {MAX_OPEN_TRADES}")
        logger.info(f"Scan Interval: {SCAN_INTERVAL_MIN} min")
        logger.info(f"Candle TF: {CANDLE_TF_MIN} min")
        logger.info("=" * 80)

        self._refresh_top_coins()

        send_alerts(
            "🚀 <b>TRADER STARTED</b>",
            f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}\n"
            f"Symbols: {len(self.symbols)}\n"
            f"Leverage: {LEVERAGE}x\n"
            f"Balance: ${self.balance:.2f}"
        )

    def fetch_ohlcv(self, symbol: str, tf: str = "15m", limit: int = 250) -> pd.DataFrame:
        for attempt in range(3):
            try:
                ohlcv = self.broker.fetch_ohlcv(symbol, tf, limit)
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df.set_index("timestamp", inplace=True)
                return df
            except Exception as e:
                logger.warn(f"Failed to fetch {symbol} (attempt {attempt + 1}): {e}")
                time.sleep(2 ** attempt)
        return pd.DataFrame()

    def check_prop_firm_limits(self) -> bool:
        drawdown = (self.initial_balance - self.balance) / self.initial_balance * 100
        
        # --- Fresh Start Safety Check ---
        if self.broker.is_live and drawdown >= 50.0 and not self.open_trades and not self.closed_trades:
            logger.info(f"🔄 Fresh Live Start detected. Resetting starting balance to match wallet: ${self.balance:.2f}")
            self.initial_balance = self.balance
            
        # Daily Loss Check (Kept as per request)
        if self.daily_pnl <= -self.config.get("prop_daily_loss_pct", PROP_DAILY_LOSS_PCT) * self.daily_start_balance / 100:
            logger.warn(f"⚠️ DAILY LOSS LIMIT ALERT: ${self.daily_pnl:.2f}")
            logger.info("Prop Firm Safety is DISABLED. Continuing trade scan...")

        return True

    def scan_and_trade(self):
        if self.paused:
            logger.info("Trading is paused. Skipping scan.")
            return

        if not self.check_prop_firm_limits():
            return

        if self.daily_profit_target > 0 and self.daily_pnl >= self.daily_profit_target:
            if not self.daily_target_reached:
                self.daily_target_reached = True
                logger.info(f"🎯 DAILY PROFIT TARGET REACHED: ${self.daily_pnl:.2f} >= ${self.daily_profit_target:.2f}")
                send_alerts(
                    "🎯 <b>DAILY TARGET REACHED</b>",
                    f"Profit: ${self.daily_pnl:.2f} / Target: ${self.daily_profit_target:.2f}\n"
                    f"Bot will stop taking new trades until tomorrow."
                )
            return

        effective_cap = min(self._apply_order_cap(), self.active_personality.max_open_trades)
        if len(self.open_trades) >= effective_cap:
            logger.info(f"Order cap reached ({len(self.open_trades)}/{effective_cap}). Skipping scan.")
            return

        p = self.active_personality
        logger.info(f"[{self.current_regime.value}|{p.name}] Scanning {len(self.symbols)} symbols... ({len(self.open_trades)}/{p.max_open_trades} open)")

        for symbol in self.symbols:
            if symbol in self.open_trades:
                continue

            # --- Correlation & Exposure Guard Pre-Check ---
            open_list = list(self.open_trades.values())
            longs = [t for t in open_list if t["direction"] == BUY]
            shorts = [t for t in open_list if t["direction"] == SELL]
            
            df = self.fetch_ohlcv(symbol, f"{CANDLE_TF_MIN}m", 250)
            if df.empty or len(df) < 200:
                continue

            df = compute_indicators(df)
            if df["atr_14"].iloc[-1] == 0 or np.isnan(df["atr_14"].iloc[-1]):
                continue

            htf_df = self.fetch_ohlcv(symbol, HTF_TIMEFRAME, limit=HTF_CANDLE_LIMIT)
            if not htf_df.empty:
                htf_df["ema_50"] = htf_df["close"].ewm(span=HTF_EMA_FAST, adjust=False).mean()
                htf_df["ema_200"] = htf_df["close"].ewm(span=HTF_EMA_SLOW, adjust=False).mean()

            sig = multi_strategy_scan(df, htf_df=htf_df, personality=self.active_personality)
            if sig is None:
                continue

            # --- Post-Signal Exposure Enforcement ---
            direction = sig["direction"]
            strategies = sig.get("strategies", [])
            
            if direction == BUY and len(longs) >= p.max_same_direction:
                logger.info(f"   [SKIP] {symbol} LONG cap reached ({p.max_same_direction})")
                continue
            if direction == SELL and len(shorts) >= p.max_same_direction:
                logger.info(f"   [SKIP] {symbol} SHORT cap reached ({p.max_same_direction})")
                continue

            # 2. Strategy Exposure Limit (Alpha-X)
            if "alpha_x" in strategies:
                alpha_x_count = len([t for t in open_list if "alpha_x" in t.get("strategies", "")])
                if alpha_x_count >= 7:
                    logger.info(f"   [SKIP] {symbol} Max Alpha-X exposure reached (7)")
                    continue

            self.execute_trade(symbol, df, sig)
            time.sleep(0.5)

    def execute_trade(self, symbol: str, df: pd.DataFrame, sig: dict):
        last = df.iloc[-1]
        direction = sig["direction"]
        atr = sig["atr"]
        fill_price = last["close"]
        p = self.active_personality

        raw_sl_dist = atr * p.atr_mult
        
        min_sl_dist = fill_price * p.sl_min_pct
        max_sl_dist = fill_price * p.sl_max_pct
        sl_dist = max(min_sl_dist, min(raw_sl_dist, max_sl_dist))

        sl_price = fill_price - sl_dist if direction == BUY else fill_price + sl_dist

        tp_price = sig.get("tp_price")
        if tp_price is None or np.isnan(tp_price):
            tp_dist = sl_dist * p.tp_rr_ratio
            tp_price = fill_price + tp_dist if direction == BUY else fill_price - tp_dist

        sl_price = float(sl_price) if not np.isnan(sl_price) else fill_price * 0.95
        tp_price = float(tp_price) if not np.isnan(tp_price) else fill_price * 1.05

        effective_risk = self.config["risk_per_trade"] * p.risk_multiplier
        risk_usd = self.balance * effective_risk
        
        ideal_qty = risk_usd / sl_dist if sl_dist > 0 else 0
        max_qty = (self.balance * p.leverage) / fill_price
        qty = min(ideal_qty, max_qty)

        tp1 = tp_price
        tp2 = None

        max_sl_dist = fill_price * p.sl_max_pct
        if direction == BUY:
            min_allowed_sl = fill_price - max_sl_dist
            if sl_price < min_allowed_sl or np.isnan(sl_price):
                sl_price = min_allowed_sl
            tp_price = float(tp_price) if not np.isnan(tp_price) else fill_price * 1.10
            tp1 = float(tp1) if not (tp1 is None or np.isnan(tp1)) else fill_price * 1.05
            tp2 = float(tp2) if not (tp2 is None or np.isnan(tp2)) else fill_price * 1.08
        else:
            max_allowed_sl = fill_price + max_sl_dist
            if sl_price > max_allowed_sl or np.isnan(sl_price):
                sl_price = max_allowed_sl
            tp_price = float(tp_price) if not np.isnan(tp_price) else fill_price * 0.90
            tp1 = float(tp1) if not (tp1 is None or np.isnan(tp1)) else fill_price * 0.95
            tp2 = float(tp2) if not (tp2 is None or np.isnan(tp2)) else fill_price * 0.92

        sl_dist_pct = abs(fill_price - sl_price) / fill_price * 100

        trade = {
            "user_id": self.user_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": fill_price,
            "qty": qty,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "tp1": tp1,
            "tp2": tp2,
            "sl_dist_pct": round(sl_dist_pct, 4),
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "scan_count": 0,
            "max_price": fill_price,
            "min_price": fill_price,
            "signal": sig["signal"],
            "strategies": ", ".join(sig.get("strategies", [])),
            "atr": atr,
            "is_alpha": is_alpha,
            "extended": False,
        }

        if self.broker.is_live:
            try:
                side = "buy" if direction == BUY else "sell"
                
                # Dynamically set leverage based on Personality before executing
                logger.info(f"Setting {symbol} leverage to {p.leverage}x for {p.name}")
                self.broker.set_leverage(symbol, p.leverage)
                
                # 1. Place Entry
                self.broker.place_market_order(symbol, side, qty)
                
                # 2. Place Real TP/SL on Exchange (Commented out per user request)
                # exit_side = "sell" if side == "buy" else "buy"
                # self.broker.place_sl_tp(symbol, exit_side, qty, sl_price, tp_price)

                logger.trade(f"OPENED: {symbol} {'LONG' if direction == BUY else 'SHORT'} @ ${fill_price:.4f} | "
                             f"SL: ${sl_price:.4f} | TP: ${tp_price:.4f} | Qty: {qty:.4f}")
            except Exception as e:
                logger.error(f"Failed to execute {symbol}: {e}")
                return
        else:
            logger.trade(f"DRY RUN OPEN: {symbol} {'LONG' if direction == BUY else 'SHORT'} @ ${fill_price:.4f} | "
                         f"SL: ${sl_price:.4f} | TP: ${tp_price:.4f} | Qty: {qty:.4f}")

        self.open_trades[symbol] = trade
        self._save_trade(trade, "open")

        # Format strategies safely for notification
        strat_list = sig.get("strategies", [])
        strat_str = ", ".join(strat_list) if isinstance(strat_list, list) else str(strat_list)
        
        # Format prices to avoid 'nan' in Telegram
        tp_display = f"${tp_price:.4f}"
        sl_display = f"${sl_price:.4f}"

        try:
            send_alerts(
                f"🔔 <b>NEW TRADE</b>",
                f"<b>{symbol}</b> {'LONG' if direction == BUY else 'SHORT'}\n"
                f"Entry: ${fill_price:.4f}\n"
                f"SL: {sl_display} | TP: {tp_display}\n"
                f"Signal: {sig.get('signal', 'Manual')}\n"
                f"Strategies: {strat_str}",
                telegram_token=self.config.get("telegram_token"),
                telegram_chat_id=self.config.get("telegram_chat_id")
            )
        except Exception as alert_err:
            logger.error(f"Failed to send Buy alert: {alert_err}")

    def manage_open_trades(self, main_scan: bool = True):
        symbols_to_check = list(self.open_trades.keys())

        for symbol in symbols_to_check:
            if symbol not in self.open_trades:
                continue

            trade = self.open_trades[symbol]
            if main_scan:
                trade["scan_count"] += 1

            try:
                ticker = self.broker.fetch_ticker(symbol)
                current_price = ticker["last"]
                self._live_prices[symbol] = current_price
            except Exception as e:
                logger.error(f"Failed to fetch ticker for {symbol}: {e}")
                continue

            trade["max_price"] = max(trade.get("max_price", current_price), current_price)
            trade["min_price"] = min(trade.get("min_price", current_price), current_price)

            direction = trade["direction"]
            sl = trade["sl_price"]
            tp = trade["tp_price"]
            entry = trade["entry_price"]

            p = self.active_personality
            if p.trailing_enabled:
                pnl_move = (current_price - entry) / entry
                if direction == BUY:
                    if pnl_move >= p.trail_trigger_pct:
                        new_sl = trade["max_price"] * (1 - p.trail_distance_pct)
                        if new_sl > trade["sl_price"]:
                            trade["sl_price"] = new_sl
                            logger.info(f"   [TRAIL] {symbol} SL followed up to ${new_sl:.4f}")
                else:
                    if pnl_move <= -p.trail_trigger_pct:
                        new_sl = trade["min_price"] * (1 + p.trail_distance_pct)
                        if new_sl < trade["sl_price"]:
                            trade["sl_price"] = new_sl
                            logger.info(f"   [TRAIL] {symbol} SL followed down to ${new_sl:.4f}")

            closed = False
            exit_price = None
            reason = ""

            # --- Alpha-X STATEFUL EXIT LOGIC (High Priority) ---
            if trade.get("is_alpha"):
                # Fetch latest candle for band levels (Parity with Main.py)
                df_curr = self.fetch_ohlcv(symbol, f"{CANDLE_TF_MIN}m", 10)
                if not df_curr.empty:
                    df_curr = compute_indicators(df_curr)
                    last_candle = df_curr.iloc[-1]
                    
                    upper = last_candle["bb200_upper"]
                    lower = last_candle["bb200_lower"]
                    tol = upper * 0.0025 # TOUCH_TOL
                    
                    # 1. Update Extensions (Must CLOSE beyond the band to lock-in)
                    is_extended = "|EXTENDED" in trade.get("signal", "")
                    if not is_extended:
                        if (direction == BUY and last_candle["close"] > upper) or \
                           (direction == SELL and last_candle["close"] < lower):
                            is_extended = True
                            trade["signal"] += "|EXTENDED"
                            logger.info(f"   [EXTEND] {symbol} locked-in beyond the band. Awaiting harvest.")
                            self._save_trade(trade, "open")

                    # 2. Check for Band-Touch Harvest (Anti-Flush Patch)
                    if is_extended and trade["scan_count"] > 0:
                        is_profitable = False
                        if direction == BUY and current_price > entry:
                            is_profitable = True
                        elif direction == SELL and current_price < entry:
                            is_profitable = True

                        if is_profitable:
                            if direction == BUY:
                                # Low wicks to band AND High is at/above band level
                                if last_candle["low"] <= upper + tol and last_candle["high"] >= upper - tol:
                                    exit_price = current_price
                                    reason = "Alpha-X Profit Harvest 🏦"
                                    closed = True
                            else:
                                # High wicks to band AND Low is at/below band level
                                if last_candle["high"] >= lower - tol and last_candle["low"] <= lower + tol:
                                    exit_price = current_price
                                    reason = "Alpha-X Profit Harvest 🏦"
                                    closed = True

            # Standard exit checks (Fallback / Fib Targets)
            if not closed:
                tp1 = trade.get("tp1")
                tp2 = trade.get("tp2")
                
                if direction == BUY:
                    if current_price <= sl:
                        exit_price = sl
                        reason = "STOP_LOSS"
                        closed = True
                    elif tp2 and current_price >= tp2:
                        exit_price = current_price
                        reason = "TAKE_PROFIT_FIB2 ✅"
                        closed = True
                    elif tp1 and current_price >= tp1:
                        exit_price = current_price
                        reason = "TAKE_PROFIT_FIB1 ✅"
                        closed = True
                else:
                    if current_price >= sl:
                        exit_price = sl
                        reason = "STOP_LOSS"
                        closed = True
                    elif tp2 and current_price <= tp2:
                        exit_price = current_price
                        reason = "TAKE_PROFIT_FIB2 ✅"
                        closed = True
                    elif tp1 and current_price <= tp1:
                        exit_price = current_price
                        reason = "TAKE_PROFIT_FIB1 ✅"
                        closed = True

            if not closed:
                pnl_pct = (current_price - entry) / entry * 100 if direction == BUY else (entry - current_price) / entry * 100

                try:
                    current_atr = trade.get("atr", current_price * 0.01)
                except:
                    current_atr = current_price * 0.01

                sl_dist_pct = trade.get("sl_dist_pct", 2.0)
                # Ensure trailing doesn't trigger prematurely for tight SLs, causing immediate breakeven exits
                trail_trigger_pct = max(sl_dist_pct, 1.5)

                if pnl_pct >= trail_trigger_pct:
                    trail_dist = current_price * 0.01
                    if direction == BUY:
                        new_sl = current_price - trail_dist
                        new_sl = max(new_sl, entry)
                        if new_sl > trade["sl_price"]:
                            old_sl = trade["sl_price"]
                            trade["sl_price"] = new_sl
                            logger.info(f"📈 Trailing SL moved for {symbol}: ${old_sl:.4f} -> ${new_sl:.4f}")
                            if self.broker.is_live:
                                self.broker.cancel_symbol_orders(symbol)
                                self.broker.place_sl_tp(symbol, "sell", trade["qty"], trade["sl_price"], trade["tp_price"])
                            self._save_trade(trade, "open")
                    else:
                        new_sl = current_price + trail_dist
                        new_sl = min(new_sl, entry)
                        if new_sl < trade["sl_price"]:
                            old_sl = trade["sl_price"]
                            trade["sl_price"] = new_sl
                            logger.info(f"📈 Trailing SL moved for {symbol}: ${old_sl:.4f} -> ${new_sl:.4f}")
                            if self.broker.is_live:
                                self.broker.cancel_symbol_orders(symbol)
                                self.broker.place_sl_tp(symbol, "buy", trade["qty"], trade["sl_price"], trade["tp_price"])
                            self._save_trade(trade, "open")

            if not closed and trade["scan_count"] >= MAX_HOLD_SCANS:
                exit_price = current_price
                reason = "MAX_HOLD_TIME"
                closed = True

            if closed:
                if reason == "STOP_LOSS":
                    if exit_price == entry:
                        reason = "BREAKEVEN"
                    elif (direction == BUY and exit_price > entry) or (direction == SELL and exit_price < entry):
                        reason = "TRAILING_STOP"
                self.close_trade(symbol, exit_price, reason)

    def close_trade(self, symbol: str, exit_price: float, reason: str):
        if symbol not in self.open_trades:
            return

        trade = self.open_trades[symbol]
        entry = trade["entry_price"]
        direction = trade["direction"]
        qty = trade["qty"]

        if direction == BUY:
            pnl_pct = (exit_price - entry) / entry * 100
        else:
            pnl_pct = (entry - exit_price) / entry * 100

        pnl_usd = self.balance * pnl_pct / 100 * RISK_PER_TRADE * LEVERAGE
        self.balance += pnl_usd
        self.daily_pnl += pnl_usd

        trade["exit_price"] = exit_price
        trade["exit_time"] = datetime.now(timezone.utc).isoformat()
        trade["pnl_pct"] = pnl_pct
        trade["pnl_usd"] = pnl_usd
        trade["reason"] = reason

        if self.broker.is_live:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.broker.cancel_symbol_orders(symbol)
                    side = "sell" if direction == BUY else "buy"
                    
                    # 1. Place the close order
                    self.broker.place_market_order(symbol, side, qty)
                    
                    # 2. VERIFY position is actually 0
                    time.sleep(1) # Wait for Binance to process
                    pos = self.broker.fetch_position(symbol)
                    actual_qty = abs(float(pos.get("contracts", 0) or pos.get("size", 0))) if pos else 0
                    
                    if actual_qty < 0.000001: # Essentially zero
                        logger.info(f"✅ Successfully closed {symbol} on exchange (Verified 0 size).")
                        break
                    else:
                        logger.warning(f"⚠️ {symbol} position still open on Binance ({actual_qty} remaining). Retrying...")
                        qty = actual_qty # Update qty to close the remaining bits
                        
                except Exception as e:
                    logger.error(f"⚠️ Attempt {attempt+1}/{max_retries} failed to close {symbol}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        logger.error(f"❌ CRITICAL: Failed to close {symbol} after {max_retries} attempts. Manual intervention required!")
                        from azalyst.notifications import send_alerts
                        send_alerts(
                            "🚨 <b>CRITICAL: CLOSE FAILED</b>",
                            f"<b>{symbol}</b> could not be closed after {max_retries} retries!\n"
                            "Manual intervention on Binance is required immediately.",
                            telegram_token=self.config.get("telegram_token"),
                            telegram_chat_id=self.config.get("telegram_chat_id")
                        )

        emoji = "✅" if pnl_usd >= 0 else "❌"
        logger.trade(f"{emoji} CLOSED: {symbol} | PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f}) | Reason: {reason}")

        self._save_trade(trade, "closed")
        self.closed_trades.append(trade)
        del self.open_trades[symbol]

        send_alerts(
            f"{emoji} <b>TRADE CLOSED</b>",
            f"<b>{symbol}</b>\n"
            f"PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
            f"Reason: {reason}",
            telegram_token=self.config.get("telegram_token"),
            telegram_chat_id=self.config.get("telegram_chat_id")
        )

    def reset_daily_pnl(self):
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute < SCAN_INTERVAL_MIN:
            self.manual_reset_daily_stats()

    def manual_reset_daily_stats(self):
        self.daily_pnl = 0.0
        self.daily_start_balance = self.balance
        self.daily_target_reached = False
        logger.info(f"Manual Daily Reset performed. New starting balance: ${self.balance:.2f}")

    def manual_reset_all_history(self):
        """Wipes all trade history and equity logs for a total clean start"""
        if not self.user_id:
            return
            
        from azalyst import db
        mode = "live" if self.broker.is_live else "dry_run"
        
        # 1. Clear trades from DB
        db.get_client().table("trades").delete().eq("user_id", self.user_id).eq("mode", mode).execute()
        
        # 2. Clear equity logs from DB
        db.get_client().table("equity_log").delete().eq("user_id", self.user_id).eq("mode", mode).execute()
        
        # 3. Clear local state
        self.closed_trades.clear()
        self.equity_curve.clear()
        self.daily_pnl = 0.0
        
        # 4. Sync balance to reset starting point
        if self.broker.is_live:
            self._sync_live_balance()
            self.initial_balance = self.balance
            self.daily_start_balance = self.balance
        else:
            self.initial_balance = 100.0 # Reset to default for dry run
            self.balance = 100.0
            self.daily_start_balance = 100.0
            
        logger.info(f"🔥 TOTAL HISTORY RESET for user {self.user_id} ({mode} mode). Starting fresh.")

    def print_status(self):
        logger.info(f"Balance: ${self.balance:.2f} | Open: {len(self.open_trades)} | "
                     f"Closed: {len(self.closed_trades)} | Daily PnL: ${self.daily_pnl:+.2f}")

        if self.open_trades:
            for sym, t in self.open_trades.items():
                pnl = (t.get("max_price", t["entry_price"]) - t["entry_price"]) / t["entry_price"] * 100 \
                      if t["direction"] == BUY else \
                      (t["entry_price"] - t.get("min_price", t["entry_price"])) / t["entry_price"] * 100
                logger.info(f"  {sym}: {'LONG' if t['direction'] == BUY else 'SHORT'} | "
                            f"PnL: {pnl:+.2f}% | Scans: {t['scan_count']}/{MAX_HOLD_SCANS}")

    def print_final_report(self):
        logger.info("\n" + "=" * 80)
        logger.info("FINAL TRADING REPORT")
        logger.info("=" * 80)

        total_pnl = self.balance - self.initial_balance
        total_pnl_pct = total_pnl / self.initial_balance * 100

        wins = [t for t in self.closed_trades if float(t.get("pnl_usd", 0)) > 0]
        losses = [t for t in self.closed_trades if float(t.get("pnl_usd", 0)) <= 0]

        logger.info(f"Initial Balance: ${self.initial_balance:.2f}")
        logger.info(f"Final Balance:   ${self.balance:.2f}")
        logger.info(f"Total PnL:       ${total_pnl:+.2f} ({total_pnl_pct:+.2f}%)")
        logger.info(f"Total Trades:    {len(self.closed_trades)}")
        logger.info(f"Winning:         {len(wins)}")
        logger.info(f"Losing:          {len(losses)}")
        if self.closed_trades:
            win_rate = len(wins) / len(self.closed_trades) * 100
            logger.info(f"Win Rate:        {win_rate:.1f}%")

        logger.info(f"Open Trades:     {len(self.open_trades)}")
        logger.info("=" * 80)

    def run(self):
        try:
            self._load_state()
            self._refresh_config()

            logger.info("\nStarting live trading loop...")
            logger.info("Press Ctrl+C to stop\n")

            while self.running:
                try:
                    self._refresh_config()
                    self._detect_regime()
                    self._sync_live_balance()

                    if time.time() - self.last_symbol_refresh_time >= 4 * 3600:
                        self._refresh_top_coins()

                    self.scan_count += 1
                    self.last_scan_time = datetime.now(timezone.utc).isoformat()
                    self.next_scan_time = (datetime.now(timezone.utc) + __import__("datetime").timedelta(minutes=SCAN_INTERVAL_MIN)).isoformat()

                    self.reset_daily_pnl()
                    self.scan_and_trade()
                    self.manage_open_trades(main_scan=True)
                    self._log_equity()
                    self.print_status()

                    logger.info(f"Next scan in {SCAN_INTERVAL_MIN} minutes...")
                    loops = (SCAN_INTERVAL_MIN * 60)
                    for i in range(loops):
                        if not self.running:
                            break
                        try:
                            # Sync balance every 1 minute
                            if i % 60 == 0:
                                self._sync_live_balance()
                            
                            # Manage prices every 1s
                            self.manage_open_trades(main_scan=False)
                        except Exception as e:
                            logger.error(f"Error managing trades: {e}")
                        time.sleep(1)

                except Exception as e:
                    logger.error(f"Scan error: {e}\n{traceback.format_exc()}")
                    time.sleep(60)

            logger.info("Trading loop stopped. Closing all open trades...")

            for symbol in list(self.open_trades.keys()):
                try:
                    ticker = self.broker.fetch_ticker(symbol)
                    self.close_trade(symbol, ticker["last"], "MANUAL_STOP")
                except Exception as e:
                    logger.error(f"Failed to close {symbol}: {e}")

            logger.info("All trades closed. Saving final state...")
            self.print_final_report()

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        finally:
            logger.info("Live trader shutdown complete")
