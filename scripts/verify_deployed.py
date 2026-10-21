"""Read-only hosted inventory checks using the generated sample administrators."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]


def verify(origin):
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or parsed.netloc != "bhc-inventory.vercel.app" or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("This check is restricted to the authorized production origin.")
    origin = origin.rstrip("/")
    credentials = json.loads((ROOT / "instance" / "seed-credentials.json").read_text(encoding="utf-8"))
    checks = 0

    def check(value, label):
        nonlocal checks
        if not value:
            raise AssertionError(label)
        checks += 1

    def sign_in(account):
        client = httpx.Client(base_url=origin, timeout=45, follow_redirects=False)
        entry = client.get("/")
        check(entry.status_code == 302, "Anonymous pages redirect")
        check(client.get("/api/state").status_code == 401, "Anonymous API is protected")
        page = client.get("/login")
        check(page.status_code == 200, "Login page loads")
        token = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
        cookie = entry.headers.get("set-cookie", "")
        check("Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie, "Production cookie flags")
        before = client.cookies.get("session")
        result = client.post("/api/auth/login", headers={"Origin": origin, "X-CSRF-Token": token},
            json={key: account[key] for key in ("email", "password")})
        check(result.status_code == 200 and result.json().get("redirect") == "/", "Hosted sign-in succeeds")
        check(client.cookies.get("session") != before, "Sign-in rotates the session cookie")
        result = client.get("/api/state")
        check(result.status_code == 200, "Live state loads after sign-in")
        state = result.json()
        check(state["mode"] == "live" and state["user"]["role"] == "admin", "Live administrator workspace")
        check(state["csrf"] != token, "Sign-in rotates the CSRF token")
        check("access_token" not in result.text and "refresh_token" not in result.text, "No Auth tokens in browser state")
        return client, state

    admin, state = sign_in(credentials["accounts"]["admin"])
    qa, qa_state = sign_in(credentials["accounts"]["qa"])
    try:
        check(state["facility"]["id"] == credentials["facility_id"], "Correct sample facility")
        check(len(state["items"]) == 19 and len(state["categories"]) == 10, "Seed inventory is integrated")
        check(state["transactions"] and all(tx.get("lines") for tx in state["transactions"]), "Stock history and batch allocations load")
        check(qa_state["facility"]["id"] != state["facility"]["id"] and qa_state["items"] == [], "Separate facility stays isolated")
        for path in ("/", "/inventory", "/movements", "/expiry", "/categories", "/settings", "/account/password"):
            result = admin.get(path)
            check(result.status_code == 200, "Protected page loads: " + path)
            check(result.headers.get("cache-control") == "no-store", "Protected page is never cached: " + path)
        check(admin.get("/team").status_code == 404, "Team screen is removed")
        for filename in ("app.css", "app.js", "auth.js", "password.js", "callback.js", "icons.svg", "favicon.svg"):
            check(admin.get("/static/" + filename).status_code == 200, "CDN asset loads: " + filename)
        check(admin.get("/health").json() == {"status": "ok"}, "Health endpoint works")
        result = admin.post("/api/actions/switch", headers={"Origin": origin, "X-CSRF-Token": state["csrf"]},
            json={"facility_id": qa_state["facility"]["id"]})
        check(result.status_code == 403, "Foreign facility switch is rejected")
        replay = httpx.Client(base_url=origin, timeout=45, cookies=admin.cookies)
        try:
            check(replay.get("/api/state").json()["facility"]["id"] == state["facility"]["id"], "Session persists across independent connections")
            result = admin.post("/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": state["csrf"]}, json={})
            check(result.status_code == 200, "Hosted logout succeeds")
            check(admin.get("/api/state").status_code == 401, "Logged-out client cannot read inventory")
            check(replay.get("/api/state").status_code == 401, "Replaying the old cookie cannot restore access")
        finally:
            replay.close()
        result = qa.post("/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": qa_state["csrf"]}, json={})
        check(result.status_code == 200, "QA logout succeeds")
        print(f"PASS: {checks} hosted checks at {origin}")
        print("Verified production login/logout, secure sessions, live seed data, facility isolation, history, and CDN assets.")
        print("Inventory data was not modified; no emails were sent.")
    finally:
        admin.close()
        qa.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://bhc-inventory.vercel.app")
    verify(parser.parse_args().origin)
