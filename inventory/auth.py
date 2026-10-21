"""Account flows, bound email callbacks, and rotation of opaque sessions."""
import secrets
import time
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session

from . import services

bp = Blueprint("accounts", __name__)


def rotate_session():
    old_sid = g.sid
    g.sid = secrets.token_urlsafe(32)
    session.clear()
    session["sid"] = g.sid
    g.record["csrf"] = secrets.token_urlsafe(32)
    g.expired_sids = [*getattr(g, "expired_sids", []), old_sid]


def auth_client():
    return services.authenticated_client(current_app.config, g.record)


def login_required():
    if not g.record.get("auth"):
        raise services.AuthenticationRequired("Please sign in to continue.")


def remember_login(response, recovery=False):
    if not services.store_auth(g.record, response):
        raise ValueError("Sign-in did not return a session. Please try again.")
    g.record.pop("demo", None)
    g.record.pop("auth_flow", None)
    g.record.pop("facility_id", None)
    g.record["mode"] = "live"
    g.record["password_recovery"] = recovery
    rotate_session()


def begin_email_flow(email, intent):
    nonce = secrets.token_urlsafe(24)
    g.record["auth_flow"] = {"nonce": nonce, "email": email.casefold(),
        "intent": intent, "expires": time.time() + 3600}
    origin = (current_app.config.get("APP_URL") or request.host_url).rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("The application URL is not configured correctly.")
    return f"{origin}/auth/callback/{nonce}"


def expected_flow(nonce):
    flow = g.record.get("auth_flow", {})
    if not nonce or not secrets.compare_digest(str(flow.get("nonce", "")), str(nonce)) or flow.get("expires", 0) < time.time():
        raise ValueError("This email link has expired or belongs to another browser. Request a new link in this browser.")
    return flow


@bp.get("/login")
def login():
    if g.record.get("auth") and g.record.get("mode") == "live":
        return redirect("/")
    return render_template("auth.html", csrf=g.record["csrf"],
        configured=bool(current_app.config["SUPABASE_PUBLISHABLE_KEY"]), onboarding=False,
        user=None, notice=g.record.pop("auth_notice", None))


@bp.get("/auth/callback/<nonce>")
def callback(nonce):
    try:
        expected_flow(nonce)
    except ValueError as error:
        g.record["auth_notice"] = str(error)
        return redirect("/login")
    return render_template("callback.html", csrf=g.record["csrf"], nonce=nonce)


@bp.get("/account/password")
def password_screen():
    login_required()
    return render_template("password.html", csrf=g.record["csrf"],
        recovery=bool(g.record.get("password_recovery")))


@bp.post("/api/auth/<action>")
def authentication(action):
    payload = request.get_json()
    if action == "logout":
        if g.record.get("auth"):
            try:
                auth_client().auth.sign_out({"scope": "local"})
            except Exception:
                current_app.logger.info("Remote sign-out unavailable; local session cleared")
        g.record.clear()
        rotate_session()
        return jsonify(redirect="/login")
    if action == "callback":
        flow = expected_flow(payload.get("nonce"))
        access, refresh = payload.get("access_token"), payload.get("refresh_token")
        if not isinstance(access, str) or not isinstance(refresh, str) or not access or not refresh:
            raise ValueError("The email link is incomplete. Request a new link.")
        client = services.new_client(current_app.config)
        # set_session verifies the tokens with Supabase, not browser claims.
        response = client.auth.set_session(access, refresh)
        if not response.user or (response.user.email or "").casefold() != flow["email"]:
            raise ValueError("The link does not match the account requested in this browser.")
        recovery = flow["intent"] == "recovery"
        remember_login(response, recovery=recovery)
        return jsonify(redirect="/account/password" if recovery else "/")
    if action == "password":
        login_required()
        password = payload.get("password", "")
        if not isinstance(password, str) or len(password) < 8:
            raise ValueError("Use a password with at least eight characters.")
        if password != payload.get("confirmation"):
            raise ValueError("The new passwords do not match.")
        if not g.record.get("password_recovery"):
            current = payload.get("current_password")
            if not isinstance(current, str) or not current:
                raise ValueError("Enter your current password.")
            verification = services.new_client(current_app.config)
            verification.auth.sign_in_with_password({"email": g.record["auth"]["email"], "password": current})
            verification.auth.sign_out({"scope": "local"})
        auth_client().auth.update_user({"password": password})
        g.record["password_recovery"] = False
        rotate_session()
        return jsonify(redirect="/", message="Your password has been changed.")
    if action not in ("login", "register", "recover", "resend"):
        raise ValueError("Unknown account action.")
    email = payload.get("email", "")
    if not isinstance(email, str) or "@" not in email or len(email.strip()) > 254:
        raise ValueError("Enter a valid email address.")
    email = email.strip()
    client = services.new_client(current_app.config)
    if action == "recover":
        callback_url = begin_email_flow(email, "recovery")
        client.auth.reset_password_email(email, {"redirect_to": callback_url})
        return jsonify(message="If an account exists for that address, a password reset link is on its way. Open it in this browser.")
    if action == "resend":
        callback_url = begin_email_flow(email, "signup")
        client.auth.resend({"type": "signup", "email": email, "options": {"email_redirect_to": callback_url}})
        return jsonify(message="If your account needs verification, a new link is on its way. Open it in this browser.")
    password = payload.get("password", "")
    if not isinstance(password, str) or not password or (action == "register" and len(password) < 8):
        raise ValueError("Use a password with at least eight characters.")
    if action == "register":
        name = str(payload.get("name", "")).strip()
        if not name or len(name) > 120:
            raise ValueError("Enter your name (up to 120 characters).")
        callback_url = begin_email_flow(email, "signup")
        response = client.auth.sign_up({"email": email, "password": password,
            "options": {"data": {"display_name": name}, "email_redirect_to": callback_url}})
        if not response.session:
            return jsonify(message="Check your email to verify your account. Open the link in this browser to continue with facility registration.")
    else:
        response = client.auth.sign_in_with_password({"email": email, "password": password})
    remember_login(response)
    return jsonify(redirect="/")
