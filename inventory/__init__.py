from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, session
from supabase_auth.errors import AuthApiError
from postgrest.exceptions import APIError
from werkzeug.exceptions import HTTPException

from . import demo, services


class SessionStore:
    """Small local server-side session store; no Supabase tokens in browser cookies."""
    def __init__(self, path):
        self.path = path
        self.locks = {}
        self.lock = threading.Lock()
        with self.connect() as db:
            db.execute("create table if not exists sessions (id text primary key, payload text not null, expires real not null)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def acquire(self, sid):
        with self.lock:
            lock = self.locks.setdefault(sid, threading.RLock())
        lock.acquire()
        return lock

    def read(self, sid):
        with self.connect() as db:
            row = db.execute("select payload from sessions where id=? and expires>?", (sid, time.time())).fetchone()
        return json.loads(row[0]) if row else {"csrf": secrets.token_urlsafe(32)}

    def write(self, sid, data):
        with self.connect() as db:
            db.execute("delete from sessions where expires < ?", (time.time(),))
            db.execute("insert into sessions values (?,?,?) on conflict(id) do update set payload=excluded.payload, expires=excluded.expires",
                (sid, json.dumps(data), time.time() + 86400))


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SUPABASE_URL=os.getenv("SUPABASE_URL", ""),
        SUPABASE_PUBLISHABLE_KEY=os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
        APP_TIMEZONE=os.getenv("APP_TIMEZONE", "Asia/Manila"),
        SECRET_KEY=os.getenv("SECRET_KEY") or None,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE") == "1", MAX_CONTENT_LENGTH=65536,
    )
    if test_config:
        app.config.update(test_config)
    instance = Path(app.config.get("DATA_DIRECTORY", app.instance_path))
    instance.mkdir(parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        key_path = instance / "secret.key"
        if not key_path.exists():
            key_path.write_text(secrets.token_hex(32), encoding="utf-8")
        app.config["SECRET_KEY"] = key_path.read_text(encoding="utf-8")
    store = SessionStore(instance / "sessions.sqlite3")
    app.extensions["session_store"] = store

    @app.before_request
    def load_session():
        if request.endpoint == "static":
            return
        if not session.get("sid"):
            session.clear()
            session["sid"] = secrets.token_urlsafe(32)
        g.sid = session["sid"]
        g.session_lock = store.acquire(g.sid)
        g.record = store.read(g.sid)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("Origin")
            if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
                return jsonify(error="This request came from another website. Reload and try again."), 403
            token = request.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(token, g.record["csrf"]):
                return jsonify(error="Your page has expired. Reload and try again."), 403
            if not request.is_json:
                return jsonify(error="Send a JSON request."), 415
            if not isinstance(request.get_json(silent=True), dict):
                return jsonify(error="Send a JSON object with the form fields."), 400

    @app.after_request
    def finish(response):
        if hasattr(g, "record"):
            store.write(g.sid, g.record)
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.teardown_request
    def unlock(_error):
        if hasattr(g, "session_lock"):
            g.session_lock.release()

    def today():
        tz = g.record.get("demo", {}).get("facility", {}).get("timezone", app.config["APP_TIMEZONE"])
        return datetime.now(ZoneInfo(tz)).date()

    def client():
        if not hasattr(g, "supabase"):
            g.supabase = services.authenticated_client(app.config, g.record)
        return g.supabase

    def state():
        if g.record.get("mode") == "live":
            result = services.live_state(client(), g.record)
        else:
            if "demo" not in g.record:
                g.record["demo"] = demo.seed(today())
            result = demo.snapshot(g.record["demo"], today())
            result.update(mode="demo", facilities=[result["facility"]], today=today().isoformat())
        result.update(csrf=g.record["csrf"], configured=bool(app.config["SUPABASE_PUBLISHABLE_KEY"]))
        return result

    def require_admin(current):
        if current["user"]["role"] != "admin":
            raise PermissionError("An administrator is required for this action.")

    @app.get("/")
    @app.get("/inventory")
    @app.get("/movements")
    @app.get("/expiry")
    @app.get("/categories")
    @app.get("/team")
    @app.get("/settings")
    def workspace():
        current = state()
        if current.get("onboarding"):
            return render_template("auth.html", csrf=g.record["csrf"], configured=current["configured"], onboarding=True, user=current["user"])
        return render_template("workspace.html", state=current)

    @app.get("/demo")
    def enter_demo():
        # A separate mode, never a fallback after a live mutation fails.
        g.record["mode"] = "demo"
        return redirect("/")

    @app.get("/login")
    def login():
        return render_template("auth.html", csrf=g.record["csrf"],
            configured=bool(app.config["SUPABASE_PUBLISHABLE_KEY"]), onboarding=False, user=None)

    @app.get("/api/state")
    def api_state():
        return jsonify(state())

    @app.post("/api/auth/<action>")
    def authentication(action):
        payload = request.get_json()
        if action == "logout":
            if g.record.get("auth"):
                try:
                    client().auth.sign_out()
                except Exception:
                    # A failed remote revocation must not trap a user in a local
                    # session. Dropping our server-side tokens still signs out.
                    app.logger.info("Remote sign-out unavailable; local session cleared")
            csrf = secrets.token_urlsafe(32)
            g.record.clear()
            g.record["csrf"] = csrf
            return jsonify(redirect="/login")
        auth_client = services.new_client(app.config)
        email = str(payload.get("email", "")).strip()
        password = str(payload.get("password", ""))
        if not email or "@" not in email:
            raise ValueError("Enter a valid email address.")
        if action not in ("login", "register"):
            raise ValueError("Unknown account action.")
        if not password or (action == "register" and len(password) < 8):
            raise ValueError("Use a password with at least eight characters.")
        if action == "register":
            name = str(payload.get("name", "")).strip()
            if not name or len(name) > 120:
                raise ValueError("Enter your name (up to 120 characters).")
            response = auth_client.auth.sign_up({"email": email, "password": password, "options": {"data": {"display_name": name}}})
            if not services.store_auth(g.record, response):
                return jsonify(message="Check your email to verify your account. Once verified, return here to sign in and register your facility.")
        else:
            response = auth_client.auth.sign_in_with_password({"email": email, "password": password})
            services.store_auth(g.record, response)
        g.record["mode"] = "live"
        g.record["csrf"] = secrets.token_urlsafe(32)
        return jsonify(redirect="/")

    @app.post("/api/facility/register")
    def register_facility():
        payload = request.get_json()
        name = str(payload.get("name", "")).strip()
        if not name or len(name) > 200:
            raise ValueError("Enter your facility name (up to 200 characters).")
        result = client().rpc("register_facility", {"p_name": name, "p_timezone": app.config["APP_TIMEZONE"]}).execute()
        g.record["facility_id"] = result.data
        g.record["mode"] = "live"
        return jsonify(redirect="/")

    @app.post("/api/actions/<action>")
    def mutate(action):
        payload = request.get_json()
        current = state()
        if current.get("onboarding"):
            raise ValueError("Register a facility first.")
        facility_id = current["facility"]["id"]
        if action == "switch":
            if not any(f["id"] == payload.get("facility_id") for f in current["facilities"]):
                raise PermissionError("You do not have access to that facility.")
            g.record["facility_id"] = payload["facility_id"]
            return jsonify(state=state(), message="Workspace switched.")
        if action not in ("stock", "item", "category", "archive", "settings", "member"):
            raise ValueError("Unknown inventory action.")
        if action != "stock":
            require_admin(current)
        now = datetime.now(ZoneInfo(current["facility"]["timezone"])).isoformat()
        model = deepcopy(g.record.get("demo")) if current["mode"] == "demo" else None
        if action == "stock":
            allowed = {"p_item_id", "p_transaction_type", "p_quantity", "p_idempotency_key", "p_batch_id",
                "p_batch_number", "p_expiry_date", "p_reason", "p_reference_number", "p_source_destination", "p_corrects_transaction_id"}
            params = {k: v for k, v in payload.items() if k in allowed and v is not None}
            if model is not None:
                demo.post_stock(model, params, today(), occurred_at=now)
            else:
                client().rpc("post_stock_transaction", {**params, "p_facility_id": facility_id}).execute()
        elif action == "item":
            name, code, unit = (str(payload.get(k, "")).strip() for k in ("name", "code", "unit"))
            kind = payload.get("item_type")
            threshold = payload.get("low_stock_threshold", 10)
            if not name or len(name) > 200 or not code or len(code) > 64 or not unit or len(unit) > 40:
                raise ValueError("Enter an item name, code, and base unit within the field limits.")
            if kind not in ("medicine", "supply") or type(threshold) is not int or threshold < 0:
                raise ValueError("Choose an item type and a valid stock threshold.")
            fields = {k: payload.get(k) for k in ("generic_name", "brand", "strength", "dosage_form", "specification", "description", "category_id")}
            fields.update(name=name, code=code, unit=unit, item_type=kind,
                low_stock_threshold=threshold, expiry_required=kind == "medicine" or bool(payload.get("expiry_required")))
            item_id = payload.get("id")
            if model is None:
                client().rpc("save_item", {"p_facility_id": facility_id, "p_item_id": item_id,
                    **{f"p_{k}": v for k, v in fields.items()}}).execute()
            else:
                existing = next((i for i in model["items"] if i["id"] == item_id), None)
                if item_id and not existing:
                    raise ValueError("Item not found.")
                if any(i["code"].lower() == code.lower() and i["id"] != item_id for i in model["items"]):
                    raise ValueError("This item code is already in use.")
                if fields["category_id"] and not any(c["id"] == fields["category_id"] and c["item_type"] == kind for c in model["categories"]):
                    raise ValueError("Choose a category for this item type.")
                if existing and any(t["item_id"] == item_id for t in model["transactions"]) and (existing["unit"] != unit or existing["item_type"] != kind):
                    raise ValueError("An item's unit and type cannot change after stock has been recorded.")
                if fields["expiry_required"] and any(b["item_id"] == item_id and not b["expiry_date"] for b in model["batches"]):
                    raise ValueError("Existing undated batches prevent requiring expiry.")
                before = deepcopy(existing)
                if existing:
                    existing.update(fields)
                else:
                    existing = {"id": secrets.token_hex(16), "is_archived": False, **fields}
                    model["items"].append(existing)
                demo.audit(model, "items", before, existing, now)
        elif action == "category":
            name, kind = str(payload.get("name", "")).strip(), payload.get("item_type")
            if not name or len(name) > 120 or kind not in ("medicine", "supply"):
                raise ValueError("Enter a category name and item type.")
            if model is None:
                client().rpc("save_category", {"p_facility_id": facility_id, "p_name": name, "p_item_type": kind}).execute()
            else:
                if any(c["name"].lower() == name.lower() and c["item_type"] == kind for c in model["categories"]):
                    raise ValueError("This category already exists.")
                category = {"id": secrets.token_hex(16), "name": name, "item_type": kind}
                model["categories"].append(category)
                demo.audit(model, "categories", None, category, now)
        elif action == "archive":
            item_id = payload.get("id")
            archive = payload.get("is_archived", True)
            if type(archive) is not bool:
                raise ValueError("Choose whether to archive this item.")
            if model is None:
                client().rpc("set_item_archived", {"p_facility_id": facility_id, "p_item_id": item_id, "p_is_archived": archive}).execute()
            else:
                target = next((i for i in model["items"] if i["id"] == item_id), None)
                if not target:
                    raise ValueError("Item not found.")
                if archive and any(b["item_id"] == item_id and b["quantity_on_hand"] > 0 for b in model["batches"]):
                    raise ValueError("Reconcile the remaining stock before archiving this item.")
                old = deepcopy(target)
                target["is_archived"] = archive
                demo.audit(model, "items", old, target, now)
        elif action == "settings":
            name = str(payload.get("name", "")).strip()
            days = payload.get("near_expiry_days")
            tz = str(payload.get("timezone", "Asia/Manila"))
            if not name or len(name) > 200 or type(days) is not int or not 1 <= days <= 365:
                raise ValueError("Enter a facility name and an expiry window from 1 to 365 days.")
            try:
                ZoneInfo(tz)
            except (KeyError, ValueError) as error:
                raise ValueError("Choose a valid timezone.") from error
            if model is None:
                client().rpc("update_facility", {"p_facility_id": facility_id, "p_name": name, "p_timezone": tz, "p_near_expiry_days": days}).execute()
            else:
                before = deepcopy(model["facility"])
                model["facility"].update(name=name, timezone=tz, near_expiry_days=days)
                demo.audit(model, "facilities", before, model["facility"], now)
        elif action == "member":
            if model is not None:
                raise ValueError("Staff invitations are not part of the sample workspace. Sign in to manage a real facility.")
            role = payload.get("role", "staff")
            active = payload.get("is_active", True)
            if role not in ("admin", "staff") or type(active) is not bool:
                raise ValueError("Choose valid staff permissions.")
            client().rpc("set_facility_member", {"p_facility_id": facility_id, "p_user_id": payload.get("user_id"),
                "p_role": role, "p_is_active": active}).execute()
        if model is not None:
            g.record["demo"] = model
        return jsonify(state=state(), message={"stock": "Stock movement recorded.", "item": "Item saved.",
            "category": "Category added.", "archive": "Item updated.", "settings": "Facility settings saved.", "member": "Staff access updated."}[action])

    @app.errorhandler(ValueError)
    @app.errorhandler(PermissionError)
    def validation_error(error):
        return jsonify(error=str(error)), 403 if isinstance(error, PermissionError) else 400

    @app.errorhandler(AuthApiError)
    @app.errorhandler(APIError)
    def service_error(error):
        message = getattr(error, "message", "The request could not be completed.")
        return jsonify(error=message[:250]), 400

    @app.errorhandler(Exception)
    def unexpected(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.error("Request failed: %s", type(error).__name__)
        if request.path.startswith("/api/"):
            return jsonify(error="The request could not be completed. Please try again."), 500
        return render_template("error.html"), 503

    return app
