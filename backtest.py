"""
Azalyst Alpha X - 2-Month Historical Backtest Engine
=====================================================
Fetches 15m candles from Binance for the top coins and simulates the
multi-strategy consensus engine with realistic SL/TP/trailing logic.

Usage:
    python backtest.py
    python backtest.py --days 60 --top-coins 30
    python backtest.py --optimize
"""

from __future__ import annotations

import argparse
import time
import sys
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

JSON_OUTPUT = False

def print_progress_bar(iteration, total, prefix='', suffix='', decimals=1, length=40, fill='-', start_time=None):
    """Call in a loop to create terminal progress bar with ETA or JSON output"""
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    
    eta_str = "--:--"
    if start_time and iteration > 0:
        elapsed = time.time() - start_time
        eta_seconds = elapsed * (total / iteration - 1)
        m, s = divmod(int(eta_seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            eta_str = f"{h:02d}:{m:02d}:{s:02d}"
        else:
            eta_str = f"{m:02d}:{s:02d}"
            
    if JSON_OUTPUT:
        import json
        print(json.dumps({"type": "progress", "prefix": prefix.strip(), "symbol": suffix.strip(), "percent": float(percent), "eta": eta_str}), flush=True)
    else:
        # Use \033[K to clear line to end
        sys.stdout.write(f'\r\033[K{prefix} |{bar}| {percent}% {suffix} | ETA: {eta_str}')
        sys.stdout.flush()
        if iteration == total: 
            print()

import ccxt
import numpy as np
import pandas as pd

# -- Project imports --------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from azalyst.config import (
    BUY, SELL, HOLD,
    LEVERAGE, RISK_PER_TRADE, ATR_MULT, TP_RR_RATIO,
    SL_MIN_PCT, SL_MAX_PCT, MAX_OPEN_TRADES, MAX_HOLD_SCANS,
    BREAKEVEN_AFTER_SCANS, MIN_AGREEMENT, WEIGHTED_THRESHOLD,
    MULTI_WEIGHTS, EXCLUDE_SYMBOLS, MIN_VOLUME_MA, TOP_N_COINS,
    MAX_SAME_DIRECTION, TAKER_FEE, SLIPPAGE_BPS, CANDLE_TF_MIN,
    TRAILING_STOP_ENABLED,
)
from azalyst.indicators import compute_indicators
from azalyst.strategies import MULTI_STRATEGIES
from azalyst.strategies.htf_filter import get_htf_trend


# =====================================================================
#  BACKTEST ENGINE
# =====================================================================

class BacktestEngine:
    """Simulates the live trader logic on historical candle data."""

    def __init__(self, config: dict):
        self.config = config
        self.balance = config["initial_balance"]
        self.initial_balance = config["initial_balance"]
        self.leverage = config["leverage"]
        self.risk_per_trade = config["risk_per_trade"]
        self.atr_mult = config["atr_mult"]
        self.tp_rr_ratio = config["tp_rr_ratio"]
        self.sl_min_pct = config["sl_min_pct"]
        self.sl_max_pct = config["sl_max_pct"]
        self.max_open = config["max_open_trades"]
        self.max_hold = config["max_hold_scans"]
        self.be_scans = config["breakeven_scans"]
        self.min_agree = config["min_agreement"]
        self.weight_thresh = config["weighted_threshold"]
        self.weights = config["weights"]
        self.trail_pct = config["trail_pct"]

        self.open_trades: dict = {}
        self.closed_trades: list = []
        self.equity_curve: list = []
        self.peak_balance = self.balance

    def _consensus(self, df: pd.DataFrame, htf_slice: pd.DataFrame = None) -> dict | None:
        from azalyst.consensus import multi_strategy_scan
        # --- Adaptive Consensus (Regime Awareness) ---
        adx_val = df["adx_14"].iloc[-1]
        # Trending = 1 agreement, Sideways = 2 agreement
        dynamic_min = 1 if adx_val > 20 else 2
        return multi_strategy_scan(df, htf_df=htf_slice, min_agreement=dynamic_min)

    def _open_trade(self, symbol: str, bar: pd.Series, sig: dict, bar_time):
        direction = sig["direction"]
        atr = sig["atr"]
        price = bar["close"]
        
        # --- Alpha-X Logic (Main.py Parity) ---
        is_alpha = "alpha_x" in sig.get("strategies", [])
        
        # SL detection (Pullback candle is bar index -1 in this context)
        # But in backtest.py, we are passed the 'ind' which ends at 'current'.
        # Pullback was index -2 in the strategy but index -2 in 'ind' is the same.
        prev_bar = bar # current bar (trigger candle)
        # We need the pullback bar which is ind.iloc[-2]
        # Since ind is sliced [:idx+1], ind.iloc[-1] is trigger, ind.iloc[-2] is pullback.
        # This function only gets 'bar' (ind.iloc[-1]). I'll use indicators from the df.
        
        # Fib Target Calculation
        sh = bar["local_swing_high"]
        sl_low = bar["local_swing_low"]
        move = sh - sl_low
        
        # Slippage
        slip = SLIPPAGE_BPS / 10000
        fill = price * (1 + slip) if direction == BUY else price * (1 - slip)

        # --- Market Regime Detection (Adaptive Risk) ---
        adx = bar.get("adx_14", 0)
        is_trending = adx > 20
        
        current_risk = self.risk_per_trade
        current_tp_ratio = self.tp_rr_ratio
        
        if not is_trending:
            current_tp_ratio = 1.4

        if is_alpha:
            # SL is the pullback candle extreme
            if direction == BUY:
                sl = bar["low"] * 0.9975 # 0.25% Buffer
                # CAPPING:
                min_sl = fill * (1 - self.sl_max_pct)
                if sl < min_sl: sl = min_sl

                tp1 = fill + move * 1.272
                tp2 = fill + move * 1.618
            else:
                sl = bar["high"] * 1.0025
                # CAPPING:
                max_sl = fill * (1 + self.sl_max_pct)
                if sl > max_sl: sl = max_sl

                tp1 = fill - move * 1.272
                tp2 = fill - move * 1.618
        else:
            # Standard ATR logic for other strategies
            sl_dist = max(min(self.atr_mult * atr, fill * self.sl_max_pct), fill * self.sl_min_pct)
            if direction == BUY:
                sl = fill - sl_dist
                tp1 = fill + sl_dist * current_tp_ratio
                tp2 = fill + sl_dist * (current_tp_ratio + 1.0)
            else:
                sl = fill + sl_dist
                tp1 = fill - sl_dist * current_tp_ratio
                tp2 = fill - sl_dist * (current_tp_ratio + 1.0)

        # Calculate Position Size (Notional)
        # We risk a % of balance, then apply leverage to get the total position size.
        position_size = self.balance * current_risk * self.leverage
        qty = position_size / fill

        self.open_trades[symbol] = {
            "symbol": symbol,
            "direction": direction,
            "entry_price": fill,
            "qty": qty,
            "sl_price": sl,
            "tp1": tp1,
            "tp2": tp2,
            "sl_dist_pct": abs(fill - sl) / fill * 100 if fill > 0 else 0,
            "entry_time": bar_time,
            "scan_count": 0,
            "atr": atr,
            "strategies": sig["strategies"],
            "extended": False,
            "is_alpha": is_alpha,
            "sab": sig.get("sab", {}),
        }

    def _manage_trade(self, symbol: str, bar: pd.Series, bar_time):
        trade = self.open_trades[symbol]
        trade["scan_count"] += 1

        direction = trade["direction"]
        entry = trade["entry_price"]
        sl = trade["sl_price"]
        tp1 = trade.get("tp1", 0)
        tp2 = trade.get("tp2", 0)
        
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]

        upper = bar.get("bb200_upper", close)
        lower = bar.get("bb200_lower", close)
        tol = upper * 0.0025 # TOUCH_TOL

        closed = False
        exit_price = 0.0
        reason = ""

        # --- Alpha-X Stateful Exit Logic (High Priority) ---
        if trade.get("is_alpha"):
            # 1. Update Extensions (Must CLOSE beyond)
            if not trade["extended"]:
                if (direction == BUY and close > upper) or (direction == SELL and close < lower):
                    trade["extended"] = True

            # 2. Check for Band-Touch Harvest (Anti-Flush Patch)
            if trade["extended"] and trade["scan_count"] > 0:
                is_profitable = False
                if direction == BUY and upper > entry:
                    is_profitable = True
                elif direction == SELL and lower < entry:
                    is_profitable = True

                if is_profitable:
                    if direction == BUY:
                        # Low wicks to band AND High is at/above band level
                        if low <= upper + tol and high >= upper - tol:
                            exit_price, reason, closed = upper, "ALPHA_X_HARVEST [OK]", True
                    else:
                        # High wicks to band AND Low is at/below band level
                        if high >= lower - tol and low <= lower + tol:
                            exit_price, reason, closed = lower, "ALPHA_X_HARVEST [OK]", True

        # Standard safety net (SL/TP)
        if not closed:
            if direction == BUY:
                if low <= sl:
                    exit_price, reason, closed = sl, "STOP_LOSS", True
                elif tp2 and high >= tp2:
                    exit_price, reason, closed = tp2, "TAKE_PROFIT_FIB2", True
                elif tp1 and high >= tp1:
                    exit_price, reason, closed = tp1, "TAKE_PROFIT_FIB1", True
            else:
                if high >= sl:
                    exit_price, reason, closed = sl, "STOP_LOSS", True
                elif tp2 and low <= tp2:
                    exit_price, reason, closed = tp2, "TAKE_PROFIT_FIB2", True
                elif tp1 and low <= tp1:
                    exit_price, reason, closed = tp1, "TAKE_PROFIT_FIB1", True

        # Breakeven
        if not closed and trade["scan_count"] >= self.be_scans:
            pnl_pct = (close - entry) / entry * 100 if direction == BUY else (entry - close) / entry * 100
            if pnl_pct > 0 and ((direction == BUY and sl < entry) or (direction == SELL and sl > entry)):
                trade["sl_price"] = entry

        # --- DYNAMIC TRAILING PROTECTION (Adaptive Regime) ---
        if not closed:
            pnl_pct = (close - entry) / entry * 100 if direction == BUY else (entry - close) / entry * 100
            adx = bar.get("adx_14", 0)
            is_trending = adx > 20
            new_sl = None

            if not is_trending:
                # SIDEWAYS: Lock profit at 1.0%
                if pnl_pct >= 1.0:
                    new_sl = entry * (1 + 0.002) if direction == BUY else entry * (1 - 0.002)
            else:
                # TRENDING: Milestone Trailing
                if pnl_pct >= 10.0:
                    new_sl = entry * (1 + 0.07) if direction == BUY else entry * (1 - 0.07)
                elif pnl_pct >= 6.0:
                    new_sl = entry * (1 + 0.03) if direction == BUY else entry * (1 - 0.03)
                elif pnl_pct >= 5.0:
                    new_sl = entry * (1 + 0.002) if direction == BUY else entry * (1 - 0.002)

            if new_sl:
                if (direction == BUY and new_sl > trade["sl_price"]) or \
                   (direction == SELL and new_sl < trade["sl_price"]):
                    trade["sl_price"] = new_sl

        # Max hold
        if not closed and trade["scan_count"] >= self.max_hold:
            exit_price, reason, closed = close, "MAX_HOLD_TIME", True

        if closed:
            if reason == "STOP_LOSS":
                if abs(exit_price - entry) < entry * 0.0001:
                    reason = "BREAKEVEN"
                elif (direction == BUY and exit_price > entry) or (direction == SELL and exit_price < entry):
                    reason = "TRAILING_STOP"
            self._close_trade(symbol, exit_price, reason, bar_time)

    def _close_trade(self, symbol: str, exit_price: float, reason: str, bar_time):
        trade = self.open_trades.pop(symbol)
        entry = trade["entry_price"]
        direction = trade["direction"]

        # Industry Standard P&L Calculation: Qty * (Exit - Entry)
        raw_pnl = trade["qty"] * (exit_price - entry) if direction == BUY else trade["qty"] * (entry - exit_price)
        
        # Calculate Fees based on Notional Value (Entry + Exit)
        entry_fee = (trade["qty"] * entry) * TAKER_FEE
        exit_fee = (trade["qty"] * exit_price) * TAKER_FEE
        pnl_usd = raw_pnl - (entry_fee + exit_fee)
        
        self.balance += pnl_usd
        self.peak_balance = max(self.peak_balance, self.balance)
        
        # Update pnl_pct to be Notional P&L % (ROE) for the report
        pnl_pct = (pnl_usd / (trade["qty"] * entry / self.leverage)) * 100 if trade["qty"] > 0 else 0

        trade["exit_price"] = exit_price
        trade["exit_time"] = bar_time
        trade["pnl_pct"] = pnl_pct
        trade["pnl_usd"] = pnl_usd
        trade["reason"] = reason
        self.closed_trades.append(trade)

    def run(self, all_data: dict, htf_data: dict, scan_every_n: int = 2):
        """
        all_data: {symbol: DataFrame of 15m candles}
        htf_data: {symbol: DataFrame of 4h candles}
        scan_every_n: simulate scanning every N bars (2 bars = 30min for 15m TF)
        """
        start_time = time.time()
        global JSON_OUTPUT
        
        # Build a global timeline from all symbols
        all_times = set()
        for df in all_data.values():
            all_times.update(df.index.tolist())
        timeline = sorted(all_times)

        if not JSON_OUTPUT:
            print(f"\n- Running backtest over {len(timeline)} bars ({len(all_data)} symbols)...\n")

        bar_counter = 0
        loop_start = time.time()
        for t in timeline:
            bar_counter += 1
            if bar_counter % 25 == 0 or bar_counter == len(timeline):
                print_progress_bar(bar_counter, len(timeline), prefix='Simulation:', suffix='Bars Processed', start_time=loop_start)

            # Manage existing trades on EVERY bar
            for sym in list(self.open_trades.keys()):
                if sym in all_data:
                    try:
                        bar = all_data[sym].loc[t]
                        self._manage_trade(sym, bar, t)
                    except KeyError:
                        pass

            # Scan for new trades every N bars
            if bar_counter % scan_every_n != 0:
                continue

            if len(self.open_trades) >= self.max_open:
                continue

            # Calculate used margin (Margin = Notional / Leverage)
            used_margin = sum([(t["qty"] * t["entry_price"]) / self.leverage for t in self.open_trades.values()])
            if used_margin >= self.balance * 0.95: # Keep 5% buffer
                continue

            for sym, df in all_data.items():
                if sym in self.open_trades:
                    continue
                if len(self.open_trades) >= self.max_open:
                    break

                try:
                    idx = df.index.get_loc(t)
                    if isinstance(idx, slice):
                        idx = idx.stop - 1
                except KeyError:
                    continue

                if idx < 200:
                    continue

                # We slice the precomputed dataframe (fast view reference)
                ind = df.iloc[:idx+1]

                if ind["atr_14"].iloc[-1] == 0 or np.isnan(ind["atr_14"].iloc[-1]):
                    continue

                # --- Institutional Lockdown: Exposure Guards ---
                open_list = list(self.open_trades.values())
                longs = [t for t in open_list if t["direction"] == BUY]
                shorts = [t for t in open_list if t["direction"] == SELL]
                
                # HTF trend & slice
                htf_slice = None
                if sym in htf_data:
                    try:
                        htf_idx = htf_data[sym].index.get_indexer([t], method='pad')[0]
                        if htf_idx >= 0 and htf_idx >= 200:
                            htf_slice = htf_data[sym].iloc[:htf_idx+1]
                    except Exception:
                        pass

                sig = self._consensus(ind, htf_slice)
                if sig:
                    # 1. Directional Correlation Cap
                    direction = sig["direction"]
                    if direction == BUY and len(longs) >= self.config["max_same_direction"]:
                        continue
                    if direction == SELL and len(shorts) >= self.config["max_same_direction"]:
                        continue

                    # 2. Strategy Exposure Limit (Alpha-X)
                    if "alpha_x" in sig.get("strategies", []):
                        alpha_x_count = len([t for t in open_list if "alpha_x" in t.get("strategies", [])])
                        if alpha_x_count >= 7:
                            continue

                    self._open_trade(sym, ind.iloc[-1], sig, t)

            # Log equity
            self.equity_curve.append({"time": t, "balance": self.balance, "open": len(self.open_trades)})

        # Close any remaining open trades at last known price
        for sym in list(self.open_trades.keys()):
            if sym in all_data and len(all_data[sym]) > 0:
                last = all_data[sym].iloc[-1]
                self._close_trade(sym, last["close"], "BACKTEST_END", all_data[sym].index[-1])
                
        elapsed = time.time() - start_time
        if not JSON_OUTPUT:
            print(f"\n[OK] Backtest completed in {elapsed:.2f} seconds.")

    def report(self) -> dict:
        trades = self.closed_trades
        if not trades:
            return {"error": "No trades taken"}

        winners = [t for t in trades if t["pnl_usd"] > 0]
        losers = [t for t in trades if t["pnl_usd"] <= 0]

        total_pnl = sum(t["pnl_usd"] for t in trades)
        avg_win = np.mean([t["pnl_usd"] for t in winners]) if winners else 0
        avg_loss = np.mean([t["pnl_usd"] for t in losers]) if losers else 0
        win_rate = len(winners) / len(trades) * 100

        gross_profit = sum(t["pnl_usd"] for t in winners)
        gross_loss = abs(sum(t["pnl_usd"] for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        max_dd = 0
        peak = self.initial_balance
        running = self.initial_balance
        for t in trades:
            running += t["pnl_usd"]
            peak = max(peak, running)
            dd = (peak - running) / peak * 100
            max_dd = max(max_dd, dd)

        # Per-strategy breakdown
        strat_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0})
        for t in trades:
            for s in t.get("strategies", []):
                strat_stats[s]["count"] += 1
                strat_stats[s]["pnl"] += t["pnl_usd"]
                if t["pnl_usd"] > 0:
                    strat_stats[s]["wins"] += 1
                else:
                    strat_stats[s]["losses"] += 1

        # Per-reason breakdown
        reason_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0})
        for t in trades:
            r = t["reason"]
            reason_stats[r]["count"] += 1
            reason_stats[r]["pnl"] += t["pnl_usd"]

        # Day of week stats
        day_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        days_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        for t in trades:
            # We need to extract the day from the entry_time
            # entry_time is likely a datetime object from the simulation
            dt = t["entry_time"]
            day_name = days_names[dt.weekday()]
            day_stats[day_name]["count"] += 1
            day_stats[day_name]["pnl"] += t["pnl_usd"]
            if t["pnl_usd"] > 0:
                day_stats[day_name]["wins"] += 1

        return {
            "total_trades": len(trades),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "final_balance": round(self.balance, 2),
            "return_pct": round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            "strategy_breakdown": dict(strat_stats),
            "reason_breakdown": dict(reason_stats),
            "day_breakdown": dict(day_stats),
            "trades": trades,
        }


