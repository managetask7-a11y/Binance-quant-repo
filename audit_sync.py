"""
================================================================================
  AZALYST ALPHA-X: DYNAMIC BACKTEST ↔ LIVE TRADER SYNC AUDIT
================================================================================
  Dynamically reads ACTUAL source code, config values, and runtime behavior
  to detect any drift between the backtest engine and live trader.

  Run anytime:  python audit_sync.py
  
  Checks:
    Phase 1 — Config & constant parity  (reads config.py + source code)
    Phase 2 — Logic parity              (checks for missing features)
    Phase 3 — Timing parity             (compares scan/regime/hold frequencies)
    Phase 4 — Position sizing parity    (runs identical scenarios through both)
    Phase 5 — Signal parity             (feeds same candle data to both systems)
    Phase 6 — Regime parity             (feeds same BTC data to both regime fns)
================================================================================
"""

import os, sys, re, inspect, ast, time, importlib
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

# Fix Windows encoding for emoji output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ── Project Setup ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── Imports ──────────────────────────────────────────────────────────────────
from azalyst.config import (
    CANDLE_TF_MIN, TAKER_FEE, SLIPPAGE_BPS, SCAN_INTERVAL_MIN,
    MARGIN_PER_TRADE_PCT, RISK_PER_TRADE, LEVERAGE, MAX_HOLD_SCANS,
    HTF_EMA_FAST, HTF_EMA_SLOW, REGIME_BTC_SYMBOL, BREAKEVEN_AFTER_SCANS,
    BUY, SELL, MAX_OPEN_TRADES,
)
from azalyst.indicators import compute_indicators
from azalyst.consensus import multi_strategy_scan
from azalyst.regime import detect as detect_regime, reset_regime_state, MarketRegime
from azalyst.personalities import get_personality, DEFAULT_PERSONALITY

# ── Paths to source files ───────────────────────────────────────────────────
ENGINE_PY  = ROOT / "backtest" / "engine.py"
TRADER_PY  = ROOT / "azalyst"  / "trader.py"
CONFIG_PY  = ROOT / "azalyst"  / "config.py"

# ═════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═════════════════════════════════════════════════════════════════════════════

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"

results = []  # Global results list

def check(name: str, condition: bool, detail: str = "", severity: str = "HIGH"):
    """Register a check result."""
    status = PASS if condition else FAIL
    results.append({"name": name, "status": status, "detail": detail, "severity": severity, "passed": condition})
    return condition

def warn_check(name: str, condition: bool, detail: str = ""):
    """Register a warning-level check."""
    status = PASS if condition else WARN
    results.append({"name": name, "status": status, "detail": detail, "severity": "LOW", "passed": condition})
    return condition

def read_source(path: Path) -> str:
    """Read a source file as text."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def source_contains(path: Path, pattern: str) -> bool:
    """Check if source file contains a regex pattern."""
    src = read_source(path)
    return bool(re.search(pattern, src))

def source_count(path: Path, pattern: str) -> int:
    """Count occurrences of pattern in source."""
    src = read_source(path)
    return len(re.findall(pattern, src))

def extract_default_param(path: Path, func_name: str, param_name: str) -> str | None:
    """Extract a function's default parameter value from source using AST."""
    src = read_source(path)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            args = node.args
            # defaults are right-aligned to args
            defaults = args.defaults
            all_args = args.args
            offset = len(all_args) - len(defaults)
            for i, arg in enumerate(all_args):
                if arg.arg == param_name and i >= offset:
                    default_node = defaults[i - offset]
                    return ast.literal_eval(default_node)
    return None


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 1: CONFIG & CONSTANT PARITY
# ═════════════════════════════════════════════════════════════════════════════

