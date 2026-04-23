from flask import Blueprint, jsonify, request, session
import requests
from dashboard.routes.auth import login_required
from azalyst import db as supabase_db
from azalyst.config import (
    TP_RR_RATIO, RISK_PER_TRADE, ATR_MULT, LEVERAGE, TOP_N_COINS
)

api_bp = Blueprint("api", __name__)

_trader_instance = None


def set_trader(trader):
    global _trader_instance
    _trader_instance = trader


def _verify_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    if _trader_instance and _trader_instance.user_id is None:
        # If trader was waiting for setup, link it to the first user who interacts
        _trader_instance.user_id = user_id
        # We MUST load their historical state and balance now that we know who they are
        _trader_instance._load_state()
        _trader_instance._refresh_config()
    elif _trader_instance and _trader_instance.user_id != user_id:
        return None
    return user_id


@api_bp.route("/api/status")
@login_required
def api_status():
    if not _verify_user():
        return jsonify({"error": "Unauthorized or trader not initialized"}), 403
    return jsonify(_trader_instance.get_status())


@api_bp.route("/api/trades/open")
@login_required
def api_open_trades():
    if not _verify_user():
        return jsonify([])
    return jsonify(_trader_instance.get_open_trades())


@api_bp.route("/api/trades/closed")
@login_required
def api_closed_trades():
    if not _verify_user():
        return jsonify([])
    return jsonify(_trader_instance.get_closed_trades())


@api_bp.route("/api/equity")
@login_required
def api_equity():
    if not _verify_user():
        return jsonify([])
    return jsonify(_trader_instance.get_equity_curve())


@api_bp.route("/api/trades/close", methods=["POST"])
@login_required
def api_close_trade():
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol", "")
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    result = _trader_instance.manual_close_trade(symbol)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@api_bp.route("/api/daily_target", methods=["POST"])
@login_required
def api_set_daily_target():
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json(silent=True) or {}
    target = data.get("target", 0)
    try:
        target = float(target)
    except (ValueError, TypeError):
        return jsonify({"error": "target must be a number"}), 400
    _trader_instance.set_daily_profit_target(target)
    # Also save to config
    supabase_db.upsert_config(_trader_instance.user_id, "daily_profit_target", str(target))
    return jsonify({"success": True, "daily_profit_target": target})


