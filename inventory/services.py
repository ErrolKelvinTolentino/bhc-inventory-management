"""Per-request Supabase clients. The signed-in user's JWT always controls RLS."""
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import ClientOptions, create_client
from supabase_auth.errors import AuthApiError, AuthSessionMissingError


class AuthenticationRequired(PermissionError):
    """The local session no longer has valid Supabase credentials."""


def new_client(config):
    if not config.get("SUPABASE_URL") or not config.get("SUPABASE_PUBLISHABLE_KEY"):
        raise ValueError("Live sign-in is not configured yet. You can explore the demo workspace.")
    return create_client(config["SUPABASE_URL"], config["SUPABASE_PUBLISHABLE_KEY"],
        options=ClientOptions(auto_refresh_token=False, persist_session=False,
            flow_type="implicit", postgrest_client_timeout=20))


def store_auth(record, response):
    if not response.session:
        return False
    user = response.user or response.session.user
    record["auth"] = {"access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token, "user_id": str(user.id),
        "email": user.email}
    return True


def authenticated_client(config, record):
    if not record.get("auth"):
        raise AuthenticationRequired("Sign in to open your facility workspace.")
    client = new_client(config)
    try:
        response = client.auth.set_session(record["auth"]["access_token"], record["auth"]["refresh_token"])
    except (AuthApiError, AuthSessionMissingError) as error:
        if isinstance(error, AuthApiError) and getattr(error, "code", "") not in (
            "refresh_token_not_found", "refresh_token_already_used", "session_not_found",
            "bad_jwt", "user_not_found", "user_banned", "session_expired",
        ) and getattr(error, "status", 0) not in (401, 403):
            raise
        record.pop("auth", None)
        record.pop("mode", None)
        record.pop("facility_id", None)
        raise AuthenticationRequired("Your session has expired. Please sign in again.") from error
    store_auth(record, response)
    return client


def all_rows(client, table, facility_id):
    result, offset = [], 0
    while True:
        order = "item_id" if table == "inventory_summary" else "user_id" if table == "facility_memberships" else "id"
        page = client.table(table).select("*").eq("facility_id", facility_id).order(order).range(offset, offset + 999).execute().data
        result.extend(page)
        if len(page) < 1000:
            return result
        offset += 1000


def live_context(client, record):
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
    membership = next((m for m in memberships if m["facility_id"] == selected["id"] and m["role"] == "admin"), None)
    if not membership:
        raise PermissionError("An active facility administrator is required.")
    record["facility_id"] = selected["id"]
    user["role"] = "admin"
    return {"mode": "live", "facility": selected, "facilities": facilities, "user": user}


def live_state(client, record):
    context = live_context(client, record)
    if context.get("onboarding"):
        return context
    selected, user = context["facility"], context["user"]
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
    audits = client.table("audit_events").select("*").eq("facility_id", facility_id).order("occurred_at", desc=True).limit(100).execute().data if user["role"] == "admin" else []
    return {**context,
        "items": items, "batches": all_rows(client, "batch_stock_status", facility_id),
        "transactions": transactions, "categories": all_rows(client, "categories", facility_id),
        "audit_events": audits, "history_limit": 200,
        "today": datetime.now(ZoneInfo(selected["timezone"])).date().isoformat()}
