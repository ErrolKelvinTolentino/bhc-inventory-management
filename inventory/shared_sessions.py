"""Encrypted, leased Supabase sessions shared by serverless Flask instances."""
import base64
import hashlib
import json
import secrets
import time
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
import httpx


class SessionUnavailable(RuntimeError):
    pass


class Lease:
    def __init__(self, store, sid, owner, record):
        self.store, self.sid, self.owner, self.record = store, sid, owner, record
        self.finished = False

    def release(self):
        if not self.finished:
            self.store.rpc("release_app_session", p_sid_hash=self.store.digest(self.sid), p_owner=self.owner)
            self.finished = True


class SupabaseSessionStore:
    def __init__(self, config):
        self.url = config["SUPABASE_URL"].rstrip("/") + "/rest/v1"
        self.key = config["SUPABASE_SECRET_KEY"]
        self.wait_seconds = config.get("SESSION_LOCK_WAIT", 8)
        # Domain-separated encryption key: independent of the cookie signing key.
        key = hashlib.sha256(("inventory-session-encryption-v1:" + config["SECRET_KEY"]).encode()).digest()
        self.cipher = Fernet(base64.urlsafe_b64encode(key))

    @staticmethod
    def digest(sid):
        return hashlib.sha256(sid.encode()).hexdigest()

    def request(self, method, path, **kwargs):
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        # Legacy service-role JWTs need Authorization; new sb_secret keys use apikey.
        if not self.key.startswith("sb_secret_"):
            headers["Authorization"] = "Bearer " + self.key
        try:
            response = httpx.request(method, self.url + path, headers=headers, timeout=12, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        except (httpx.HTTPError, ValueError) as error:
            raise SessionUnavailable("Session storage is temporarily unavailable. Please try again.") from error

    def rpc(self, name, **payload):
        return self.request("POST", "/rpc/" + name, json=payload)

    def decode(self, payload):
        if not payload:
            return {"csrf": secrets.token_urlsafe(32)}
        try:
            return json.loads(self.cipher.decrypt(payload.encode()))
        except (InvalidToken, ValueError, TypeError) as error:
            raise SessionUnavailable("This session could not be read. Please clear your browser cookie and sign in again.") from error

    def acquire(self, sid):
        owner, deadline = str(uuid4()), time.monotonic() + self.wait_seconds
        while True:
            result = self.rpc("lease_app_session", p_sid_hash=self.digest(sid), p_owner=owner)
            if result["acquired"]:
                lease = Lease(self, sid, owner, {})
                try:
                    lease.record = self.decode(result["payload"])
                    return lease
                except Exception:
                    lease.release()
                    raise
            if time.monotonic() >= deadline:
                raise SessionUnavailable("Another request is finishing. Please try again.")
            time.sleep(0.15)

    def finish(self, lease, sid, record):
        payload = self.cipher.encrypt(json.dumps(record).encode()).decode()
        self.rpc("commit_app_session", p_sid_hash=self.digest(lease.sid), p_owner=lease.owner,
            p_new_sid_hash=self.digest(sid), p_payload=payload)
        lease.finished = True

    # Inspection/setup helpers used by integration checks, never browser endpoints.
    def read(self, sid):
        lease = self.acquire(sid)
        try:
            return lease.record
        finally:
            lease.release()

    def write(self, sid, record):
        lease = self.acquire(sid)
        try:
            self.finish(lease, sid, record)
        finally:
            lease.release()