# ---------------------------------------------------------------------
#  DATA FETCHING
# ---------------------------------------------------------------------

def fetch_historical(exchange, symbol: str, tf: str, since_ms: int, limit_per_call: int = 1000) -> pd.DataFrame:
    """Paginated OHLCV fetch for historical data."""
    all_rows = []
    current_since = since_ms

    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, tf, since=current_since, limit=limit_per_call)
        except Exception as e:
            # print(f"  - Failed to fetch {symbol} {tf}: {e}")
            break

        if not ohlcv:
            break

        all_rows.extend(ohlcv)
        last_ts = ohlcv[-1][0]
        if last_ts <= current_since:
            break
        current_since = last_ts + 1

        if len(ohlcv) < limit_per_call:
            break

        time.sleep(0.15)  # respectful rate limit

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df = df[~df.index.duplicated(keep="last")]
    return df


def get_top_symbols(exchange, n: int = 30) -> list:
    """Get top N symbols by volume."""
    print("- Fetching market data from Binance...")
    markets = exchange.load_markets()

    usdt_symbols = [
        s for s, m in markets.items()
        if (s.endswith("/USDT:USDT")) and m.get("active", True)
    ]

    filtered = []
    for s in usdt_symbols:
        base = s.split("/")[0]
        full_name = s.replace("/USDT", "").replace(":", "")
        if full_name not in EXCLUDE_SYMBOLS and base not in EXCLUDE_SYMBOLS:
            filtered.append(s)

    print(f"  Found {len(filtered)} active futures pairs. Fetching volumes...")
    tickers = exchange.fetch_tickers()

    ranked = []
    for sym in filtered:
        if sym in tickers:
            vol = tickers[sym].get("quoteVolume", 0) or 0
            if vol > MIN_VOLUME_MA:
                ranked.append((sym, vol))

    ranked.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in ranked[:n]]
    print(f"  Selected top {len(symbols)} symbols by volume.\n")
    return symbols