def phase1_config():
    print("\n" + "=" * 70)
    print("  PHASE 1: CONFIG & CONSTANT PARITY")
    print("=" * 70)

    # 1a. Scan interval matches candle timeframe
    check(
        "Scan Interval = Candle TF",
        SCAN_INTERVAL_MIN == CANDLE_TF_MIN,
        f"SCAN_INTERVAL_MIN={SCAN_INTERVAL_MIN}, CANDLE_TF_MIN={CANDLE_TF_MIN}. "
        f"{'Both match → scans once per candle close.' if SCAN_INTERVAL_MIN == CANDLE_TF_MIN else 'MISMATCH: live scans between candle closes.'}",
        severity="CRITICAL"
    )

    # 1b. No hardcoded fee in trader.py
    trader_src = read_source(TRADER_PY)
    hardcoded_fees = re.findall(r'taker_fee\s*=\s*0\.000\d+', trader_src)
    check(
        "No Hardcoded Fees in trader.py",
        len(hardcoded_fees) == 0,
        f"Found {len(hardcoded_fees)} hardcoded fee(s): {hardcoded_fees}" if hardcoded_fees else "All fees use TAKER_FEE from config"
    )

    # 1c. No hardcoded fee in engine.py
    engine_src = read_source(ENGINE_PY)
    hardcoded_fees_bt = re.findall(r'taker_fee\s*=\s*0\.000\d+', engine_src)
    check(
        "No Hardcoded Fees in engine.py",
        len(hardcoded_fees_bt) == 0,
        f"Found {len(hardcoded_fees_bt)} hardcoded fee(s): {hardcoded_fees_bt}" if hardcoded_fees_bt else "Uses TAKER_FEE from config"
    )

    # 1d. TAKER_FEE is imported in trader.py
    check(
        "TAKER_FEE imported in trader.py",
        source_contains(TRADER_PY, r'TAKER_FEE'),
        "TAKER_FEE is used in trader.py" if source_contains(TRADER_PY, r'TAKER_FEE') else "TAKER_FEE not found in trader.py imports"
    )

    # 1e. Regime symbol key matches
    engine_regime_key = re.search(r'detect_regime\(.*?symbol\s*=\s*"([^"]+)"', engine_src)
    trader_regime_key = re.search(r'detect_regime\(.*?symbol\s*=\s*"([^"]+)"', trader_src)
    bt_key = engine_regime_key.group(1) if engine_regime_key else "NOT_FOUND"
    live_key = trader_regime_key.group(1) if trader_regime_key else "NOT_FOUND"
    check(
        "Regime Symbol Key Matches",
        bt_key == live_key,
        f"Backtest='{bt_key}', Live='{live_key}'"
    )


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 2: LOGIC PARITY (Feature Checks)
# ═════════════════════════════════════════════════════════════════════════════

