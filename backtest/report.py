from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

from azalyst.config import BUY


def generate_report(engine) -> dict:
    trades = engine.closed_trades
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
    peak = engine.initial_balance
    running = engine.initial_balance
    for t in trades:
        running += t["pnl_usd"]
        peak = max(peak, running)
        dd = (peak - running) / peak * 100
        max_dd = max(max_dd, dd)

    strat_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0})
    for t in trades:
        for s in t.get("strategies", []):
            strat_stats[s]["count"] += 1
            strat_stats[s]["pnl"] += t["pnl_usd"]
            if t["pnl_usd"] > 0:
                strat_stats[s]["wins"] += 1
            else:
                strat_stats[s]["losses"] += 1

    reason_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for t in trades:
        r = t["reason"]
        reason_stats[r]["count"] += 1
        reason_stats[r]["pnl"] += t["pnl_usd"]

    monthly_stats = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        et = t.get("exit_time")
        if et is not None:
            month_key = str(et)[:7]
            monthly_stats[month_key]["trades"] += 1
            monthly_stats[month_key]["pnl"] += t["pnl_usd"]
            if t["pnl_usd"] > 0:
                monthly_stats[month_key]["wins"] += 1

    regime_stats = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        reg = t.get("regime", "unknown")
        regime_stats[reg]["trades"] += 1
        regime_stats[reg]["pnl"] += t["pnl_usd"]
        if t["pnl_usd"] > 0:
            regime_stats[reg]["wins"] += 1

    return {
        "total_trades": len(trades),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(float(avg_win), 2),
        "avg_loss": round(float(avg_loss), 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "final_balance": round(engine.balance, 2),
        "return_pct": round((engine.balance - engine.initial_balance) / engine.initial_balance * 100, 2),
        "strategy_breakdown": dict(strat_stats),
        "reason_breakdown": dict(reason_stats),
        "monthly_breakdown": dict(monthly_stats),
        "regime_breakdown": dict(regime_stats),
        "regime_shifts": engine.regime_log,
        "trades": trades,
    }


def print_report(report: dict, label: str = "DEFAULT"):
    print("\n" + "=" * 80)
    print(f"  BACKTEST RESULTS - {label}")
    print("=" * 80)

    if "error" in report:
        print(f"  [ERROR] {report['error']}")
        return

    tag = "[WIN]" if report["total_pnl"] >= 0 else "[LOSS]"

    print(f"  Total Trades:    {report['total_trades']}")
    print(f"  Winners:         {report['winners']}")
    print(f"  Losers:          {report['losers']}")
    print(f"  Win Rate:        {report['win_rate']}%")
    print(f"  {tag} Total P&L:  ${report['total_pnl']}")
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
        tag = "[OK]" if s["pnl"] > 0 else "[X]"
        print(f"  {tag} {name:<15} {s['count']:>7} {s['wins']:>6} {s['losses']:>7} ${s['pnl']:>+9.2f} {wr:>6.1f}%")

    print("\n  -- Exit Reason Breakdown --")
    reasons = report.get("reason_breakdown", {})
    sorted_reasons = sorted(reasons.items(), key=lambda x: x[1]["count"], reverse=True)
    for r, s in sorted_reasons:
        tag = "[OK]" if s["pnl"] > 0 else "[X]"
        print(f"  {tag} {r:<20} {s['count']:>4} trades   ${s['pnl']:>+9.2f}")

    print("\n  -- Monthly Breakdown --")
    monthly = report.get("monthly_breakdown", {})
    for month, s in sorted(monthly.items()):
        wr = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0
        tag = "[OK]" if s["pnl"] > 0 else "[X]"
        print(f"  {tag} {month}   {s['trades']:>4} trades   ${s['pnl']:>+9.2f}   WR: {wr:.1f}%")

    print("\n  -- Regime Breakdown --")
    regime = report.get("regime_breakdown", {})
    for reg, s in sorted(regime.items()):
        wr = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0
        tag = "[OK]" if s["pnl"] > 0 else "[X]"
        print(f"  {tag} {reg:<20} {s['trades']:>4} trades   ${s['pnl']:>+9.2f}   WR: {wr:.1f}%")

    shifts = report.get("regime_shifts", [])
    if shifts:
        print(f"\n  -- Regime Shifts ({len(shifts)} total) --")
        for s in shifts[:10]:
            print(f"  {str(s['time'])[:19]}  {s['from']} -> {s['to']}  [{s['personality']}]")
        if len(shifts) > 10:
            print(f"  ... and {len(shifts) - 10} more")

    print("=" * 80)


def save_trades_csv(report: dict, label: str = "default"):
    trades = report.get("trades", [])
    if not trades:
        return

    safe_label = label.replace(" ", "_").replace("(", "").replace(")", "").replace(",", "").lower()
    filename = f"backtest_trades_{safe_label}.csv"

    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Symbol", "Direction", "Entry Time", "Exit Time", "Entry Price",
                "Exit Price", "SL Dist %", "PnL %", "PnL $", "Reason",
                "Strategies", "Regime", "Personality",
            ])
            for t in trades:
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
                    t.get("regime", ""),
                    t.get("personality", ""),
                ])
        print(f"  Trades saved to {filename}")
    except Exception as e:
        print(f"  Failed to save CSV: {e}")
