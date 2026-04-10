from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv
import ccxt

from azalyst.config import LEVERAGE
from azalyst.logger import logger
from azalyst.trader import LiveTrader


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Azalyst Alpha X — Multi Strategy Live Trader")
    parser.add_argument("--testnet", action="store_true", help="Use Binance testnet")
    parser.add_argument("--dry-run", action="store_true", help="Paper trading only (no live orders)")
    parser.add_argument("--api-key", type=str, help="Binance API key (or set BINANCE_API_KEY env var)")
    parser.add_argument("--api-secret", type=str, help="Binance API secret (or set BINANCE_API_SECRET env var)")
    parser.add_argument("--symbols", type=str, help="Comma-separated list of symbols to trade")
    parser.add_argument("--dashboard", action="store_true", default=True, help="Launch web dashboard (default: enabled)")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable web dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard port (default: 8080)")

    args = parser.parse_args()

    exchange_config = {
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
        },
    }

    dry_run = True  # Forced to true per user request
    logger.info("Operating in Signal-Only Mode (No API keys required, no real trades).")
    logger.info("Using Binance Public Data (Paper Trading)")

    exchange = ccxt.binance(exchange_config)

    trader = LiveTrader(exchange, dry_run=dry_run)

    if args.symbols:
        trader.symbols = [s.strip() for s in args.symbols.split(",")]

    if args.dashboard and not args.no_dashboard:
        from azalyst.dashboard.server import start_dashboard
        start_dashboard(trader, port=args.port)
        logger.info(f"Dashboard running at http://localhost:{args.port}")

    trader.run()


if __name__ == "__main__":
    main()