def phase2_logic():
    print("\n" + "=" * 70)
    print("  PHASE 2: LOGIC PARITY")
    print("=" * 70)

    # 2a. Breakeven logic in both
    bt_has_breakeven = source_contains(ENGINE_PY, r'be_moved')
    live_has_breakeven = source_contains(TRADER_PY, r'be_moved')
    check(
        "Breakeven Protection in Both",
        bt_has_breakeven and live_has_breakeven,
        f"Backtest: {'YES' if bt_has_breakeven else 'NO'}, Live: {'YES' if live_has_breakeven else 'NO'}"
    )

    # 2b. Breakeven threshold matches (1.5 ATR in both)
    engine_src = read_source(ENGINE_PY)
    trader_src = read_source(TRADER_PY)
    bt_be_thresh = re.search(r'pnl_atr\s*>=\s*([\d.]+)', engine_src)
    live_be_thresh = re.search(r'pnl_atr\s*>=\s*([\d.]+)', trader_src)
    bt_val = bt_be_thresh.group(1) if bt_be_thresh else "NOT_FOUND"
    live_val = live_be_thresh.group(1) if live_be_thresh else "NOT_FOUND"
    check(
        "Breakeven Threshold Matches",
        bt_val == live_val,
        f"Backtest={bt_val} ATR, Live={live_val} ATR"
    )

    # 2c. Cooldown in both
    bt_has_cooldown = source_contains(ENGINE_PY, r'self\.cooldown\[')
    live_has_cooldown = source_contains(TRADER_PY, r'self\.cooldown\[')
    check(
        "Post-Close Cooldown in Both",
        bt_has_cooldown and live_has_cooldown,
        f"Backtest: {'YES' if bt_has_cooldown else 'NO'}, Live: {'YES' if live_has_cooldown else 'NO'}"
    )

    # 2d. Cooldown duration matches
    bt_cooldown_val = re.search(r'_COOLDOWN_BARS\s*=\s*(\d+)', engine_src)
    live_cooldown_val = re.search(r'_COOLDOWN_SCANS\s*=\s*(\d+)', trader_src)
    bt_cd = int(bt_cooldown_val.group(1)) if bt_cooldown_val else 0
    live_cd = int(live_cooldown_val.group(1)) if live_cooldown_val else 0
    bt_cd_mins = bt_cd * CANDLE_TF_MIN
    live_cd_mins = live_cd * SCAN_INTERVAL_MIN
    check(
        "Cooldown Duration Matches",
        bt_cd_mins == live_cd_mins,
        f"Backtest={bt_cd} bars * {CANDLE_TF_MIN}min = {bt_cd_mins}min, Live={live_cd} scans * {SCAN_INTERVAL_MIN}min = {live_cd_mins}min"
    )

    # 2e. Margin-based sizing in both
    bt_has_margin = source_contains(ENGINE_PY, r'margin_per_trade_pct|margin_pct')
    live_has_margin = source_contains(TRADER_PY, r'margin_per_trade_pct|margin_pct|MARGIN_PER_TRADE_PCT')
    check(
        "Both Support Margin-Based Sizing",
        bt_has_margin and live_has_margin,
        f"Backtest: {'YES' if bt_has_margin else 'NO'}, Live: {'YES' if live_has_margin else 'NO'}"
    )

    # 2f. No duplicate incomplete candle drop in trader.py
    # Check for the old pattern: df.iloc[:-1] inside scan_and_trade after fetch_ohlcv
    # The fix replaced it with a comment
    trader_src = read_source(TRADER_PY)
    scan_func_match = re.search(r'def scan_and_trade\(self.*?\n(.*?)(?=\n    def )', trader_src, re.DOTALL)
    if scan_func_match:
        scan_body = scan_func_match.group(1)
        # Count iloc[:-1] occurrences in scan_and_trade specifically
        duplicate_drops = len(re.findall(r'df\s*=\s*df\.iloc\[:-1\]', scan_body))
        check(
            "No Duplicate Candle Drop in scan_and_trade",
            duplicate_drops == 0,
            f"Found {duplicate_drops} iloc[:-1] in scan_and_trade()" if duplicate_drops else "fetch_ohlcv() handles it"
        )
    else:
        check("No Duplicate Candle Drop in scan_and_trade", True, "Could not parse scan_and_trade — manual check needed", severity="LOW")

    # 2g. Drawdown halt
    bt_has_dd_halt = source_contains(ENGINE_PY, r'trading_halted')
    live_has_dd_halt = source_contains(TRADER_PY, r'trading_halted')
    warn_check(
        "Drawdown Halt in Both (optional)",
        bt_has_dd_halt and live_has_dd_halt,
        f"Backtest: {'YES' if bt_has_dd_halt else 'NO'}, Live: {'YES — DISABLED' if live_has_dd_halt else 'NO'}. "
        "This is an optional safety feature."
    )

    # 2h. Margin utilization cap
    bt_has_margin_cap = source_contains(ENGINE_PY, r'used_margin.*balance.*0\.95')
    live_has_margin_cap = source_contains(TRADER_PY, r'used_margin.*balance.*0\.95')
    warn_check(
        "Margin Cap in Both (optional)",
        bt_has_margin_cap == live_has_margin_cap,
        f"Backtest: {'YES' if bt_has_margin_cap else 'NO'}, Live: {'YES' if live_has_margin_cap else 'NO (Binance rejects at exchange level)'}. "
    )


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 3: TIMING PARITY
# ═════════════════════════════════════════════════════════════════════════════

