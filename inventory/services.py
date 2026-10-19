"""Per-request Supabase clients. The signed-in user's JWT always controls RLS."""
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import ClientOptions, create_client


def new_client(config):
    if not config.get("SUPABASE_URL") or not config.get("SUPABASE_PUBLISHABLE_KEY"):
        raise ValueError("Live sign-in is not configured yet. You can explore the demo workspace.")
    return create_client(config["SUPABASE_URL"], config["SUPABASE_PUBLISHABLE_KEY"],
        options=ClientOptions(auto_refresh_token=False, persist_session=False))


def store_auth(record, response):
    if not response.session:
        return False
    record["auth"] = {"access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token, "user_id": str(response.user.id),
        "email": response.user.email}
    return True


def authenticated_client(config, record):
    if not record.get("auth"):
        raise PermissionError("Sign in to open your facility workspace.")
    client = new_client(config)
    response = client.auth.set_session(record["auth"]["access_token"], record["auth"]["refresh_token"])
    store_auth(record, response)
    return client


def all_rows(client, table, facility_id):
    result, offset = [], 0
    while True:
        page = client.table(table).select("*").eq("facility_id", facility_id).range(offset, offset + 999).execute().data
        result.extend(page)
        if len(page) < 1000:
            return result
        offset += 1000


def live_state(client, record):
    auth = record["auth"]
    memberships = client.table("facility_memberships").select("*").eq("user_id", auth["user_id"]).eq("is_active", True).execute().data
    profile = client.table("profiles").select("display_name").eq("id", auth["user_id"]).single().execute().data
    user = {"id": auth["user_id"], "name": profile["display_name"], "email": auth["email"], "role": "admin"}
    facilities = client.table("facilities").select("*").order("created_at").execute().data
    selected = next((f for f in facilities if f["id"] == record.get("facility_id")), None)
    if not selected and facilities:
        selected = facilities[0]
    if not selected:
        return {"onboarding": True, "user": user, "facilities": [], "mode": "live"}
    record["facility_id"] = selected["id"]
    user["role"] = next(m["role"] for m in memberships if m["facility_id"] == selected["id"])
    facility_id = selected["id"]
    items = all_rows(client, "items", facility_id)
    summaries = {s["item_id"]: s for s in all_rows(client, "inventory_summary", facility_id)}
    for item in items:
        item.update({key: value for key, value in summaries[item["id"]].items() if key != "item_id"})
    transactions = client.table("stock_transactions").select("*").eq("facility_id", facility_id).order("occurred_at", desc=True).limit(200).execute().data
    lines = []
    if transactions:
        offset = 0
        while True:
            page = client.table("stock_transaction_lines").select("*").eq("facility_id", facility_id).in_("transaction_id", [t["id"] for t in transactions]).range(offset, offset + 999).execute().data
            lines.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
    for tx in transactions:
        tx["lines"] = [line for line in lines if line["transaction_id"] == tx["id"]]
        tx.pop("request_payload", None)
    profiles = {p["id"]: p["display_name"] for p in client.table("profiles").select("id,display_name").execute().data}
    members = all_rows(client, "facility_memberships", facility_id)
    for member in members:
        member["name"] = profiles.get(member["user_id"], "Inactive account")
    audits = client.table("audit_events").select("*").eq("facility_id", facility_id).order("occurred_at", desc=True).limit(100).execute().data if user["role"] == "admin" else []
    return {"mode": "live", "facility": selected, "facilities": facilities, "user": user,
        "items": items, "batches": all_rows(client, "batch_stock_status", facility_id),
        "transactions": transactions, "categories": all_rows(client, "categories", facility_id),
        "members": members, "audit_events": audits, "history_limit": 200,
        "today": datetime.now(ZoneInfo(selected["timezone"])).date().isoformat()}
