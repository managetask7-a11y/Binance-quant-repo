from functools import wraps
from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template
from gotrue.errors import AuthApiError
from azalyst import db
import logging

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            # If it's an API request, return 401
            if request.path.startswith("/api/"):
                return jsonify({"error": "Unauthorized"}), 401
            # Otherwise, redirect to login page
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route("/auth/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("pages.index"))
        return render_template("auth.html", mode="login")

    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    client = db.get_client()
    try:
        response = client.auth.sign_in_with_password({"email": email, "password": password})
        if response.user:
            session["user_id"] = response.user.id
            session["access_token"] = response.session.access_token
            return jsonify({"success": True})
        return jsonify({"error": "Login failed"}), 401
    except AuthApiError as e:
        return jsonify({"error": str(e.message)}), 401
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@auth_bp.route("/auth/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("pages.index"))
        return render_template("auth.html", mode="signup")

    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400

    client = db.get_client()
    try:
        # Use current host URL for redirection to handle localhost vs production (Render)
        redirect_to = request.host_url.rstrip('/') + url_for('pages.index')
        response = client.auth.sign_up({
            "email": email, 
            "password": password,
            "options": {"email_redirect_to": redirect_to}
        })
        if response.user:
            # Supabase might demand email confirmation depending on settings. 
            # If confirmed immediately or if confirmation is disabled, session works.
            if response.session:
                session["user_id"] = response.user.id
                session["access_token"] = response.session.access_token
                return jsonify({"success": True, "message": "Signup successful!"})
            else:
                 return jsonify({"success": True, "message": "Check your email for the confirmation link."})
        return jsonify({"error": "Signup failed"}), 400
    except AuthApiError as e:
        return jsonify({"error": str(e.message)}), 400
    except Exception as e:
        logger.error(f"Signup error: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    client = db.get_client()
    try:
        client.auth.sign_out()
    except Exception as e:
        logger.error(f"Logout error with Supabase: {e}")
    session.clear()
    return jsonify({"success": True})
