"""Quick quantitative analysis of backtest_trades_regime-adaptive.csv"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np

df = pd.read_csv("backtest_trades_regime-adaptive.csv")
df["Entry Time"] = pd.to_datetime(df["Entry Time"], utc=True)
df["Exit Time"] = pd.to_datetime(df["Exit Time"], utc=True)
df["Hold_Hours"] = (df["Exit Time"] - df["Entry Time"]).dt.total_seconds() / 3600
df["Month"] = df["Entry Time"].dt.to_period("M")
# Clean numeric columns
df["PnL $"] = df["PnL $"].astype(str).str.replace("$","").str.replace(",","").str.strip().astype(float)
df["PnL %"] = df["PnL %"].astype(str).str.replace("%","").str.strip().astype(float)
df["SL_pct"] = df["SL Dist %"].astype(str).str.replace("%","").str.strip().astype(float)

print("="*80)
print("  DEEP QUANTITATIVE ANALYSIS")
print("="*80)

# 1. Expectancy
avg_win = df.loc[df["PnL $"]>0, "PnL $"].mean()
avg_loss = df.loc[df["PnL $"]<0, "PnL $"].mean()
wr = len(df[df["PnL $"]>0]) / len(df)
expectancy = wr * avg_win + (1-wr) * avg_loss
print(f"\n--- EXPECTANCY ---")
print(f"Win Rate: {wr:.1%}")
print(f"Avg Winner: ${avg_win:.2f}")
print(f"Avg Loser:  ${avg_loss:.2f}")
print(f"Avg Win / Avg Loss (R:R realized): {abs(avg_win/avg_loss):.2f}")
print(f"Expectancy per trade: ${expectancy:.2f}")

# 2. Distribution of wins/losses
print(f"\n--- PnL DISTRIBUTION ---")
for bucket in [(-100,-20), (-20,-10), (-10,-5), (-5, 0), (0,5), (5,10), (10,25), (25,50), (50,200)]:
    cnt = len(df[(df["PnL $"]>=bucket[0]) & (df["PnL $"]<bucket[1])])
    print(f"  ${bucket[0]:>6} to ${bucket[1]:>4}: {cnt:>3} trades")

# 3. Trailing stop realized RR
print(f"\n--- EXIT REASON ANALYSIS ---")
for reason in df["Reason"].unique():
    sub = df[df["Reason"]==reason]
    wins = len(sub[sub["PnL $"]>0])
    total = len(sub)
    net = sub["PnL $"].sum()
    avg = sub["PnL $"].mean()
    avg_pnl_pct = sub["PnL %"].mean()
    avg_hold = sub["Hold_Hours"].mean()
    print(f"  {reason:<20} | {total:>3} trades | WR: {wins/total:.0%} | Net: ${net:>8.2f} | Avg: ${avg:>7.2f} | Avg%: {avg_pnl_pct:>7.2f}% | Hold: {avg_hold:.1f}h")

# 4. Strategy-pair analysis
print(f"\n--- STRATEGY COMBO PERFORMANCE ---")
strat_combos = df.groupby("Strategies").agg(
    Trades=("PnL $","count"),
    Net=("PnL $","sum"),
    WR=("PnL $", lambda x: (x>0).sum()/len(x)*100),
    Avg=("PnL $","mean"),
).sort_values("Net", ascending=False)
for combo, row in strat_combos.iterrows():
    print(f"  {combo:<30} | {int(row['Trades']):>3} trades | Net: ${row['Net']:>8.2f} | WR: {row['WR']:.0f}% | Avg: ${row['Avg']:.2f}")

# 5. Regime analysis
print(f"\n--- REGIME DEEP ANALYSIS ---")
for regime in df["Regime"].unique():
    sub = df[df["Regime"]==regime]
    wins = len(sub[sub["PnL $"]>0])
    net = sub["PnL $"].sum()
    avg = sub["PnL $"].mean()
    avg_sl = sub["SL_pct"].mean()
    avg_hold = sub["Hold_Hours"].mean()
    # Biggest wins/losses
    biggest_win = sub["PnL $"].max()
    biggest_loss = sub["PnL $"].min()
    print(f"\n  {regime}")
    print(f"    Trades: {len(sub)} | WR: {wins/len(sub):.0%} | Net: ${net:.2f} | Avg: ${avg:.2f}")
    print(f"    Avg SL Dist: {avg_sl:.2f}% | Avg Hold: {avg_hold:.1f}h")
    print(f"    Biggest Win: ${biggest_win:.2f} | Biggest Loss: ${biggest_loss:.2f}")
    
    # By exit reason within regime
    for reason in sub["Reason"].unique():
        rsub = sub[sub["Reason"]==reason]
        print(f"      {reason:<20}: {len(rsub):>2} trades, ${rsub['PnL $'].sum():>8.2f}")

# 6. Trailing stop analysis - are winners cut early?
print(f"\n--- TRAILING STOP vs TAKE_PROFIT COMPARISON ---")
ts = df[df["Reason"]=="TRAILING_STOP"]
tp = df[df["Reason"]=="TAKE_PROFIT_1"]
print(f"  Trailing Stop: {len(ts)} trades, Avg PnL%: {ts['PnL %'].mean():.2f}%")
print(f"  Take Profit 1: {len(tp)} trades, Avg PnL%: {tp['PnL %'].mean():.2f}%")

# Trailing stop winners - how much further price went after exit
print(f"\n  Trailing Stop PnL$ distribution:")
for pct in [7.5, 10, 15, 25, 50, 100]:
    cnt = len(ts[ts["PnL %"] <= pct])
    print(f"    <= {pct}%: {cnt} trades")

# 7. Stop Loss analysis
print(f"\n--- STOP LOSS ANALYSIS ---")
sl = df[df["Reason"]=="STOP_LOSS"]
print(f"  Total SL hits: {len(sl)}")
print(f"  Avg SL PnL$: ${sl['PnL $'].mean():.2f}")
print(f"  Avg SL dist%: {sl['SL_pct'].mean():.2f}%")
print(f"  SL total damage: ${sl['PnL $'].sum():.2f}")
# Top 5 worst SL
print(f"  Top 10 Worst Stop Losses:")
for _, row in sl.nsmallest(10, "PnL $").iterrows():
    print(f"    {row['Symbol']:<25} ${row['PnL $']:>8.2f} | SL: {row['SL Dist %']} | {row['Regime']} | {row['Strategies']}")

# 8. Monthly analysis  
print(f"\n--- MONTHLY BREAKDOWN (DETAILED) ---")
for month in sorted(df["Month"].unique()):
    sub = df[df["Month"]==month]
    net = sub["PnL $"].sum()
    wins = len(sub[sub["PnL $"]>0])
    total = len(sub)
    biggest_loss = sub["PnL $"].min()
    biggest_win = sub["PnL $"].max()
    sl_hits = len(sub[sub["Reason"]=="STOP_LOSS"])
    symbol = "✅" if net > 0 else "❌"
    print(f"  {symbol} {month} | {total:>2} trades | WR: {wins/total:.0%} | Net: ${net:>8.2f} | SL: {sl_hits} | Best: ${biggest_win:.2f} | Worst: ${biggest_loss:.2f}")

# 9. Coins performance
print(f"\n--- COIN PERFORMANCE ---")
coin_perf = df.groupby("Symbol").agg(
    Trades=("PnL $","count"),
    Net=("PnL $","sum"),
    WR=("PnL $", lambda x: (x>0).sum()/len(x)*100),
    Avg=("PnL $","mean"),
    AvgSL=("SL_pct","mean"),
).sort_values("Net", ascending=False)
for coin, row in coin_perf.iterrows():
    sym = "✅" if row["Net"]>0 else "❌"
    print(f"  {sym} {coin:<25} | {int(row['Trades']):>2} trades | Net: ${row['Net']:>8.2f} | WR: {row['WR']:.0f}% | AvgSL: {row['AvgSL']:.2f}%")

# 10. Key stat: What % of total losses come from STOP_LOSS
total_loss = df[df["PnL $"]<0]["PnL $"].sum()
sl_loss = sl["PnL $"].sum()
print(f"\n--- KEY RATIO ---")
print(f"  Total Losses: ${total_loss:.2f}")
print(f"  From Stop Loss: ${sl_loss:.2f} ({sl_loss/total_loss*100:.1f}%)")
print(f"  From MAX_HOLD: ${df[df['Reason']=='MAX_HOLD_TIME']['PnL $'].sum():.2f}")
