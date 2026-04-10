from __future__ import annotations

import csv
import signal
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, List

import ccxt
import numpy as np
import pandas as pd

from azalyst.config import (
    INITIAL_BALANCE, LEVERAGE, RISK_PER_TRADE, ATR_MULT, TP_RR_RATIO,
    SL_MIN_PCT, SL_MAX_PCT, MAX_OPEN_TRADES, MAX_HOLD_SCANS,
    BREAKEVEN_AFTER_SCANS, SCAN_INTERVAL_MIN, CANDLE_TF_MIN,
    PROP_MAX_DRAWDOWN_PCT, PROP_DAILY_LOSS_PCT, SLIPPAGE_BPS,
    BUY, SELL, EXCLUDE_SYMBOLS, MIN_VOLUME_MA, TOP_N_COINS,
    LIVE_TRADES_CSV, EQUITY_LOG_CSV,
)
from azalyst.logger import logger
from azalyst.indicators import compute_indicators
from azalyst.consensus import multi_strategy_scan
from azalyst.notifications import send_alerts


class LiveTrader:
    def __init__(self, exchange: ccxt.binance, dry_run: bool = False):
        self.exchange = exchange
        self.dry_run = dry_run
        self.balance = INITIAL_BALANCE
        self.initial_balance = INITIAL_BALANCE
        self.open_trades: Dict[str, dict] = {}
        self.closed_trades: List[dict] = []
        self.daily_pnl = 0.0
        self.daily_start_balance = INITIAL_BALANCE
        self.scan_count = 0
        self.running = True
        self.symbols: List[str] = []
        self.last_scan_time = None
        self.next_scan_time = None
        self.equity_curve: List[dict] = []

        self._load_state()

        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    def _shutdown_handler(self, signum, frame):
        logger.info(f"Received shutdown signal. Closing {len(self.open_trades)} open trades...")
        self.running = False

    def _load_state(self):
        if LIVE_TRADES_CSV.exists():
            try:
                with open(LIVE_TRADES_CSV, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["status"] == "open":
                            symbol = row["symbol"]
                            self.open_trades[symbol] = {
                                "symbol": symbol,
                                "direction": int(row["direction"]),
                                "entry_price": float(row["entry_price"]),
                                "qty": float(row["qty"]),
                                "sl_price": float(row["sl_price"]),
                                "tp_price": float(row["tp_price"]),
                                "entry_time": row["entry_time"],
                                "scan_count": int(row.get("scan_count", 0)),
                                "max_price": float(row.get("max_price", 0)),
                                "min_price": float(row.get("min_price", 0)),
                            }
                        else:
                            self.closed_trades.append(row)
                logger.info(f"Loaded {len(self.open_trades)} open trades from {LIVE_TRADES_CSV}")
            except Exception as e:
                logger.error(f"Failed to load state: {e}")

    def _save_trade(self, trade: dict, status: str = "open"):
        file_exists = LIVE_TRADES_CSV.exists()
        fieldnames = [
            "symbol", "direction", "entry_price", "qty", "sl_price", "tp_price",
            "entry_time", "exit_time", "exit_price", "pnl_pct", "pnl_usd",
            "status", "scan_count", "max_price", "min_price", "reason",
        ]

        with open(LIVE_TRADES_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()

            row = {**trade}
            if status == "open":
                row["exit_time"] = ""
                row["exit_price"] = ""
                row["pnl_pct"] = ""
                row["pnl_usd"] = ""
                row["reason"] = ""
            row["status"] = status

            writer.writerow(row)

    def _log_equity(self):
        point = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "balance": self.balance,
            "open_trades": len(self.open_trades),
            "daily_pnl": self.daily_pnl,
        }
        self.equity_curve.append(point)

        file_exists = EQUITY_LOG_CSV.exists()
        with open(EQUITY_LOG_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "balance", "open_trades", "daily_pnl"])
            if not file_exists:
                writer.writeheader()
            writer.writerow(point)

    def get_status(self) -> dict:
        current_drawdown = (self.initial_balance - self.balance) / self.initial_balance * 100
        return {
            "balance": round(self.balance, 2),
            "initial_balance": round(self.initial_balance, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "drawdown_pct": round(current_drawdown, 2),
            "open_count": len(self.open_trades),
            "closed_count": len(self.closed_trades),
            "max_trades": MAX_OPEN_TRADES,
            "last_scan": self.last_scan_time,
            "next_scan": self.next_scan_time,
            "running": self.running,
            "dry_run": self.dry_run,
            "scan_count": self.scan_count,
            "leverage": LEVERAGE,
            "risk_per_trade": RISK_PER_TRADE,
            "prop_max_dd": PROP_MAX_DRAWDOWN_PCT,
            "prop_daily_loss": PROP_DAILY_LOSS_PCT,
        }

    def get_open_trades(self) -> list:
        result = []
        for sym, t in self.open_trades.items():
            direction = t["direction"]
            entry = t["entry_price"]
            result.append({
                "symbol": sym,
                "direction": "LONG" if direction == BUY else "SHORT",
                "entry_price": round(entry, 6),
                "sl_price": round(t["sl_price"], 6),
                "tp_price": round(t["tp_price"], 6),
                "qty": round(t["qty"], 6),
                "entry_time": t["entry_time"],
                "scan_count": t["scan_count"],
                "max_hold": MAX_HOLD_SCANS,
                "max_price": round(t.get("max_price", entry), 6),
                "min_price": round(t.get("min_price", entry), 6),
                "strategies": t.get("strategies", ""),
                "signal": t.get("signal", ""),
            })
        return result

    def get_closed_trades(self) -> list:
        result = []
        for t in self.closed_trades:
            result.append({
                "symbol": t.get("symbol", ""),
                "direction": "LONG" if str(t.get("direction", "1")) == "1" else "SHORT",
                "entry_price": t.get("entry_price", ""),
                "exit_price": t.get("exit_price", ""),
                "pnl_pct": t.get("pnl_pct", ""),
                "pnl_usd": t.get("pnl_usd", ""),
                "reason": t.get("reason", ""),
                "entry_time": t.get("entry_time", ""),
                "exit_time": t.get("exit_time", ""),
            })
        return result

    def get_equity_curve(self) -> list:
        return self.equity_curve

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

        logger.info("Loading markets from Binance...")
        markets = self.exchange.load_markets()

        usdt_symbols = [
            s for s, m in markets.items()
            if (s.endswith("/USDT") or s.endswith("/USDT:USDT")) and m.get("active", True)
        ]

        filtered = []
        for s in usdt_symbols:
            base = s.split("/")[0]
            full_name = s.replace("/USDT", "").replace(":", "")
            if full_name not in EXCLUDE_SYMBOLS and base not in EXCLUDE_SYMBOLS:
                filtered.append(s)

        logger.info(f"Found {len(filtered)} active USDT pairs. Fetching volume data...")
        
        # Fetch all tickers first, then filter, to avoid hitting dead/delisted symbols individually
        all_tickers = self.exchange.fetch_tickers()

        volume_ranked = []
        for symbol in filtered:
            if symbol in all_tickers:
                ticker = all_tickers[symbol]
                vol_usdt = ticker.get("quoteVolume", 0) or 0
                if vol_usdt > MIN_VOLUME_MA:
                    volume_ranked.append((symbol, vol_usdt))

        volume_ranked.sort(key=lambda x: x[1], reverse=True)
        self.symbols = [s for s, _ in volume_ranked[:TOP_N_COINS]]

        logger.info(f"Selected top {len(self.symbols)} symbols:")
        for s in self.symbols[:5]:
            logger.info(f"  - {s}")
        if len(self.symbols) > 5:
            logger.info(f"  ... and {len(self.symbols) - 5} more")

        if not self.dry_run:
            logger.info("Setting leverage...")
            for symbol in self.symbols:
                try:
                    self.exchange.set_leverage(LEVERAGE, symbol)
                except Exception as e:
                    logger.warn(f"Failed to set leverage for {symbol}: {e}")

        logger.info(f"Initialization complete. Scanning {len(self.symbols)} symbols...")

        send_alerts(
            "🚀 **TRADER STARTED**",
            f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}\n"
            f"Symbols: {len(self.symbols)}\n"
            f"Leverage: {LEVERAGE}x\n"
            f"Balance: ${self.balance:.2f}"
        )

    def fetch_ohlcv(self, symbol: str, tf: str = "15m", limit: int = 250) -> pd.DataFrame:
        for attempt in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, tf, limit=limit)
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df.set_index("timestamp", inplace=True)
                return df
            except Exception as e:
                logger.warn(f"Failed to fetch {symbol} (attempt {attempt + 1}): {e}")
                time.sleep(2 ** attempt)
        return pd.DataFrame()

    def check_prop_firm_limits(self) -> bool:
        current_drawdown = (self.initial_balance - self.balance) / self.initial_balance * 100
        if current_drawdown >= PROP_MAX_DRAWDOWN_PCT:
            logger.warn(f"MAX DRAWDOWN HIT: {current_drawdown:.1f}% >= {PROP_MAX_DRAWDOWN_PCT}%")
            logger.warn("Stopping all trading until manual review")
            return False

        if self.daily_pnl <= -PROP_DAILY_LOSS_PCT * self.daily_start_balance / 100:
            logger.warn(f"DAILY LOSS LIMIT HIT: ${self.daily_pnl:.2f}")
            logger.warn("Stopping trading for today")
            return False

        return True

    def scan_and_trade(self):
        if not self.check_prop_firm_limits():
            return

        if len(self.open_trades) >= MAX_OPEN_TRADES:
            logger.info(f"Max trades reached ({len(self.open_trades)}). Skipping scan.")
            return

        logger.info(f"Scanning {len(self.symbols)} symbols... ({len(self.open_trades)}/{MAX_OPEN_TRADES} open)")

        for symbol in self.symbols:
            if symbol in self.open_trades:
                continue

            df = self.fetch_ohlcv(symbol, f"{CANDLE_TF_MIN}m", 250)
            if df.empty or len(df) < 200:
                continue

            df = compute_indicators(df)
            if df["atr_14"].iloc[-1] == 0 or np.isnan(df["atr_14"].iloc[-1]):
                continue

            sig = multi_strategy_scan(df)
            if sig is None:
                continue

            self.execute_trade(symbol, df, sig)
            time.sleep(0.5)

    def execute_trade(self, symbol: str, df: pd.DataFrame, sig: dict):
        last = df.iloc[-1]
        direction = sig["direction"]
        atr = sig["atr"]
        price = last["close"]

        slippage_pct = SLIPPAGE_BPS / 10000
        if direction == BUY:
            fill_price = price * (1 + slippage_pct)
        else:
            fill_price = price * (1 - slippage_pct)

        risk_usd = self.balance * RISK_PER_TRADE * LEVERAGE
        qty = risk_usd / fill_price

        sl_dist = max(min(ATR_MULT * atr, fill_price * SL_MAX_PCT), fill_price * SL_MIN_PCT)
        if direction == BUY:
            sl_price = fill_price - sl_dist
            tp_price = fill_price + sl_dist * TP_RR_RATIO
        else:
            sl_price = fill_price + sl_dist
            tp_price = fill_price - sl_dist * TP_RR_RATIO

        trade = {
            "symbol": symbol,
            "direction": direction,
            "entry_price": fill_price,
            "qty": qty,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "entry_time": datetime.now(timezone.utc).isoformat(),
            "scan_count": 0,
            "max_price": fill_price,
            "min_price": fill_price,
            "signal": sig["signal"],
            "strategies": ", ".join(sig.get("strategies", [])),
        }

        if not self.dry_run:
            try:
                if direction == BUY:
                    self.exchange.create_market_order(symbol, "buy", qty)
                else:
                    self.exchange.create_market_order(symbol, "sell", qty)

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

        send_alerts(
            f"🔔 **NEW TRADE**",
            f"**{symbol}** {'LONG' if direction == BUY else 'SHORT'}\n"
            f"Entry: ${fill_price:.4f}\n"
            f"SL: ${sl_price:.4f} | TP: ${tp_price:.4f}\n"
            f"Signal: {sig['signal']}\n"
            f"Strategies: {', '.join(sig.get('strategies', []))}"
        )

    def manage_open_trades(self):
        symbols_to_check = list(self.open_trades.keys())

        for symbol in symbols_to_check:
            if symbol not in self.open_trades:
                continue

            trade = self.open_trades[symbol]
            trade["scan_count"] += 1

            try:
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker["last"]
                high = ticker["high"]
                low = ticker["low"]
            except Exception as e:
                logger.error(f"Failed to fetch ticker for {symbol}: {e}")
                continue

            trade["max_price"] = max(trade["max_price"], high)
            trade["min_price"] = min(trade["min_price"], low)

            direction = trade["direction"]
            sl = trade["sl_price"]
            tp = trade["tp_price"]
            entry = trade["entry_price"]

            closed = False
            exit_price = None
            reason = ""

            if direction == BUY:
                if low <= sl:
                    exit_price = sl
                    reason = "STOP_LOSS"
                    closed = True
                elif high >= tp:
                    exit_price = tp
                    reason = "TAKE_PROFIT"
                    closed = True
            else:
                if high >= sl:
                    exit_price = sl
                    reason = "STOP_LOSS"
                    closed = True
                elif low <= tp:
                    exit_price = tp
                    reason = "TAKE_PROFIT"
                    closed = True

            if not closed and trade["scan_count"] >= BREAKEVEN_AFTER_SCANS:
                pnl_pct = (current_price - entry) / entry * 100 if direction == BUY else (entry - current_price) / entry * 100
                if pnl_pct > 0.3:
                    if direction == BUY and sl < entry:
                        trade["sl_price"] = entry
                        logger.info(f"Moved {symbol} SL to breakeven @ ${entry:.4f}")
                    elif direction == SELL and sl > entry:
                        trade["sl_price"] = entry
                        logger.info(f"Moved {symbol} SL to breakeven @ ${entry:.4f}")

            if not closed and trade["scan_count"] >= MAX_HOLD_SCANS:
                exit_price = current_price
                reason = "MAX_HOLD_TIME"
                closed = True

            if closed:
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

        if not self.dry_run:
            try:
                if direction == BUY:
                    self.exchange.create_market_order(symbol, "sell", qty)
                else:
                    self.exchange.create_market_order(symbol, "buy", qty)
            except Exception as e:
                logger.error(f"Failed to close {symbol}: {e}")

        emoji = "✅" if pnl_usd >= 0 else "❌"
        logger.trade(f"{emoji} CLOSED: {symbol} | PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f}) | Reason: {reason}")

        self._save_trade(trade, "closed")
        self.closed_trades.append(trade)
        del self.open_trades[symbol]

        send_alerts(
            f"{emoji} **TRADE CLOSED**",
            f"**{symbol}**\n"
            f"PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
            f"Reason: {reason}"
        )

    def reset_daily_pnl(self):
        now = datetime.now(timezone.utc)
        if now.hour == 0 and now.minute < SCAN_INTERVAL_MIN:
            self.daily_pnl = 0.0
            self.daily_start_balance = self.balance
            logger.info(f"Daily PnL reset. New starting balance: ${self.balance:.2f}")

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
            self.initialize()

            logger.info("\nStarting live trading loop...")
            logger.info("Press Ctrl+C to stop\n")

            while self.running:
                try:
                    self.scan_count += 1
                    self.last_scan_time = datetime.now(timezone.utc).isoformat()
                    self.next_scan_time = (datetime.now(timezone.utc) + __import__("datetime").timedelta(minutes=SCAN_INTERVAL_MIN)).isoformat()

                    self.reset_daily_pnl()
                    self.scan_and_trade()
                    self.manage_open_trades()
                    self._log_equity()
                    self.print_status()

                    logger.info(f"Next scan in {SCAN_INTERVAL_MIN} minutes...")
                    for _ in range(SCAN_INTERVAL_MIN * 6):
                        if not self.running:
                            break
                        time.sleep(10)

                except Exception as e:
                    logger.error(f"Scan error: {e}\n{traceback.format_exc()}")
                    time.sleep(60)

            logger.info("Trading loop stopped. Closing all open trades...")

            for symbol in list(self.open_trades.keys()):
                try:
                    ticker = self.exchange.fetch_ticker(symbol)
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