@api_bp.route("/api/server/ip")
@login_required
def api_server_ip():
    try:
        # Use ipify to get the public IP of the machine
        resp = requests.get('https://api.ipify.org', timeout=5)
        return jsonify({"ip": resp.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/api/settings/mode", methods=["POST"])
@login_required
def api_change_mode():
    user_id = _verify_user()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.get_json(silent=True) or {}
    mode = data.get("mode")
    api_key = data.get("api_key", "")
    api_secret = data.get("api_secret", "")
    
    if mode not in ["dry_run", "live"]:
        return jsonify({"error": "Invalid mode"}), 400
        
    # Save to DB
    supabase_db.upsert_config(user_id, "trading_mode", mode)
    
    if mode == "live":
        # Load existing keys from DB if none provided
        if not api_key:
            from azalyst.crypto import decrypt
            api_key = decrypt(supabase_db.get_config(user_id, "binance_api_key", ""))
        if not api_secret:
            from azalyst.crypto import decrypt
            api_secret = decrypt(supabase_db.get_config(user_id, "binance_api_secret", ""))
            
        if not api_key or not api_secret:
            return jsonify({"error": "Please connect to Binance first to use Live mode."}), 400
            
        testnet = supabase_db.get_config(user_id, "binance_testnet", "false") == "true"
        
        try:
            from azalyst.brokers.live_binance import LiveBinanceBroker
            broker = LiveBinanceBroker(api_key, api_secret, testnet=testnet)
            # Validate connection briefly
            val = broker.validate_connection()
            if not val.get("success"):
                return jsonify({"error": "Failed to connect to Live Binance. " + val.get("error", "")}), 400
            _trader_instance.reconfigure(broker)
        except Exception as e:
            return jsonify({"error": f"Failed to configure Live Binance: {e}"}), 400
    else:
        _trader_instance.reconfigure(
            __import__("azalyst.brokers.demo", fromlist=["DemoBroker"]).DemoBroker(
                __import__("ccxt").binanceusdm({"enableRateLimit": True})
            )
        )

    return jsonify({"success": True, "mode": mode})


@api_bp.route("/api/trading/pause", methods=["POST"])
@login_required
def api_pause():
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
    _trader_instance.pause()
    supabase_db.upsert_config(_trader_instance.user_id, "paused", "true")
    return jsonify({"success": True, "paused": True})


@api_bp.route("/api/trading/resume", methods=["POST"])
@login_required
def api_resume():
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
    _trader_instance.resume()
    supabase_db.upsert_config(_trader_instance.user_id, "paused", "false")
    return jsonify({"success": True, "paused": False})


@api_bp.route("/api/wallet", methods=["GET"])
@login_required
def api_wallet():
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({
        "virtual_balance": round(_trader_instance.balance, 2),
        "live_balance": round(_trader_instance.live_balance, 2) if _trader_instance.live_balance is not None else None,
        "is_live": _trader_instance.broker.is_live,
    })


@api_bp.route("/api/config/defaults", methods=["GET"])
@login_required
def api_get_config_defaults():
    # Strictly returns values from config.py
    strategy_mapping = {
        "tp_rr_ratio": TP_RR_RATIO,
        "risk_per_trade": RISK_PER_TRADE,
        "atr_mult": ATR_MULT,
        "leverage": LEVERAGE,
        "top_n_coins": TOP_N_COINS,
        "prop_daily_loss_pct": PROP_DAILY_LOSS_PCT
    }
    return jsonify(strategy_mapping)


@api_bp.route("/api/settings/config", methods=["GET"])
@login_required
def api_get_config():
    user_id = _verify_user()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Strategy keys should show active values (with global defaults as fallback)
    strategy_keys = [
        "tp_rr_ratio", "risk_per_trade", "atr_mult", "leverage",
        "top_n_coins", "prop_daily_loss_pct", "daily_profit_target"
    ]
    
    # Notification keys should stay blank unless specifically set by the user
    notification_keys = ["telegram_bot_token", "telegram_chat_id"]
    
    config = {}
    
    # 1. Strategy: Get from trader instance (which already has defaults applied)
    for k in strategy_keys:
        if k == "daily_profit_target":
            config[k] = _trader_instance.daily_profit_target
        else:
            config[k] = _trader_instance.config.get(k, "")
        
    # 2. Notifications: Get strictly from DB, fallback to empty string
    for k in notification_keys:
        config[k] = supabase_db.get_config(user_id, k, "")
        
    return jsonify(config)


@api_bp.route("/api/settings/config", methods=["POST"])
@login_required
def api_update_config():
    user_id = _verify_user()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    data = request.get_json(silent=True) or {}
    
    # Map of allowed keys and their expected types
    allowed_keys = {
        "tp_rr_ratio": float,
        "risk_per_trade": float,
        "atr_mult": float,
        "leverage": int,
        "top_n_coins": int,
        "prop_daily_loss_pct": float,
        "daily_profit_target": float,
        "telegram_bot_token": str,
        "telegram_chat_id": str
    }
    
    for key, val_type in allowed_keys.items():
        if key in data:
            val = data[key]
            try:
                # Basic validation/conversion
                if val_type == float:
                    val = float(val)
                elif val_type == int:
                    val = int(val)
                else:
                    val = str(val)
                
                supabase_db.upsert_config(user_id, key, str(val))
            except (ValueError, TypeError):
                continue

    # Refresh the trader instance so it picks up changes immediately
    _trader_instance._refresh_config()
    
    return jsonify({"success": True})


@api_bp.route("/test_ping")
def test_ping():
    return jsonify({"status": "healthy", "message": "pong"})
