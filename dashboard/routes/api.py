from flask import Blueprint, jsonify, request, session
import requests
import logging

logger = logging.getLogger(__name__)
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
        _trader_instance._refresh_top_coins()
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
                err_msg = val.get("error", "")
                detail = val.get("detail", "").lower()
                
                # ONLY block if we are sure it's an Authentication/API Key issue
                if "auth" in detail or "invalid" in err_msg.lower() or "key" in err_msg.lower():
                    return jsonify({"error": "Failed to connect to Live Binance. " + err_msg}), 400
                
                # For any other connection error (timeout, 418, connection failed), allow saving
                _trader_instance.reconfigure(broker)
                return jsonify({
                    "success": True, 
                    "mode": mode, 
                    "warning": f"Settings saved! Note: Binance connection is unstable ({err_msg}). Bot will retry automatically."
                })
            _trader_instance.reconfigure(broker)
        except Exception as e:
            # Fallback for unexpected exceptions
            _trader_instance.reconfigure(broker)
            return jsonify({"success": True, "mode": mode, "warning": "Settings saved, but connection could not be verified."})
    else:
        _trader_instance.reconfigure(
            __import__("azalyst.brokers.demo", fromlist=["DemoBroker"]).DemoBroker()
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


@api_bp.route("/api/trading/reset_daily", methods=["POST"])
@login_required
def api_reset_daily():
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
        
    try:
        if _trader_instance:
            _trader_instance.manual_reset_daily_stats()
            return jsonify({"success": True, "message": "Daily limits reset successfully."})
        else:
            return jsonify({"error": "Trader instance not found"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/api/trading/reset_all", methods=["POST"])
@login_required
def api_reset_all():
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
    try:
        if _trader_instance:
            _trader_instance.manual_reset_all_history()
            return jsonify({"success": True})
        return jsonify({"error": "Trader instance not found"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        "top_n_coins", "prop_daily_loss_pct", "daily_profit_target",
        "regime_mode", "manual_regime"
    ]
    
    # Notification keys should stay blank unless specifically set by the user
    notification_keys = ["telegram_bot_token", "telegram_chat_id"]
    
    config = {}
    
    # 1. Strategy: Get from trader instance (which already has defaults applied)
    for k in strategy_keys:
        if k == "daily_profit_target":
            config[k] = _trader_instance.daily_profit_target
        elif k in ["regime_mode", "manual_regime"]:
            config[k] = supabase_db.get_config(user_id, k, "auto" if k == "regime_mode" else "sideways")
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
        "telegram_chat_id": str,
        "regime_mode": str,
        "manual_regime": str
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
    _trader_instance.refresh_regime_now()
    
    return jsonify({"success": True})


@api_bp.route("/api/test_trade", methods=["POST"])
@login_required
def api_test_trade():
    """Opens a tiny long, then immediately closes it to verify full trade pipeline."""
    if not _verify_user():
        return jsonify({"error": "Unauthorized"}), 403
    if not _trader_instance or not _trader_instance.broker.is_live:
        return jsonify({"error": "Bot must be in LIVE mode to test a real trade."}), 400

    data = request.get_json(silent=True) or {}
    req_symbol = data.get("symbol")

    # 1. Pick symbol: specified or first from tracking list
    symbols = _trader_instance.symbols
    if not symbols:
        return jsonify({"error": "No symbols are currently being tracked."}), 400
    
    if req_symbol and req_symbol in symbols:
        symbol = req_symbol
    else:
        symbol = symbols[0]

    try:
        broker = _trader_instance.broker

        # 2. Fetch current price to calculate minimum qty
        import ccxt
        ticker = broker._exchange.fetch_ticker(symbol)
        price = ticker.get("last", 0)
        if not price:
            return jsonify({"error": f"Could not fetch price for {symbol}."}), 500

        # Calculate qty for ~$6.0 notional (Binance min is ~$5)
        # We use a bit more ($6) to ensure we clear the minimum exactly
        qty = 6.0 / price
        
        # Rounding for safety (most coins use 0-3 decimals)
        if price > 1000: qty = round(qty, 4)
        elif price > 10: qty = round(qty, 2)
        else: qty = round(qty, 1)

        # 3. Open a tiny LONG
        logger.info(f"🧪 Running test trade on {symbol} (Qty: {qty} @ ${price})")
        open_result = broker.place_market_order(symbol, "buy", qty)
        if not open_result:
            return jsonify({"error": f"Failed to open test position on {symbol}. Endpoint may be blocked."}), 500

        # 4. Immediately close it
        import time
        time.sleep(1.5)
        close_result = broker.place_market_order(symbol, "sell", qty)

        return jsonify({
            "success": True,
            "message": f"✅ Test trade complete! Opened and closed {qty} {symbol.split('/')[0]} (~$6.00).",
            "symbol": symbol,
            "open_order": str(open_result.get("id", "N/A")),
            "close_order": str(close_result.get("id", "N/A")) if close_result else "N/A"
        })
    except Exception as e:
        return jsonify({"error": f"Test trade failed: {str(e)}"}), 500


@api_bp.route("/test_ping")
def test_ping():
    return jsonify({"status": "healthy", "message": "pong"})
