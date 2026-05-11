from __future__ import annotations

import os

from flask import Blueprint, jsonify, request, session

from azalyst import db as supabase_db
from azalyst import crypto
from azalyst.brokers.live_binance import LiveBinanceBroker
from azalyst.brokers.demo import DemoBroker
from dashboard.routes.auth import login_required

broker_bp = Blueprint("broker", __name__)

_trader_instance = None


def set_broker_trader(trader):
    global _trader_instance
    _trader_instance = trader


def _user_id() -> str | None:
    return session.get("user_id")


def _encryption_key_available() -> bool:
    return bool(os.environ.get("ENCRYPTION_KEY"))


@broker_bp.route("/api/broker/connect", methods=["POST"])
@login_required
def connect_broker():
    user_id = _user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    api_key = (data.get("api_key") or "").strip()
    api_secret = (data.get("api_secret") or "").strip()
    testnet = bool(data.get("testnet", False))

    if not api_key or not api_secret:
        return jsonify({"error": "api_key and api_secret are required"}), 400

    broker = LiveBinanceBroker(api_key=api_key, api_secret=api_secret, testnet=testnet)
    result = broker.validate_connection()

    if not result.get("success"):
        return jsonify({"error": result.get("error", "Connection failed"), "detail": result.get("detail")}), 400

    if _encryption_key_available():
        supabase_db.upsert_config(user_id, "binance_api_key", crypto.encrypt(api_key))
        supabase_db.upsert_config(user_id, "binance_api_secret", crypto.encrypt(api_secret))
        supabase_db.upsert_config(user_id, "keys_encrypted", "true")
    else:
        supabase_db.upsert_config(user_id, "binance_api_key", api_key)
        supabase_db.upsert_config(user_id, "binance_api_secret", api_secret)
        supabase_db.upsert_config(user_id, "keys_encrypted", "false")

    supabase_db.upsert_config(user_id, "trading_mode", "live")
    supabase_db.upsert_config(user_id, "binance_testnet", str(testnet).lower())

    if _trader_instance:
        _trader_instance.reconfigure(broker)

    if result.get("balance", 0) > 0:
        supabase_db.upsert_wallet_snapshot(user_id, result["balance"], source="binance")

    return jsonify({
        "success": True,
        "balance": result["balance"],
        "permissions": result.get("permissions", []),
        "testnet": testnet,
    })


@broker_bp.route("/api/broker/status", methods=["GET"])
@login_required
def broker_status():
    user_id = _user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403

    trading_mode = supabase_db.get_config(user_id, "trading_mode", "demo")
    testnet = supabase_db.get_config(user_id, "binance_testnet", "false") == "true"
    is_live = trading_mode == "live"

    live_balance = None
    if is_live and _trader_instance:
        live_balance = _trader_instance.live_balance

    return jsonify({
        "is_live": is_live,
        "testnet": testnet,
        "live_balance": live_balance,
        "paused": _trader_instance.paused if _trader_instance else False,
    })


@broker_bp.route("/api/broker/wallet", methods=["GET"])
@login_required
def broker_wallet():
    user_id = _user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403

    if not _trader_instance or not _trader_instance.broker.is_live:
        return jsonify({"balance": None, "source": "demo"})

    balance = _trader_instance.broker.fetch_wallet_balance()
    if balance > 0:
        supabase_db.upsert_wallet_snapshot(user_id, balance)

    return jsonify({"balance": balance, "source": "binance"})


@broker_bp.route("/api/broker/disconnect", methods=["POST"])
@login_required
def disconnect_broker():
    user_id = _user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403

    supabase_db.upsert_config(user_id, "binance_api_key", "")
    supabase_db.upsert_config(user_id, "binance_api_secret", "")
    supabase_db.upsert_config(user_id, "trading_mode", "dry_run")
    supabase_db.upsert_config(user_id, "keys_encrypted", "false")

    if _trader_instance:
        from azalyst.brokers.demo import DemoBroker
        _trader_instance.reconfigure(DemoBroker())

    return jsonify({"success": True})


@broker_bp.route("/api/broker/history", methods=["GET"])
@login_required
def broker_history():
    user_id = _user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403

    limit = min(int(request.args.get("limit", 100)), 500)
    trades = supabase_db.fetch_binance_trades(user_id, limit=limit)

    total_pnl = sum(float(t.get("realized_pnl", 0)) for t in trades)
    total_commission = sum(float(t.get("commission", 0)) for t in trades)

    return jsonify({
        "trades": trades,
        "analytics": {
            "total_trades": len(trades),
            "total_realized_pnl": round(total_pnl, 4),
            "total_commission": round(total_commission, 6),
            "net_pnl": round(total_pnl - total_commission, 4),
        },
    })