# ---------------------------------------------------------------------
#  PRINTING
# ---------------------------------------------------------------------

def print_report(report: dict, config_label: str = "DEFAULT"):
    print("\n" + "=" * 80)
    print(f"  BACKTEST RESULTS - {config_label}")
    print("=" * 80)

    if "error" in report:
        print(f"  [ERROR] {report['error']}")
        return

    pnl_label = "[WIN]" if report["total_pnl"] >= 0 else "[LOSS]"

    print(f"  Total Trades:    {report['total_trades']}")
    print(f"  Winners:         {report['winners']}")
    print(f"  Losers:          {report['losers']}")
    print(f"  Win Rate:        {report['win_rate']}%")
    print(f"  {pnl_label} Total P&L:      ${report['total_pnl']}")
    print(f"  Avg Winner:      ${report['avg_win']}")
    print(f"  Avg Loser:       ${report['avg_loss']}")
    print(f"  Profit Factor:   {report['profit_factor']}")
    print(f"  Max Drawdown:    {report['max_drawdown_pct']}%")
    print(f"  Final Balance:   ${report['final_balance']}")
    print(f"  Total Return:    {report['return_pct']}%")

    print("\n  -- Strategy Breakdown --")
    strats = report.get("strategy_breakdown", {})
    sorted_strats = sorted(strats.items(), key=lambda x: x[1]["pnl"], reverse=True)
    print(f"  {'Strategy':<18} {'Trades':>7} {'Wins':>6} {'Losses':>7} {'Net P&L':>10} {'Win%':>7}")
    print(f"  {'-'*18} {'-'*7} {'-'*6} {'-'*7} {'-'*10} {'-'*7}")
    for name, s in sorted_strats:
        wr = s["wins"] / s["count"] * 100 if s["count"] > 0 else 0
        status = "[OK]" if s["pnl"] > 0 else "[X]"
        print(f"  {status} {name:<15} {s['count']:>7} {s['wins']:>6} {s['losses']:>7} ${s['pnl']:>+9.2f} {wr:>6.1f}%")

    print("\n  -- Weekly Performance --")
    days_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_stats = report.get("day_breakdown", {})
    print(f"  {'Day':<12} {'Trades':>7} {'Win%':>7} {'Net P&L':>12}")
    print(f"  {'-'*12} {'-'*7} {'-'*7} {'-'*12}")
    for day in days_names:
        s = day_stats.get(day, {"count": 0, "pnl": 0.0, "wins": 0})
        wr = s["wins"] / s["count"] * 100 if s["count"] > 0 else 0
        status = "[OK]" if s["pnl"] > 0 else "[X]"
        print(f"  {status} {day:<9} {s['count']:>7} {wr:>6.1f}% ${s['pnl']:>+11.2f}")

    print("\n  -- Exit Reason Breakdown --")
    reasons = report.get("reason_breakdown", {})
    sorted_reasons = sorted(reasons.items(), key=lambda x: x[1]["count"], reverse=True)
    for r, s in sorted_reasons:
        status = "[OK]" if s["pnl"] > 0 else "[X]"
        print(f"  {status} {r:<20} {s['count']:>4} trades   ${s['pnl']:>+9.2f}")

    print("=" * 80)
    
    # Save trades to CSV
    if report.get("trades"):
        import csv
        safe_label = config_label.replace(" ", "_").replace("(", "").replace(")", "").replace(",", "").lower()
        filename = f"backtest_trades_{safe_label}.csv"
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Symbol", "Direction", "Entry Time", "Exit Time", "Entry Price",
                    "Exit Price", "SL Distance %", "PnL %", "PnL $", "Reason", "Strategies",
                    "SAB S-Score", "SAB A-Score", "SAB B-Bonus"
                ])
                for t in report["trades"]:
                    sab = t.get("sab", {})
                    writer.writerow([
                        t["symbol"],
                        "LONG" if t["direction"] == BUY else "SHORT",
                        t["entry_time"],
                        t["exit_time"],
                        f"{t['entry_price']:.6f}",
                        f"{t['exit_price']:.6f}",
                        f"{t.get('sl_dist_pct', 0):.2f}%",
                        f"{t['pnl_pct']:.2f}%",
                        f"${t['pnl_usd']:.2f}",
                        t["reason"],
                        ", ".join(t.get("strategies", [])),
                        sab.get("s_score", "N/A"),
                        sab.get("a_score", "N/A"),
                        sab.get("b_bonus", "N/A"),
                    ])
            print(f"  - Trade history saved to {filename}")
        except Exception as e:
            print(f"  - Failed to save CSV: {e}")