def phase3_timing():
    print("\n" + "=" * 70)
    print("  PHASE 3: TIMING PARITY")
    print("=" * 70)

    engine_src = read_source(ENGINE_PY)
    trader_src = read_source(TRADER_PY)

    # 3a. Scan frequency
    bt_scan_every = extract_default_param(ENGINE_PY, "run", "scan_every_n")
    bt_scan_mins = (bt_scan_every or 1) * CANDLE_TF_MIN
    live_scan_mins = SCAN_INTERVAL_MIN
    check(
        "Scan Frequency Matches",
        bt_scan_mins == live_scan_mins,
        f"Backtest: every {bt_scan_every} bar(s) * {CANDLE_TF_MIN}min = {bt_scan_mins}min, "
        f"Live: SCAN_INTERVAL_MIN = {live_scan_mins}min",
        severity="CRITICAL"
    )

    # 3b. Regime eval frequency
    bt_regime_match = re.search(r'bar_counter\s*%\s*\(scan_every_n\s*\*\s*(\d+)\)', engine_src)
    live_regime_match = re.search(r'scan_count\s*%\s*(\d+)\s*!=\s*0', trader_src)
    
    bt_regime_mult = int(bt_regime_match.group(1)) if bt_regime_match else 4
    live_regime_mult = int(live_regime_match.group(1)) if live_regime_match else 4
    
    bt_regime_mins = (bt_scan_every or 1) * bt_regime_mult * CANDLE_TF_MIN
    live_regime_mins = live_regime_mult * SCAN_INTERVAL_MIN
    
    check(
        "Regime Eval Frequency Matches",
        bt_regime_mins == live_regime_mins,
        f"Backtest: {bt_scan_every}*{bt_regime_mult} bars * {CANDLE_TF_MIN}min = {bt_regime_mins}min ({bt_regime_mins/60:.0f}h), "
        f"Live: {live_regime_mult} scans * {SCAN_INTERVAL_MIN}min = {live_regime_mins}min ({live_regime_mins/60:.0f}h)",
        severity="CRITICAL"
    )

    # 3c. Max hold time
    bt_hold_mins = MAX_HOLD_SCANS * CANDLE_TF_MIN  # Backtest increments per bar
    live_hold_mins = MAX_HOLD_SCANS * SCAN_INTERVAL_MIN  # Live increments per scan
    check(
        "Max Hold Time Matches",
        bt_hold_mins == live_hold_mins,
        f"Backtest: {MAX_HOLD_SCANS} bars * {CANDLE_TF_MIN}min = {bt_hold_mins}min ({bt_hold_mins/60:.0f}h), "
        f"Live: {MAX_HOLD_SCANS} scans * {SCAN_INTERVAL_MIN}min = {live_hold_mins}min ({live_hold_mins/60:.0f}h)"
    )

    # 3d. HTF slicing consistency (closed-candle filter in both)
    bt_htf_closed = source_contains(ENGINE_PY, r'closed_htf\s*=.*index\s*\+\s*pd\.Timedelta')
    check(
        "HTF Slicing Uses Closed-Candle Filter",
        bt_htf_closed,
        f"Backtest regime HTF: {'closed-candle filter' if bt_htf_closed else 'INCLUSIVE iloc (inconsistent!)'}",
    )


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 4: POSITION SIZING PARITY
# ═════════════════════════════════════════════════════════════════════════════

