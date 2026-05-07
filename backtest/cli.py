from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from azalyst.config import (
    LEVERAGE, RISK_PER_TRADE, ATR_MULT, TP_RR_RATIO,
    SL_MIN_PCT, SL_MAX_PCT, MAX_OPEN_TRADES, MAX_HOLD_SCANS,
    BREAKEVEN_AFTER_SCANS, MAX_SAME_DIRECTION, GOLD_COINS,
    REGIME_BTC_SYMBOL
)
from backtest.data import DataProvider
from backtest.engine import BacktestEngine
from backtest.report import generate_report, print_report, save_trades_csv


def _build_config() -> dict:
    return {
        "initial_balance": 100,
        "leverage": LEVERAGE,
        "risk_per_trade": RISK_PER_TRADE,
        "atr_mult": ATR_MULT,
        "tp_rr_ratio": TP_RR_RATIO,
        "sl_min_pct": SL_MIN_PCT,
        "sl_max_pct": SL_MAX_PCT,
        "max_open_trades": MAX_OPEN_TRADES,
        "max_hold_scans": MAX_HOLD_SCANS,
        "breakeven_scans": BREAKEVEN_AFTER_SCANS,
        "max_same_direction": MAX_SAME_DIRECTION,
    }


def main():
    parser = argparse.ArgumentParser(description="Azalyst Alpha X - Industrial Backtester")
    parser.add_argument("--start-date", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD, default: today)")
    parser.add_argument("--top-coins", type=int, default=25, help="Number of top coins (default: 25)")
    parser.add_argument("--dynamic-top", action="store_true", help="Enable dynamic symbol selection during backtest")
    parser.add_argument("--gold-list", action="store_true", help="Use the hardcoded Gold List of 30 high-quality coins")
    parser.add_argument("--scan-bars", type=int, default=2, help="Scan every N bars (default: 2)")
    parser.add_argument("--no-regime", action="store_true", help="Disable regime adaptation")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cached data and exit")
    parser.add_argument("--optimize", action="store_true", help="Compare regime vs no-regime")
    args = parser.parse_args()

    if args.clear_cache:
        DataProvider.clear_cache()
        return

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end_date = datetime.now(timezone.utc)

    print("=" * 80)
    print("  AZALYST ALPHA X - INDUSTRIAL BACKTESTER")
    print("=" * 80)
    print(f"  Period: {args.start_date} to {end_date.strftime('%Y-%m-%d')}")
    print(f"  Top Coins: {args.top_coins}")
    print(f"  Regime: {'ENABLED' if not args.no_regime else 'DISABLED'}")
    print("=" * 80)

    provider = DataProvider()
    
    if args.gold_list:
        print("  [GOLD LIST MODE] Using hardcoded list of high-quality coins.")
        symbols = GOLD_COINS
    else:
        # If top_coins is 0, fetch ALL symbols. Otherwise, if dynamic_top is enabled, fetch 100.
        if args.top_coins == 0:
            fetch_count = 0
        else:
            fetch_count = 100 if args.dynamic_top else args.top_coins
        symbols = provider.get_top_symbols(n=fetch_count)
    
    # ALWAYS ensure BTC is in symbols for regime detection, even if not in Gold List
    if REGIME_BTC_SYMBOL not in symbols:
        symbols = list(symbols) + [REGIME_BTC_SYMBOL]
        
    all_data, htf_data = provider.prepare_backtest_data(symbols, start_date, end_date)

    config = _build_config()

    if not args.optimize:
        use_regime = not args.no_regime
        label = "REGIME-ADAPTIVE" if use_regime else "STATIC (NO REGIME)"
        engine = BacktestEngine(config, use_regime=use_regime)
        # Pass dynamic settings to run
        engine.run(all_data, htf_data, start_date, end_date, 
                   scan_every_n=args.scan_bars, 
                   dynamic_top=args.dynamic_top,
                   top_n=args.top_coins,
                   trade_symbols=symbols) # 'symbols' is the original list before BTC was added
        report = generate_report(engine)
        print_report(report, label)
        save_trades_csv(report, label)
    else:
        results = {}

        print("\n  [1/2] Running REGIME-ADAPTIVE backtest...")
        engine_regime = BacktestEngine(config, use_regime=True)
        engine_regime.run(all_data, htf_data, start_date, end_date, 
                          scan_every_n=args.scan_bars, 
                          dynamic_top=args.dynamic_top,
                          top_n=args.top_coins)
        report_regime = generate_report(engine_regime)
        results["REGIME-ADAPTIVE"] = report_regime
        print_report(report_regime, "REGIME-ADAPTIVE")
        save_trades_csv(report_regime, "regime-adaptive")

        print("\n  [2/2] Running STATIC (NO REGIME) backtest...")
        engine_static = BacktestEngine(config, use_regime=False)
        engine_static.run(all_data, htf_data, start_date, end_date, 
                          scan_every_n=args.scan_bars, 
                          dynamic_top=args.dynamic_top,
                          top_n=args.top_coins)
        report_static = generate_report(engine_static)
        results["STATIC"] = report_static
        print_report(report_static, "STATIC (NO REGIME)")
        save_trades_csv(report_static, "static")

        print("\n" + "=" * 80)
        print("  COMPARISON: REGIME vs STATIC")
        print("=" * 80)
        print(f"  {'Config':<25} {'Trades':>7} {'Win%':>6} {'PnL':>10} {'PF':>6} {'MaxDD':>7} {'Return':>8}")
        print(f"  {'-'*25} {'-'*7} {'-'*6} {'-'*10} {'-'*6} {'-'*7} {'-'*8}")
        for label, r in results.items():
            if "error" in r:
                print(f"  {label:<25} {'NO TRADES':>7}")
                continue
            print(
                f"  {label:<25} {r['total_trades']:>7} {r['win_rate']:>5.1f}% "
                f"${r['total_pnl']:>+9.2f} {r['profit_factor']:>5.2f} "
                f"{r['max_drawdown_pct']:>6.1f}% {r['return_pct']:>+7.1f}%"
            )
        print("=" * 80)


if __name__ == "__main__":
    main()
