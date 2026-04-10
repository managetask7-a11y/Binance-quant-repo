# Azalyst Alpha X — Multi Strategy Live Trader

Automated multi-strategy crypto trading system for Binance Futures with a real-time web dashboard and Discord alerts.

## Quick Start

```bash
pip install -r requirements.txt

# Paper trading with dashboard
python run.py --dry-run --api-key YOUR_KEY --api-secret YOUR_SECRET

# Live trading
python run.py --api-key YOUR_KEY --api-secret YOUR_SECRET

# Testnet
python run.py --testnet --api-key YOUR_KEY --api-secret YOUR_SECRET
```

Dashboard opens at **http://localhost:8080** by default.

## Project Structure

```
azalyst/
├── config.py           # All trading parameters & constants
├── logger.py           # Logging utility
├── indicators.py       # Technical indicator calculations
├── consensus.py        # Multi-strategy voting logic
├── trader.py           # Live trading engine
├── notifications.py    # Discord webhook alerts
├── strategies/
│   ├── zamco.py        # EMA trend pullback
│   ├── bnf.py          # Mean reversion (Takashi Kotegawa)
│   ├── jadecap.py      # Supply/demand + break of structure
│   ├── marci.py        # MACD + VWAP + ADX trend day
│   ├── nbb.py          # Candlestick pattern + S/R
│   ├── umar.py         # Momentum breakout
│   └── kane.py         # Liquidity sweep + reversal
└── dashboard/
    ├── server.py       # Flask API & dashboard server
    ├── templates/      # HTML templates
    └── static/         # CSS & JavaScript
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--dry-run` | Paper trading, no real orders |
| `--testnet` | Use Binance testnet |
| `--api-key` | Binance API key |
| `--api-secret` | Binance API secret |
| `--symbols` | Comma-separated symbol list |
| `--no-dashboard` | Disable web dashboard |
| `--port` | Dashboard port (default: 8080) |

## Risk Parameters

| Parameter | Value |
|-----------|-------|
| Leverage | 5x |
| Risk per trade | 10% |
| Max drawdown | 50% |
| Daily loss limit | 25% |
| Max concurrent trades | 20 |
| Max hold time | 12 hours |
| Stop loss | 1.2x ATR (1-3% bounds) |
| Take profit | 2.5x R:R ratio |
