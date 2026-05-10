from __future__ import annotations

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        _client = create_client(url, key)
    return _client


def insert_trade(user_id: str, trade: dict, mode: str = "dry_run") -> dict:
    client = get_client()
    row = {
        "user_id": user_id,
        "mode": mode,
        "symbol": trade["symbol"],
        "direction": trade["direction"],
        "entry_price": trade["entry_price"],
        "qty": trade["qty"],
        "sl_price": trade["sl_price"],
        "tp_price": trade["tp_price"],
        "sl_dist_pct": trade.get("sl_dist_pct", 0),
        "entry_time": trade["entry_time"],
        "status": "open",
        "scan_count": trade.get("scan_count", 0),
        "max_price": trade.get("max_price", trade["entry_price"]),
        "min_price": trade.get("min_price", trade["entry_price"]),
        "signal": trade.get("signal", ""),
        "strategies": trade.get("strategies", ""),
        "atr": trade.get("atr", 0),
    }
    result = client.table("trades").insert(row).execute()
    if result.data:
        return result.data[0]
    return {}


def update_trade(user_id: str, trade_id: int, updates: dict) -> None:
    client = get_client()
    client.table("trades").update(updates).eq("id", trade_id).eq("user_id", user_id).execute()


def update_trade_sl(user_id: str, trade_id: int, sl_price: float) -> None:
    client = get_client()
    client.table("trades").update({"sl_price": sl_price}).eq("id", trade_id).eq("user_id", user_id).execute()


def close_trade_db(user_id: str, trade_id: int, exit_time: str, exit_price: float,
                   pnl_pct: float, pnl_usd: float, reason: str) -> None:
    client = get_client()
    client.table("trades").update({
        "exit_time": exit_time,
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "status": "closed",
        "reason": reason,
    }).eq("id", trade_id).eq("user_id", user_id).execute()


def fetch_open_trades(user_id: str, mode: str = "dry_run") -> list:
    client = get_client()
    result = client.table("trades").select("*").eq("status", "open").eq("user_id", user_id).eq("mode", mode).execute()
    return result.data or []


def fetch_closed_trades(user_id: str, mode: str = "dry_run") -> list:
    client = get_client()
    result = client.table("trades").select("*").eq("status", "closed").eq("user_id", user_id).eq("mode", mode).order("exit_time", desc=False).execute()
    return result.data or []


def insert_equity(user_id: str, point: dict, mode: str = "dry_run") -> None:
    client = get_client()
    client.table("equity_log").insert({
        "user_id": user_id,
        "mode": mode,
        "timestamp": point["timestamp"],
        "balance": point["balance"],
        "open_trades": point["open_trades"],
        "daily_pnl": point["daily_pnl"],
    }).execute()


def fetch_equity(user_id: str, mode: str = "dry_run") -> list:
    client = get_client()
    result = client.table("equity_log").select("*").eq("user_id", user_id).eq("mode", mode).order("timestamp").execute()
    return result.data or []


def safe_execute(func, max_retries=3):
    """Retries a database operation if it fails due to transient network errors."""
    import time
    last_err = None
    for i in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_err = e
            # Log only if it's a known transient network error
            if "ReadError" in str(e) or "Resource temporarily unavailable" in str(e) or "10035" in str(e):
                from azalyst.logger import logger
                logger.warn(f"Database transient error (attempt {i+1}/{max_retries}): {e}")
                time.sleep(0.5 * (i + 1))
                continue
            raise e
    raise last_err


def upsert_config(user_id: str, key: str, value: str) -> None:
    client = get_client()
    def _op():
        return client.table("bot_config").upsert(
            {"user_id": user_id, "key": key, "value": value},
            on_conflict="user_id,key"
        ).execute()
    safe_execute(_op)


def get_config(user_id: str, key: str, default=None):
    client = get_client()
    def _op():
        return client.table("bot_config").select("value").eq("user_id", user_id).eq("key", key).limit(1).execute()
    
    result = safe_execute(_op)
    if result and result.data:
        return result.data[0]["value"]
    return default


def upsert_wallet_snapshot(user_id: str, balance: float, source: str = "binance") -> None:
    client = get_client()
    client.table("wallet_snapshots").insert({
        "user_id": user_id,
        "balance": balance,
        "source": source,
    }).execute()


def fetch_wallet_snapshots(user_id: str, limit: int = 100) -> list:
    client = get_client()
    result = (
        client.table("wallet_snapshots")
        .select("*")
        .eq("user_id", user_id)
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def insert_binance_trades(user_id: str, trades: list) -> None:
    client = get_client()
    rows = []
    for t in trades:
        rows.append({
            "user_id": user_id,
            "order_id": str(t.get("id", "")),
            "symbol": t.get("symbol", ""),
            "side": t.get("side", ""),
            "qty": float(t.get("amount", 0) or 0),
            "price": float(t.get("price", 0) or 0),
            "realized_pnl": float(t.get("info", {}).get("realizedPnl", 0) or 0),
            "commission": float(t.get("fee", {}).get("cost", 0) or 0),
            "commission_asset": t.get("fee", {}).get("currency", ""),
            "trade_time": t.get("datetime", ""),
        })
    if rows:
        client.table("binance_trades").upsert(rows, on_conflict="user_id,order_id").execute()


def fetch_binance_trades(user_id: str, limit: int = 100) -> list:
    client = get_client()
    result = (
        client.table("binance_trades")
        .select("*")
        .eq("user_id", user_id)
        .order("trade_time", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