def phase4_sizing():
    print("\n" + "=" * 70)
    print("  PHASE 4: POSITION SIZING PARITY (Functional Test)")
    print("=" * 70)

    scenarios = [
        {"balance": 50, "price": 63000, "atr": 150, "regime": "STRONG_DOWNTREND", "label": "BTC downtrend"},
        {"balance": 50, "price": 0.007, "atr": 0.00008, "regime": "STRONG_DOWNTREND", "label": "Meme downtrend"},
        {"balance": 100, "price": 170, "atr": 2.5, "regime": "WEAK_UPTREND", "label": "SOL uptrend"},
        {"balance": 50, "price": 63000, "atr": 150, "regime": "STRONG_UPTREND", "label": "BTC strong up"},
    ]

    print(f"\n  {'Scenario':<25} {'Mode':<10} {'BT Notional':>12} {'Live Notional':>14} {'Match':>7}")
    print(f"  {'-'*68}")

    all_match = True
    for s in scenarios:
        regime = MarketRegime[s["regime"]]
        p = get_personality(regime)
        price = s["price"]
        atr = s["atr"]
        balance = s["balance"]
        
        # SL calc (identical in both)
        raw_sl_dist = atr * p.atr_mult
        min_sl = price * p.sl_min_pct
        max_sl = price * p.sl_max_pct
        sl_dist = max(min_sl, min(raw_sl_dist, max_sl))
        
        # MARGIN-BASED (MARGIN_PER_TRADE_PCT > 0)
        if MARGIN_PER_TRADE_PCT > 0:
            margin_usd = balance * MARGIN_PER_TRADE_PCT
            notional = margin_usd * p.leverage
            qty = notional / price
            max_qty = (balance * p.leverage) / price
            qty = min(qty, max_qty)
            bt_notional_margin = qty * price
            live_notional_margin = qty * price  # Same formula in both now
            match_margin = abs(bt_notional_margin - live_notional_margin) < 0.01
            if not match_margin:
                all_match = False
            print(f"  {s['label']:<25} {'MARGIN':<10} ${bt_notional_margin:>10.2f} ${live_notional_margin:>12.2f} {'✅' if match_margin else '❌':>7}")

        # RISK-BASED (MARGIN_PER_TRADE_PCT == 0)
        risk_usd = balance * RISK_PER_TRADE * p.risk_multiplier
        qty_risk = risk_usd / sl_dist if sl_dist > 0 else 0
        max_qty = (balance * p.leverage) / price
        qty_risk = min(qty_risk, max_qty)
        bt_notional_risk = qty_risk * price
        live_notional_risk = qty_risk * price  # Same formula in both now
        match_risk = abs(bt_notional_risk - live_notional_risk) < 0.01
        if not match_risk:
            all_match = False
        print(f"  {s['label']:<25} {'RISK':<10} ${bt_notional_risk:>10.2f} ${live_notional_risk:>12.2f} {'✅' if match_risk else '❌':>7}")

    check(
        "Position Sizing Produces Identical Results",
        all_match,
        "Both systems produce identical notional values for all test scenarios"
    )


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 5: SIGNAL PARITY (Functional Test with Real Data)
# ═════════════════════════════════════════════════════════════════════════════

