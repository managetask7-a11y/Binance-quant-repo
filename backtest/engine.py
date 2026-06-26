from __future__ import annotations

import time
import sys
import numpy as np
import pandas as pd

from azalyst.config import (
    BUY, SELL, SLIPPAGE_BPS, TAKER_FEE, MAX_HOLD_SCANS,
    BREAKEVEN_AFTER_SCANS, CANDLE_TF_MIN, HTF_TIMEFRAME,
    TRAILING_STOP_ENABLED, REGIME_BTC_SYMBOL,
)
from azalyst.indicators import compute_indicators
from azalyst.consensus import multi_strategy_scan
from azalyst.regime import detect as detect_regime, MarketRegime, reset_regime_state
from azalyst.personalities import get_personality, DEFAULT_PERSONALITY, Personality


class BacktestEngine:

    def __init__(self, config: dict, use_regime: bool = True):
        self.config = config
        self.balance = config["initial_balance"]
        self.initial_balance = config["initial_balance"]
        self.leverage = config["leverage"]
        self.risk_per_trade = config["risk_per_trade"]
        self.max_open = config["max_open_trades"]
        self.max_hold = config["max_hold_scans"]
        self.be_scans = config["breakeven_scans"]
        self.use_regime = use_regime

        self.open_trades: dict = {}
        self.closed_trades: list = []
        self.equity_curve: list = []
        self.peak_balance = self.balance
        self.current_regime = MarketRegime.SIDEWAYS
        self.active_personality: Personality = DEFAULT_PERSONALITY
        self.regime_log: list = []

        self.cooldown: dict = {}
        self.trading_halted = False
        self._COOLDOWN_BARS = 16
        self._DD_HALT_PCT = 0.20
        self._DD_RESUME_PCT = 0.12

        reset_regime_state()

    def _detect_regime_at_bar(self, all_data: dict, htf_data: dict, current_time):
        if not self.use_regime:
            return

        btc_sym = None
        for sym in all_data:
            if "BTC" in sym:
                btc_sym = sym
                break

        if btc_sym is None:
            return

        df = all_data[btc_sym]
        try:
            idx = df.index.get_loc(current_time)
            if isinstance(idx, slice):
                idx = idx.stop - 1
        except KeyError:
            idx = df.index.get_indexer([current_time], method="pad")[0]

        if idx < 200:
            return

        btc_slice = df.iloc[:idx]

        htf_slice = None
        if btc_sym in htf_data:
            try:
                # Use closed-candle filter (matches signal scanning and live trader)
                htf_tf_mins = 240  # 4 hours
                closed_htf = htf_data[btc_sym][htf_data[btc_sym].index + pd.Timedelta(minutes=htf_tf_mins) <= current_time]
                if not closed_htf.empty and len(closed_htf) >= 200:
                    htf_slice = closed_htf
            except Exception:
                pass

        old = self.current_regime
        self.current_regime = detect_regime(btc_slice, htf_df=htf_slice, symbol="__MARKET__", current_regime=self.current_regime)
        self.active_personality = get_personality(self.current_regime)

        if old != self.current_regime:
            self.regime_log.append({
                "time": current_time,
                "from": old.value,
                "to": self.current_regime.value,
                "personality": self.active_personality.name,
            })

    def _check_drawdown_halt(self, current_time):
        if self.peak_balance <= 0:
            return
            
        # If currently halted, wait for timeout
        if hasattr(self, 'halt_until') and self.halt_until is not None:
            if current_time >= self.halt_until:
                self.trading_halted = False
                self.halt_until = None
                # Reset peak balance so we don't immediately halt again
                self.peak_balance = self.balance
            return

        current_dd = (self.peak_balance - self.balance) / self.peak_balance
        if not self.trading_halted and current_dd >= self._DD_HALT_PCT:
            self.trading_halted = True
            self.halt_until = current_time + pd.Timedelta(days=3) # Halt for 3 days

    def _open_trade(self, symbol: str, bar: pd.Series, sig: dict, bar_time):
        direction = sig["direction"]
        atr = sig["atr"]
        price = bar["close"]
        p = self.active_personality

        # [REAL-WORLD SIMULATION] Apply slippage to entry price
        slip = SLIPPAGE_BPS / 10000
        fill = price * (1 + slip) if direction == BUY else price * (1 - slip)

        atr_val = bar.get("atr_14", atr)
        raw_sl_dist = atr_val * p.atr_mult

        min_sl_dist = fill * p.sl_min_pct
        max_sl_dist = fill * p.sl_max_pct
        sl_dist = max(min_sl_dist, min(raw_sl_dist, max_sl_dist))

        effective_risk = self.risk_per_trade * p.risk_multiplier
        risk_usd = self.balance * effective_risk

        margin_pct = self.config.get("margin_per_trade_pct", 0.0)
        if margin_pct > 0:
            # Fixed % Margin Sizing (matches live trader)
            margin_usd = self.balance * margin_pct
            notional = margin_usd * p.leverage
            ideal_qty = notional / fill
        else:
            # Traditional Risk-Based Sizing
            ideal_qty = risk_usd / sl_dist if sl_dist > 0 else 0

        max_qty = (self.balance * p.leverage) / fill
        qty = min(ideal_qty, max_qty)

        tp_dist = sl_dist * p.tp_rr_ratio

        if direction == BUY:
            sl = fill - sl_dist
            tp1 = fill + tp_dist
        else:
            sl = fill + sl_dist
            tp1 = fill - tp_dist
        tp2 = None

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
            "atr_val": atr_val,
            "strategies": sig["strategies"],
            "extended": False,
            "is_alpha": False,
            "regime": self.current_regime.value,
            "personality": self.active_personality.name,
            "max_price": fill,
            "min_price": fill,
            "be_moved": False,
            "tp1_locked": False,
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

        trade["max_price"] = max(trade.get("max_price", close), high)
        trade["min_price"] = min(trade.get("min_price", close), low)

        closed = False
        exit_price = 0.0
        reason = ""

        # ═══════════════════════════════════════════════════════════════
        # PRIORITY 1: STOP LOSS / TAKE PROFIT CHECKS
        # [REAL-WORLD SIMULATION] Uses intra-bar High/Low wicks.
        # This accurately simulates real Binance execution where limits 
        # or stops are triggered mid-candle, not just at the close.
        # ═══════════════════════════════════════════════════════════════
        if not closed:
            if direction == BUY:
                if low <= sl:
                    exit_price, reason, closed = sl, "STOP_LOSS", True
                elif tp2 and high >= tp2:
                    exit_price, reason, closed = tp2, "TAKE_PROFIT_2", True
                elif tp1 and high >= tp1:
                    exit_price, reason, closed = tp1, "TAKE_PROFIT_1", True
            else:
                if high >= sl:
                    exit_price, reason, closed = sl, "STOP_LOSS", True
                elif tp2 and low <= tp2:
                    exit_price, reason, closed = tp2, "TAKE_PROFIT_2", True
                elif tp1 and low <= tp1:
                    exit_price, reason, closed = tp1, "TAKE_PROFIT_1", True

        # ═══════════════════════════════════════════════════════════════
        # PRIORITY 2: BREAKEVEN PROTECTION (at 1.5 ATR profit)
        # Move SL to entry + fees + 0.2% lock.
        # Small lock so it doesn't interfere with trailing stop.
        # ═══════════════════════════════════════════════════════════════
        if not closed and not trade.get("be_moved", False) and self.active_personality.trailing_enabled:
            atr_val = trade.get("atr_val", trade["atr"])
            if atr_val > 0:
                if direction == BUY:
                    pnl_atr = (close - entry) / atr_val
                else:
                    pnl_atr = (entry - close) / atr_val
                if pnl_atr >= 1.5:
                    fee_buffer = entry * TAKER_FEE * 2
                    profit_lock = entry * 0.002  # 0.2% — small lock, won't interfere with trail
                    if direction == BUY:
                        new_sl = entry + fee_buffer + profit_lock
                        if new_sl > trade["sl_price"]:
                            trade["sl_price"] = new_sl
                            trade["be_moved"] = True
                    else:
                        new_sl = entry - fee_buffer - profit_lock
                        if new_sl < trade["sl_price"]:
                            trade["sl_price"] = new_sl
                            trade["be_moved"] = True

        # ═══════════════════════════════════════════════════════════════
        # PRIORITY 3: TRAILING STOP (percentage-based from peak)
        # [D8 FIX] Uses same pnl_move formula as live trader for both
        # LONG and SHORT directions.
        # ═══════════════════════════════════════════════════════════════
        p = self.active_personality
        if not closed and p.trailing_enabled:
            pnl_move = (close - entry) / entry  # same as live for LONG
            if direction == BUY:
                if pnl_move >= p.trail_trigger_pct:
                    new_sl = trade["max_price"] * (1 - p.trail_distance_pct)
                    new_sl = max(new_sl, entry)  # never below entry
                    if new_sl > trade["sl_price"]:
                        trade["sl_price"] = new_sl
            else:
                # [D8 FIX] Live SHORT uses: pnl_move <= -trail_trigger_pct
                # i.e., pnl_move is still (close-entry)/entry, but for shorts
                # a profitable move means pnl_move is negative
                if pnl_move <= -p.trail_trigger_pct:
                    new_sl = trade["min_price"] * (1 + p.trail_distance_pct)
                    new_sl = min(new_sl, entry)  # never above entry
                    if new_sl < trade["sl_price"]:
                        trade["sl_price"] = new_sl

        # ═══════════════════════════════════════════════════════════════
        # PRIORITY 4: ALPHA-X STATEFUL EXIT (ported from live trader)
        # [D7 FIX] Live has Alpha-X EXTENDED + band-harvest logic that
        # was completely missing from the backtest engine.
        # ═══════════════════════════════════════════════════════════════
        if not closed and trade.get("is_alpha"):
            upper = bar.get("bb200_upper", 0)
            lower = bar.get("bb200_lower", 0)
            tol = upper * 0.0025 if upper > 0 else 0  # TOUCH_TOL

            # 1. Update Extensions (must CLOSE beyond band)
            is_extended = trade.get("extended", False)
            if not is_extended:
                if (direction == BUY and close > upper) or \
                   (direction == SELL and close < lower):
                    trade["extended"] = True

            # 2. Band-Touch Harvest
            if trade.get("extended") and trade["scan_count"] > 0:
                is_profitable = (direction == BUY and close > entry) or \
                                (direction == SELL and close < entry)
                if is_profitable:
                    if direction == BUY:
                        if low <= upper + tol and high >= upper - tol:
                            exit_price, reason, closed = close, "ALPHA_X_HARVEST", True
                    else:
                        if high >= lower - tol and low <= lower + tol:
                            exit_price, reason, closed = close, "ALPHA_X_HARVEST", True

        # ═══════════════════════════════════════════════════════════════
        # PRIORITY 5: MAX HOLD TIME
        # ═══════════════════════════════════════════════════════════════
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

        raw_pnl = trade["qty"] * (exit_price - entry) if direction == BUY else trade["qty"] * (entry - exit_price)
        entry_fee = (trade["qty"] * entry) * TAKER_FEE
        exit_fee = (trade["qty"] * exit_price) * TAKER_FEE
        pnl_usd = raw_pnl - (entry_fee + exit_fee)

        self.balance += pnl_usd
        self.peak_balance = max(self.peak_balance, self.balance)

        pnl_pct = (pnl_usd / (trade["qty"] * entry / self.leverage)) * 100 if trade["qty"] > 0 else 0

        trade["exit_price"] = exit_price
        trade["exit_time"] = bar_time
        trade["pnl_pct"] = pnl_pct
        trade["pnl_usd"] = pnl_usd
        trade["reason"] = reason
        self.closed_trades.append(trade)

        self.cooldown[symbol] = self._COOLDOWN_BARS

    def run(self, all_data: dict, htf_data: dict, start_date, end_date, 
            scan_every_n: int = 1, dynamic_top: bool = False, top_n: int = 20,
            trade_symbols: list[str] | None = None):
        t0 = time.time()
        # [D2 FIX] Preserve trade_symbols insertion order instead of sorting alphabetically.
        # Live trader uses GOLD_COINS order; sorted() changed symbol priority when order cap was hit.
        if trade_symbols:
            self.active_symbols = [s for s in trade_symbols if s in all_data]
        else:
            self.active_symbols = sorted(list(all_data.keys()))
            if not dynamic_top:
                self.active_symbols = self.active_symbols[:top_n]

        all_times = set()
        for df in all_data.values():
            all_times.update(df.index.tolist())
        timeline = sorted([t for t in all_times if start_date <= t <= end_date])

        print(f"\n  Running backtest over {len(timeline)} bars ({len(all_data)} symbols)...")

        bar_counter = 0
        total = len(timeline)

        for t in timeline:
            bar_counter += 1

            if bar_counter % 50 == 0 or bar_counter == total:
                pct = bar_counter / total * 100
                elapsed = time.time() - t0
                eta = elapsed / bar_counter * (total - bar_counter) if bar_counter > 0 else 0
                sys.stdout.write(f"\r  Simulation: {pct:.1f}% | {bar_counter}/{total} bars | ETA: {int(eta)}s   ")
                sys.stdout.flush()

            for sym in list(self.cooldown.keys()):
                self.cooldown[sym] -= 1
                if self.cooldown[sym] <= 0:
                    del self.cooldown[sym]

            for sym in list(self.open_trades.keys()):
                if sym in all_data:
                    try:
                        bar = all_data[sym].loc[t]
                        self._manage_trade(sym, bar, t)
                    except KeyError:
                        pass

            if bar_counter % scan_every_n != 0:
                continue

            # [D14 FIX] Check regime on every scan to match live trader
            if bar_counter % scan_every_n == 0:
                self._detect_regime_at_bar(all_data, htf_data, t)
                
                # Dynamic Symbol Re-ranking
                if dynamic_top:
                    symbol_volumes = []
                    for sym, df in all_data.items():
                        try:
                            idx = df.index.get_loc(t)
                            if isinstance(idx, slice):
                                idx = idx.stop - 1
                            # Look back 96 bars (24 hours) for volume
                            start_idx = max(0, idx - 96)
                            vol = df.iloc[start_idx:idx+1]["volume"].sum()
                            symbol_volumes.append((sym, vol))
                        except KeyError:
                            continue
                    
                    symbol_volumes.sort(key=lambda x: x[1], reverse=True)
                    self.active_symbols = [s for s, _ in symbol_volumes[:top_n]]

            # [D13 FIX] Drawdown halt disabled to match live trader behavior
            # Live trader.py says: "Prop Firm Safety is DISABLED. Continuing trade scan..."
            # self._check_drawdown_halt(t)
            # if self.trading_halted:
            #     self.equity_curve.append({"time": t, "balance": self.balance, "open": len(self.open_trades)})
            #     continue

            p = self.active_personality
            if len(self.open_trades) >= min(self.max_open, p.max_open_trades):
                continue

            # [M6 FIX] Margin utilization cap removed — live trader does NOT have this check
            # used_margin = sum([(tr["qty"] * tr["entry_price"]) / self.leverage for tr in self.open_trades.values()])
            # if used_margin >= self.balance * 0.95:
            #     continue

            # Sync scan limit with active personality (Matches live trader.py)
            current_scan_symbols = self.active_symbols[:p.scan_limit]
            for sym in current_scan_symbols:
                df = all_data[sym]
                if sym in self.open_trades:
                    continue
                if sym in self.cooldown:
                    continue
                if len(self.open_trades) >= min(self.max_open, p.max_open_trades):
                    break

                try:
                    idx = df.index.get_loc(t)
                    if isinstance(idx, slice):
                        idx = idx.stop - 1
                except KeyError:
                    continue

                if idx < 200:
                    continue

                ind = df.iloc[:idx]

                if ind["atr_14"].iloc[-1] == 0 or np.isnan(ind["atr_14"].iloc[-1]):
                    continue

                last = ind.iloc[-1]
                atr_val = last["atr_14"]
                price = last["close"]
                # [D12 FIX] ATR/price volatility filter removed — live trader does NOT have this check
                # if price > 0 and atr_val / price > 0.05:
                #     continue

                open_list = list(self.open_trades.values())
                longs = [tr for tr in open_list if tr["direction"] == BUY]
                shorts = [tr for tr in open_list if tr["direction"] == SELL]

                htf_slice = None
                if sym in htf_data:
                    try:
                        import pandas as pd
                        htf_tf_mins = 240 # 4 hours
                        # Only use HTF candles that have fully closed at or before time t
                        closed_htf = htf_data[sym][htf_data[sym].index + pd.Timedelta(minutes=htf_tf_mins) <= t]
                        if not closed_htf.empty and len(closed_htf) >= 200:
                            htf_slice = closed_htf
                    except Exception:
                        pass

                sig = multi_strategy_scan(ind, htf_df=htf_slice, personality=p)
                if sig:
                    direction = sig["direction"]
                    
                    try:
                        from azalyst.config import LONG_ONLY_COINS, SHORT_ONLY_COINS
                        if direction == BUY and sym in SHORT_ONLY_COINS:
                            continue
                        if direction == SELL and sym in LONG_ONLY_COINS:
                            continue
                    except ImportError:
                        pass
                        
                    if direction == BUY and len(longs) >= p.max_same_direction:
                        continue
                    if direction == SELL and len(shorts) >= p.max_same_direction:
                        continue

                    # [M3 FIX] Alpha-X exposure cap (matches live trader)
                    if "alpha_x" in sig.get("strategies", []):
                        alpha_count = sum(1 for tr in self.open_trades.values() if tr.get("is_alpha"))
                        if alpha_count >= 7:
                            continue

                    self._open_trade(sym, ind.iloc[-1], sig, t)

            self.equity_curve.append({"time": t, "balance": self.balance, "open": len(self.open_trades)})

        for sym in list(self.open_trades.keys()):
            if sym in all_data and len(all_data[sym]) > 0:
                last = all_data[sym].iloc[-1]
                self._close_trade(sym, last["close"], "BACKTEST_END", all_data[sym].index[-1])

        elapsed = time.time() - t0
        print(f"\n  Backtest completed in {elapsed:.1f}s")