# =====================================================================
#  MAIN
# =====================================================================

def main():
    global JSON_OUTPUT
    parser = argparse.ArgumentParser(description="Azalyst Alpha X - 2-Month Backtest")
    parser.add_argument("--days", type=int, default=60, help="Number of days to backtest (default: 60)")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Output JSON for dashboard parsing")
    parser.add_argument("--config", type=str, help="JSON string of config overrides")
    parser.add_argument("--top-coins", type=int, default=25, help="Number of top coins by volume (default: 25)")
    parser.add_argument("--scan-bars", type=int, default=2, help="Scan every N bars (2 = 30min for 15m TF)")
    parser.add_argument("--optimize", action="store_true", help="Run multiple configs and compare")
    parser.add_argument("--no-sab", action="store_true", help="Disable S-A-B gate (runs pure strategy vote for comparison)")
    args = parser.parse_args()
    
    if args.json:
        JSON_OUTPUT = True
    
    sab_on = not args.no_sab
    if not JSON_OUTPUT:
        if not sab_on:
            print("[WARN] SAB gate DISABLED -- running pure strategy vote mode for comparison.")
        else:
            print("[OK] SAB gate ENABLED -- S-A-B tier validation active.")

    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})

    symbols = get_top_symbols(exchange, n=args.top_coins)

    if args.start_date:
        start_dt = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        since_ms = int(start_dt.timestamp() * 1000)
        if args.end_date:
            end_dt = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            end_dt = datetime.now(timezone.utc)
        args.days = (end_dt - start_dt).days
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
        since_ms = int(since_dt.timestamp() * 1000)
    
    fetch_start = time.time()

    # -- Fetch Candles --
    tf_str = f"{CANDLE_TF_MIN}m"
    all_data = {}
    if not JSON_OUTPUT:
        print(f"\n- Fetching {tf_str} data & precomputing indicators for {len(symbols)} symbols...")
    for i, sym in enumerate(symbols):
        print_progress_bar(i, len(symbols), prefix='Data Fetch (1/2):', suffix=f'[{sym:<10}]', start_time=fetch_start)
        df = fetch_historical(exchange, sym, tf_str, since_ms)
        if not df.empty and len(df) > 200:
            try:
                # Precompute indicators across the entire historical dataset ONCE. Wait time goes from hours to seconds!
                df = compute_indicators(df)
                all_data[sym] = df
            except Exception as e:
                pass
        time.sleep(0.2)
    print_progress_bar(len(symbols), len(symbols), prefix='Data Fetch (1/2):', suffix='[Done]      ', start_time=fetch_start)

    # -- Fetch 4h candles for HTF filter --
    htf_since_ms = int((datetime.now(timezone.utc) - timedelta(days=args.days + 60)).timestamp() * 1000)
    htf_data = {}
    if not JSON_OUTPUT:
        print(f"\n- Fetching 4h HTF data for {len(all_data)} symbols...")
    htf_start = time.time()
    for i, sym in enumerate(all_data.keys()):
        print_progress_bar(i, len(all_data), prefix='Data Fetch (2/2):', suffix=f'[{sym:<10}]', start_time=htf_start)
        df = fetch_historical(exchange, sym, "4h", htf_since_ms)
        if not df.empty and len(df) >= 200:
            # Precompute HTF indicators 
            df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
            df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
            htf_data[sym] = df
        time.sleep(0.2)
    print_progress_bar(len(all_data), len(all_data), prefix='Data Fetch (2/2):', suffix='[Done]      ', start_time=htf_start)

    if not JSON_OUTPUT:
        print(f"\n[OK] Data fetching & precomputation completed in {time.time() - fetch_start:.2f}s")
        print(f"   Stored {len(all_data)} symbols with {tf_str} candles, {len(htf_data)} with 4h HTF data.\n")

    # -- Define configs --
    default_config = {
        "initial_balance": 100.0,
        "leverage": LEVERAGE,
        "risk_per_trade": RISK_PER_TRADE,
        "atr_mult": ATR_MULT,
        "tp_rr_ratio": TP_RR_RATIO,
        "sl_min_pct": SL_MIN_PCT,
        "sl_max_pct": SL_MAX_PCT,
        "max_open_trades": MAX_OPEN_TRADES,
        "max_hold_scans": MAX_HOLD_SCANS,
        "breakeven_scans": BREAKEVEN_AFTER_SCANS,
        "min_agreement": MIN_AGREEMENT,
        "weighted_threshold": WEIGHTED_THRESHOLD,
        "weights": dict(MULTI_WEIGHTS),
        "trail_pct": 0.01,  # 1% trailing distance
        "max_same_direction": MAX_SAME_DIRECTION,
    }
    
    if args.config:
        try:
            import json
            overrides = json.loads(args.config)
            default_config.update(overrides)
        except Exception as e:
            if not JSON_OUTPUT:
                print(f"[ERR] Failed to parse config override: {e}")

    if not args.optimize:
        # -- Single run with current config --
        engine = BacktestEngine(default_config)
        engine.run(all_data, htf_data, scan_every_n=args.scan_bars)
        report = engine.report()
        if JSON_OUTPUT:
            import json
            print(json.dumps({"type": "result", "report": report}))
        else:
            print_report(report, "CURRENT CONFIG")
    else:
        # -- Optimization: compare multiple configs --
        configs = {
            "CURRENT": default_config,
            "CONSERVATIVE (3 agree, tight SL)": {
                **default_config,
                "min_agreement": 3,
                "weighted_threshold": 3.0,
                "sl_max_pct": 0.03,
                "weights": {**MULTI_WEIGHTS, "jadecap": 0.4, "fvg": 1.0},
            },
            "AGGRESSIVE (2 agree, wide TP)": {
                **default_config,
                "min_agreement": 2,
                "tp_rr_ratio": 2.0,
                "sl_max_pct": 0.04,
                "trail_pct": 0.008,
            },
            "BALANCED (3 agree, 1.8 TP RR)": {
                **default_config,
                "min_agreement": 3,
                "weighted_threshold": 2.5,
                "tp_rr_ratio": 1.8,
                "sl_max_pct": 0.03,
                "trail_pct": 0.01,
                "weights": {**MULTI_WEIGHTS, "jadecap": 0.4, "fvg": 1.0, "bnf": 2.5, "wyckoff": 2.5},
            },
        }

        results = {}
        for label, cfg in configs.items():
            print(f"\n- Running backtest: {label}...")
            engine = BacktestEngine(cfg)
            engine.run(all_data, htf_data, scan_every_n=args.scan_bars)
            report = engine.report()
            results[label] = report
            print_report(report, label)

        # -- Summary comparison --
        print("\n" + "=" * 80)
        print("  STAT OPTIMIZATION COMPARISON")
        print("=" * 80)
        print(f"  {'Config':<35} {'Trades':>7} {'Win%':>6} {'PnL':>10} {'PF':>6} {'MaxDD':>7} {'Return':>8}")
        print(f"  {'-'*35} {'-'*7} {'-'*6} {'-'*10} {'-'*6} {'-'*7} {'-'*8}")
        for label, r in results.items():
            if "error" in r:
                print(f"  {label:<35} {'NO TRADES':>7}")
                continue
            marker = "*" if r == max(results.values(), key=lambda x: x.get("total_pnl", -9999)) else " "
            print(
                f"  {marker}{label:<33} {r['total_trades']:>7} {r['win_rate']:>5.1f}% "
                f"${r['total_pnl']:>+9.2f} {r['profit_factor']:>5.2f} "
                f"{r['max_drawdown_pct']:>6.1f}% {r['return_pct']:>+7.1f}%"
            )
        print("=" * 80)


if __name__ == "__main__":
    main()