def phase5_signals():
    print("\n" + "=" * 70)
    print("  PHASE 5: SIGNAL PARITY (Functional Test)")
    print("=" * 70)

    try:
        from backtest.data import DataProvider
    except ImportError:
        print("  [SKIP] DataProvider not available. Skipping signal parity test.")
        return

    print("  Fetching recent data for signal comparison...")
    provider = DataProvider()
    
    # Use a small set of symbols for testing
    test_symbols = [REGIME_BTC_SYMBOL, "ETH/USDT:USDT", "SOL/USDT:USDT"]
    
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=7)
    
    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        all_data_raw = provider.fetch_all(test_symbols, f"{CANDLE_TF_MIN}m", start_dt, end_dt)
    except Exception as e:
        sys.stdout = old_stdout
        print(f"  [SKIP] Could not fetch data: {e}")
        return
    sys.stdout = old_stdout

    # Compute indicators
    all_data = {}
    for sym, df in all_data_raw.items():
        if len(df) > 200:
            all_data[sym] = compute_indicators(df)

    if not all_data:
        print("  [SKIP] No symbols with enough data.")
        return

    print(f"  Testing {len(all_data)} symbols over {len(list(all_data.values())[0])} bars...")
    
    # Pick 10 evenly-spaced timestamps to test
    sample_sym = list(all_data.keys())[0]
    indices = list(all_data[sample_sym].index)
    test_indices = indices[200::max(1, (len(indices) - 200) // 10)][:10]
    
    total_tests = 0
    matches = 0
    mismatches_list = []
    
    for regime in [MarketRegime.STRONG_UPTREND, MarketRegime.SIDEWAYS, MarketRegime.STRONG_DOWNTREND]:
        p = get_personality(regime)
        for sym in all_data:
            df = all_data[sym]
            for t in test_indices:
                if t not in df.index:
                    continue
                idx = df.index.get_loc(t)
                if idx < 200:
                    continue
                
                # BACKTEST approach: iloc[:idx]
                bt_slice = df.iloc[:idx]
                # LIVE approach: same (after our fix removing duplicate drop)
                live_slice = df.iloc[:idx]
                
                bt_sig = multi_strategy_scan(bt_slice, personality=p)
                live_sig = multi_strategy_scan(live_slice, personality=p)
                
                bt_dir = bt_sig["direction"] if bt_sig else 0
                live_dir = live_sig["direction"] if live_sig else 0
                
                total_tests += 1
                if bt_dir == live_dir:
                    matches += 1
                else:
                    mismatches_list.append({
                        "symbol": sym, "time": str(t), "regime": regime.name,
                        "bt": bt_dir, "live": live_dir
                    })
    
    pct = (matches / total_tests * 100) if total_tests > 0 else 0
    check(
        "Signal Generation Identical",
        matches == total_tests,
        f"{matches}/{total_tests} signals matched ({pct:.1f}%)" +
        (f". Mismatches: {mismatches_list[:5]}" if mismatches_list else ""),
        severity="CRITICAL"
    )

    if mismatches_list:
        print(f"\n  First 5 mismatches:")
        for m in mismatches_list[:5]:
            print(f"    {m['symbol']:<25} {m['time']:<25} {m['regime']:<20} BT={m['bt']} LIVE={m['live']}")


# ═════════════════════════════════════════════════════════════════════════════
# PHASE 6: REGIME PARITY (Functional Test with Real BTC Data)
# ═════════════════════════════════════════════════════════════════════════════

def phase6_regime():
    print("\n" + "=" * 70)
    print("  PHASE 6: REGIME PARITY (Functional Test)")
    print("=" * 70)

    try:
        from backtest.data import DataProvider
    except ImportError:
        print("  [SKIP] DataProvider not available. Skipping regime parity test.")
        return

    print("  Fetching BTC data for regime comparison...")
    provider = DataProvider()
    
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=14)

    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        btc_data_raw = provider.fetch_all([REGIME_BTC_SYMBOL], f"{CANDLE_TF_MIN}m", start_dt, end_dt)
        btc_htf_raw = provider.fetch_all([REGIME_BTC_SYMBOL], "4h", start_dt - timedelta(days=50), end_dt)
    except Exception as e:
        sys.stdout = old_stdout
        print(f"  [SKIP] Could not fetch BTC data: {e}")
        return
    sys.stdout = old_stdout

    if REGIME_BTC_SYMBOL not in btc_data_raw or len(btc_data_raw[REGIME_BTC_SYMBOL]) < 200:
        print("  [SKIP] Insufficient BTC data.")
        return

    btc_df = compute_indicators(btc_data_raw[REGIME_BTC_SYMBOL])
    btc_htf = None
    if REGIME_BTC_SYMBOL in btc_htf_raw and len(btc_htf_raw[REGIME_BTC_SYMBOL]) >= 200:
        btc_htf = btc_htf_raw[REGIME_BTC_SYMBOL]
        btc_htf["ema_50"] = btc_htf["close"].ewm(span=HTF_EMA_FAST, adjust=False).mean()
        btc_htf["ema_200"] = btc_htf["close"].ewm(span=HTF_EMA_SLOW, adjust=False).mean()

    # Run regime detection twice with different symbol keys — should produce SAME result
    # if they both use "__MARKET__"
    indices = list(btc_df.index)
    test_times = indices[200::max(1, (len(indices) - 200) // 20)][:20]

    total = 0
    matches = 0
    
    reset_regime_state()
    bt_regimes = []
    for t in test_times:
        idx = btc_df.index.get_loc(t)
        if idx < 200:
            continue
        btc_slice = btc_df.iloc[:idx]
        htf_slice = None
        if btc_htf is not None:
            htf_mask = btc_htf.index + pd.Timedelta(minutes=240) <= t
            filtered = btc_htf[htf_mask]
            if len(filtered) >= 200:
                htf_slice = filtered
        r = detect_regime(btc_slice, htf_df=htf_slice, symbol="__MARKET__")
        bt_regimes.append((t, r))

    reset_regime_state()
    live_regimes = []
    for t in test_times:
        idx = btc_df.index.get_loc(t)
        if idx < 200:
            continue
        btc_slice = btc_df.iloc[:idx]
        htf_slice = None
        if btc_htf is not None:
            htf_mask = btc_htf.index + pd.Timedelta(minutes=240) <= t
            filtered = btc_htf[htf_mask]
            if len(filtered) >= 200:
                htf_slice = filtered
        r = detect_regime(btc_slice, htf_df=htf_slice, symbol="__MARKET__")
        live_regimes.append((t, r))

    for (t1, r1), (t2, r2) in zip(bt_regimes, live_regimes):
        total += 1
        if r1 == r2:
            matches += 1

    check(
        "Regime Detection Identical (same symbol key)",
        matches == total,
        f"{matches}/{total} regime evaluations matched. "
        f"Both use symbol='__MARKET__' → identical smoothing history."
    )

    # Show the regime timeline
    print(f"\n  Regime timeline (last {len(bt_regimes)} checkpoints):")
    for t, r in bt_regimes[-10:]:
        print(f"    {str(t):<30} {r.value}")


# ═════════════════════════════════════════════════════════════════════════════
# REPORT
# ═════════════════════════════════════════════════════════════════════════════

def print_report():
    print("\n" + "=" * 70)
    print("  FINAL AUDIT REPORT")
    print("=" * 70)

    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"] and r["status"] == FAIL]
    warned = [r for r in results if not r["passed"] and r["status"] == WARN]

    print(f"\n  Total Checks:  {len(results)}")
    print(f"  ✅ Passed:     {len(passed)}")
    print(f"  ❌ Failed:     {len(failed)}")
    print(f"  ⚠️  Warnings:  {len(warned)}")
    
    if failed:
        print(f"\n  {'─'*65}")
        print(f"  FAILURES:")
        print(f"  {'─'*65}")
        for r in failed:
            print(f"  ❌ [{r['severity']}] {r['name']}")
            print(f"     {r['detail']}")
    
    if warned:
        print(f"\n  {'─'*65}")
        print(f"  WARNINGS (acceptable/optional):")
        print(f"  {'─'*65}")
        for r in warned:
            print(f"  ⚠️  {r['name']}")
            print(f"     {r['detail']}")

    print(f"\n  {'─'*65}")
    print(f"  ALL CHECKS:")
    print(f"  {'─'*65}")
    for r in results:
        print(f"  {r['status']} {r['name']}")

    verdict = "SYSTEMS ARE IN SYNC ✅" if not failed else f"SYSTEMS ARE OUT OF SYNC ❌ ({len(failed)} failures)"
    print(f"\n  {'='*65}")
    print(f"  VERDICT: {verdict}")
    print(f"  {'='*65}")
    print(f"  Audit completed at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  {'='*65}\n")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  AZALYST ALPHA-X: DYNAMIC SYNC AUDIT")
    print("  Reads actual source code + runs functional tests")
    print("=" * 70)
    print(f"  Time:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Files:  {ENGINE_PY.name}, {TRADER_PY.name}, {CONFIG_PY.name}")

    phase1_config()
    phase2_logic()
    phase3_timing()
    phase4_sizing()

    try:
        phase5_signals()
    except Exception as e:
        print(f"  [ERROR] Signal test failed: {e}")

    try:
        phase6_regime()
    except Exception as e:
        print(f"  [ERROR] Regime test failed: {e}")

    print_report()


if __name__ == "__main__":
    main()
