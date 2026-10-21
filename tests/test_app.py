import json
from uuid import uuid4

import pytest

from inventory import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "SECRET_KEY": "test-only-key", "DATA_DIRECTORY": str(tmp_path),
        "SUPABASE_URL": "", "SUPABASE_PUBLISHABLE_KEY": ""})


def workspace(client):
    response = client.get("/api/state")
    if response.status_code == 401:
        client.get("/demo")
        response = client.get("/api/state")
    assert response.status_code == 200
    return response.get_json()


def mutate(client, state, action, payload):
    return client.post(f"/api/actions/{action}", json=payload, headers={"X-CSRF-Token": state["csrf"]})


def stock_payload(item, kind, quantity, **kwargs):
    return {"p_item_id": item["id"], "p_transaction_type": kind, "p_quantity": quantity,
        "p_idempotency_key": str(uuid4()), **kwargs}


def test_workspace_routes_and_private_cookie(app):
    client = app.test_client()
    assert client.get("/").status_code == 302
    assert client.get("/").headers["Location"] == "/login"
    assert client.get("/api/state").status_code == 401
    client.get("/demo")
    for path in ("/", "/inventory", "/movements", "/expiry", "/categories", "/settings", "/login"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    cookie = client.get_cookie("session")
    assert cookie.http_only and cookie.same_site == "Lax"
    assert "access_token" not in cookie.value


def test_demo_seed_reconciles_and_marks_expiry(app):
    state = workspace(app.test_client())
    assert state["mode"] == "demo" and len(state["items"]) == 19
    assert len([i for i in state["items"] if i["stock_status"] != "in_stock"]) == 3
    assert len([b for b in state["batches"] if b["expiry_status"] == "expired"]) == 1
    for batch in state["batches"]:
        movements = [line["quantity_change"] for t in state["transactions"] for line in t["lines"] if line["batch_id"] == batch["id"]]
        assert sum(movements) == batch["quantity_on_hand"]
    assert all("request_payload" not in t for t in state["transactions"])


def test_csrf_and_origin_protection(app):
    client = app.test_client()
    state = workspace(client)
    payload = {"name": "Changed", "timezone": "Asia/Manila", "near_expiry_days": 30}
    assert client.post("/api/actions/settings", json=payload).status_code == 403
    assert client.post("/api/actions/settings", json=payload, headers={"X-CSRF-Token": state["csrf"], "Origin": "https://elsewhere.invalid"}).status_code == 403
    assert workspace(client)["facility"]["name"] == state["facility"]["name"]


def test_non_object_json_is_rejected(app):
    client = app.test_client()
    state = workspace(client)
    response = client.post("/api/actions/settings", json=[], headers={"X-CSRF-Token":state["csrf"]})
    assert response.status_code == 400


def test_demo_sessions_are_isolated(app):
    first, second = app.test_client(), app.test_client()
    state = workspace(first)
    response = mutate(first, state, "settings", {"name": "My sample clinic", "timezone": "Asia/Manila", "near_expiry_days": 45})
    assert response.status_code == 200
    assert workspace(first)["facility"]["name"] == "My sample clinic"
    assert workspace(second)["facility"]["name"] == "San Isidro Health Center"
    audit = workspace(first)["audit_events"][0]
    assert audit["old_data"]["name"] == "San Isidro Health Center"
    assert audit["new_data"]["name"] == "My sample clinic"


def test_receipt_issue_retries_and_history(app):
    client = app.test_client()
    state = workspace(client)
    item = next(i for i in state["items"] if i["name"] == "Paracetamol")
    payload = stock_payload(item, "receipt", 100, p_batch_number="TEST-LOT", p_expiry_date="2099-12-31")
    response = mutate(client, state, "stock", payload)
    assert response.status_code == 200
    after = response.get_json()["state"]
    assert next(i for i in after["items"] if i["id"] == item["id"])["usable_quantity"] == item["usable_quantity"] + 100
    count = len(after["transactions"])
    assert mutate(client, state, "stock", payload).status_code == 200
    assert len(workspace(client)["transactions"]) == count
    changed = {**payload, "p_quantity": 101}
    assert mutate(client, state, "stock", changed).status_code == 400
    issue = stock_payload(item, "issue", 20, p_source_destination="Clinic use")
    response = mutate(client, state, "stock", issue)
    assert response.status_code == 200
    tx = next(t for t in response.get_json()["state"]["transactions"] if t["idempotency_key"] == issue["p_idempotency_key"])
    assert tx["quantity_change"] == -20
    assert tx["lines"][0]["balance_before"] - tx["lines"][0]["balance_after"] == 20


def test_failed_issue_does_not_change_inventory_or_history(app):
    client = app.test_client()
    state = workspace(client)
    item = next(i for i in state["items"] if i["name"] == "Amoxicillin")
    assert mutate(client, state, "stock", stock_payload(item, "issue", 99999)).status_code == 400
    after = workspace(client)
    assert after["batches"] == state["batches"]
    assert after["transactions"] == state["transactions"]


def test_expired_stock_blocked_until_disposal(app):
    client = app.test_client()
    state = workspace(client)
    batch = next(b for b in state["batches"] if b["expiry_status"] == "expired")
    item = next(i for i in state["items"] if i["id"] == batch["item_id"])
    payload = stock_payload(item, "issue", 1, p_batch_id=batch["id"])
    assert mutate(client, state, "stock", payload).status_code == 400
    response = mutate(client, state, "stock", stock_payload(item, "disposal", batch["quantity_on_hand"], p_batch_id=batch["id"], p_reason="Expired stock removed"))
    assert response.status_code == 200
    after = response.get_json()["state"]
    assert next(b for b in after["batches"] if b["id"] == batch["id"])["quantity_on_hand"] == 0


def test_adjustment_archive_and_audit(app):
    client = app.test_client()
    state = workspace(client)
    item = next(i for i in state["items"] if i["name"] == "Cotton balls")
    batch = next(b for b in state["batches"] if b["item_id"] == item["id"])
    assert mutate(client, state, "archive", {"id": item["id"], "is_archived": True}).status_code == 400
    assert mutate(client, state, "stock", stock_payload(item, "adjustment", 0, p_batch_id=batch["id"], p_reason="Damaged stock" )).status_code == 200
    response = mutate(client, state, "archive", {"id": item["id"], "is_archived": True})
    assert response.status_code == 200
    assert next(i for i in response.get_json()["state"]["items"] if i["id"] == item["id"])["is_archived"]
    assert any(a["table_name"] == "items" for a in workspace(client)["audit_events"])


def test_catalog_validation_and_snapshot_history(app):
    client = app.test_client()
    state = workspace(client)
    item = next(i for i in state["items"] if i["name"] == "Paracetamol")
    payload = {**item, "name": "Paracetamol renamed"}
    assert mutate(client, state, "item", payload).status_code == 200
    assert all(t["item_name"] == "Paracetamol" for t in workspace(client)["transactions"] if t["item_id"] == item["id"])
    assert mutate(client, state, "item", {**payload, "unit": "box"}).status_code == 400
    assert mutate(client, state, "item", {**payload, "id": None}).status_code == 400


def test_administrator_only_workspace(app):
    client = app.test_client()
    state = workspace(client)
    assert state["user"]["role"] == "admin"
    assert all(member["role"] == "admin" for member in state["members"])
    assert client.get("/team").status_code == 404
    assert b'Team members' not in client.get("/").data
    assert mutate(client, state, "member", {"user_id":"unused", "role":"staff"}).status_code == 400


def test_no_silent_demo_fallback_when_live_auth_is_missing(app):
    client = app.test_client()
    state = workspace(client)
    with client.session_transaction() as browser_session:
        sid = browser_session["sid"]
    store = app.extensions["session_store"]
    saved = store.read(sid)
    saved["mode"] = "live"
    store.write(sid, saved)
    assert client.get("/api/state").status_code == 401
    assert client.get("/demo").status_code == 302
    assert workspace(client)["mode"] == "demo"


def test_facility_configuration_and_tokens_not_exposed(app):
    client = app.test_client()
    state = workspace(client)
    assert mutate(client, state, "settings", {"name":"Test", "timezone":"Invalid/Zone", "near_expiry_days":30}).status_code == 400
    assert mutate(client, state, "settings", {"name":"Test", "timezone":"UTC", "near_expiry_days":0}).status_code == 400
    serialized = json.dumps(state)
    assert "refresh_token" not in serialized and "access_token" not in serialized
    assert client.post('/api/auth/login', json={"email":"test@example.test", "password":"unused"}, headers={"X-CSRF-Token":state["csrf"]}).status_code == 400
