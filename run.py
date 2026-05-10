from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from azalyst.brokers.demo import DemoBroker
from azalyst.brokers.live_binance import LiveBinanceBroker
from azalyst.config import LEVERAGE
from azalyst.logger import logger
from azalyst.trader import LiveTrader
from azalyst import db


def _resolve_api_keys(user_id: str):
    raw_key = db.get_config(user_id, "binance_api_key", "")
    raw_secret = db.get_config(user_id, "binance_api_secret", "")
    encrypted = db.get_config(user_id, "keys_encrypted", "false") == "true"

    if encrypted and raw_key and raw_secret:
        from azalyst import crypto
        try:
            return crypto.decrypt(raw_key), crypto.decrypt(raw_secret)
        except Exception as exc:
            logger.error(f"Failed to decrypt API keys: {exc}")
            return "", ""

    return raw_key or os.getenv("BINANCE_API_KEY", ""), raw_secret or os.getenv("BINANCE_API_SECRET", "")



def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Azalyst Alpha X — Multi Strategy Live Trader")
    parser.add_argument("--dry-run", action="store_true", help="Force paper trading mode")
    parser.add_argument("--dashboard", action="store_true", default=True, help="Launch web dashboard")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable web dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard port")
    args = parser.parse_args()

    active_user_id = None
    client = db.get_client()
    try:
        res = client.table("bot_config").select("user_id").eq("key", "trading_mode").limit(1).execute()
        if res.data:
            active_user_id = res.data[0].get("user_id")
    except Exception as exc:
        logger.error(f"Failed to check bot configuration: {exc}")

    trading_mode = ""
    if active_user_id:
        trading_mode = db.get_config(active_user_id, "trading_mode", "")

    if args.dry_run:
        trading_mode = "dry_run"

    if trading_mode == "live" and active_user_id and not args.dry_run:
        api_key, api_secret = _resolve_api_keys(active_user_id)
        testnet = db.get_config(active_user_id, "binance_testnet", "false") == "true"
        if api_key and api_secret:
            broker = LiveBinanceBroker(api_key=api_key, api_secret=api_secret, testnet=testnet)
            logger.info(f"Operating in LIVE {'TESTNET ' if testnet else ''}TRADING mode for user {active_user_id}")
        else:
            logger.warning("Live mode configured but no API keys found. Falling back to demo mode.")
            broker = DemoBroker()
            api_key, api_secret, testnet = "", "", False
    else:
        broker = DemoBroker()
        api_key, api_secret, testnet = "", "", False
        if trading_mode == "dry_run" and active_user_id:
            logger.info(f"Operating in Demo (Dry Run) mode for user {active_user_id}")
        else:
            logger.info("No active user configuration found. Waiting for setup via dashboard.")

    trader = LiveTrader(broker=broker, user_id=active_user_id, api_key=api_key, api_secret=api_secret, testnet=testnet)

    if args.dashboard and not args.no_dashboard:
        from dashboard.server import start_dashboard
        start_dashboard(trader, port=args.port)
        if not trading_mode:
            logger.info(f"Open http://localhost:{args.port}/auth/signup to create an account")
        else:
            logger.info(f"Dashboard running at http://localhost:{args.port}")

    if not trading_mode and not args.dry_run:
        logger.info("Waiting for configuration from dashboard...")
        import time
        wait_count = 0
        while True:
            try:
                if trader.user_id and db.get_config(trader.user_id, "trading_mode", ""):
                    break
            except Exception as e:
                logger.warning(f"Database connection error: {e}. Retrying...")
            
            wait_count += 1
            if wait_count % 15 == 0:  # Every 30 seconds (15 * 2s)
                logger.info("Still waiting for trading mode configuration (Live/Dry Run) via dashboard...")
                
            time.sleep(2)
            
        try:
            trading_mode = db.get_config(trader.user_id, "trading_mode", "")
            logger.info(f"Configuration received: {trading_mode}. Starting trader...")
        except Exception:
            pass

    trader.run()


if __name__ == "__main__":
    main()
