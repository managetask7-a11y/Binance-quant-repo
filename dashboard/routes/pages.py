from flask import Blueprint, render_template, request, redirect, url_for, session
from azalyst import db as supabase_db
from dashboard.routes.auth import login_required

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/")
@login_required
def index():
    user_id = session.get("user_id")
    mode = supabase_db.get_config(user_id, "trading_mode", "")
    if not mode:
        return redirect(url_for("pages.setup"))
    return render_template("index.html")


@pages_bp.route("/setup", methods=["GET"])
@login_required
def setup():
    return render_template("setup.html")


@pages_bp.route("/setup", methods=["POST"])
@login_required
def setup_post():
    user_id = session.get("user_id")
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "dry_run")
    api_key = data.get("api_key", "")
    api_secret = data.get("api_secret", "")

    supabase_db.upsert_config(user_id, "trading_mode", mode)
    if api_key:
        supabase_db.upsert_config(user_id, "binance_api_key", api_key)
    if api_secret:
        supabase_db.upsert_config(user_id, "binance_api_secret", api_secret)
    return {"success": True, "mode": mode}

@pages_bp.route("/backtest")
@login_required
def backtest():
    return render_template("backtest.html")
