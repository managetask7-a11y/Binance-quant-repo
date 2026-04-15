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


def insert_trade(user_id: str, trade: dict) -> dict:
    client = get_client()
    row = {
        "user_id": user_id,
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


def fetch_open_trades(user_id: str) -> list:
    client = get_client()
    result = client.table("trades").select("*").eq("status", "open").eq("user_id", user_id).execute()
    return result.data or []


def fetch_closed_trades(user_id: str) -> list:
    client = get_client()
    result = client.table("trades").select("*").eq("status", "closed").eq("user_id", user_id).order("exit_time", desc=False).execute()
    return result.data or []


def insert_equity(user_id: str, point: dict) -> None:
    client = get_client()
    client.table("equity_log").insert({
        "user_id": user_id,
        "timestamp": point["timestamp"],
        "balance": point["balance"],
        "open_trades": point["open_trades"],
        "daily_pnl": point["daily_pnl"],
    }).execute()


def fetch_equity(user_id: str) -> list:
    client = get_client()
    result = client.table("equity_log").select("*").eq("user_id", user_id).order("timestamp").execute()
    return result.data or []


def upsert_config(user_id: str, key: str, value: str) -> None:
    client = get_client()
    client.table("bot_config").upsert({
        "user_id": user_id,
        "key": key,
        "value": value,
    }, on_conflict="user_id,key").execute()


def get_config(user_id: str, key: str, default: str = "") -> str:
    client = get_client()
    result = client.table("bot_config").select("value").eq("key", key).eq("user_id", user_id).execute()
    if result.data:
        return result.data[0]["value"]
    return default
