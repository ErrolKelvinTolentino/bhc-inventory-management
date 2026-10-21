r"""Create/reuse one labeled sample facility through Supabase Auth and user RPCs.

Run: .venv\Scripts\python.exe scripts/seed_supabase.py --use-cli
Only Auth account creation uses an administrative key, kept in process memory.
Inventory writes use the seeded administrator's ordinary authenticated client.
"""
import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from supabase import ClientOptions, create_client
from inventory.demo import seed

SEED_TAG = "bhc-sample-v1"


def get_admin_key(project_ref, use_cli=False):
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if key:
        return key
    if not use_cli:
        raise ValueError("Supply a seed-only administrative key in the environment or pass --use-cli.")
    command = ["npx.cmd" if os.name == "nt" else "npx", "--yes", "supabase", "projects", "api-keys",
        "--project-ref", project_ref, "--output", "json", "--reveal"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    entries = json.loads(result.stdout)
    if isinstance(entries, dict):
        entries = entries.get("api_keys", entries.get("keys", []))
    found = next((entry["api_key"] for entry in entries if entry.get("name") == "service_role"), None)
    if not found:
        found = next((entry["api_key"] for entry in entries if entry.get("type") == "secret"), None)
    if not found:
        raise ValueError("The CLI did not return an administrative key.")
    return found


def save_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def seed_project(use_cli=False, credentials_path=None):
    load_dotenv(ROOT / ".env")
    url, public_key = os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    project_ref = (urlsplit(url).hostname or "").split(".")[0]
    if not re.fullmatch("[a-z]{20}", project_ref) or not public_key:
        raise ValueError("Configure a hosted SUPABASE_URL and public client key in .env first.")
    path = Path(credentials_path) if credentials_path else ROOT / "instance" / "seed-credentials.json"
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["project_ref"] != project_ref or record["seed_version"] != SEED_TAG:
            raise ValueError("The credentials file belongs to another project or seed version.")
    else:
        record = {"project_ref": project_ref, "seed_version": SEED_TAG,
            "seed_date": datetime.now(ZoneInfo("Asia/Manila")).date().isoformat(),
            "facility_name": "Sample Health Center (Seed)",
            "accounts": {role: {"email": f"{role}@seed.bhc-inventory.test", "password": secrets.token_urlsafe(24)}
                for role in ("admin",)}}
        save_record(path, record)
    options = ClientOptions(auto_refresh_token=False, persist_session=False, flow_type="implicit", postgrest_client_timeout=20)
    administrative = create_client(url, get_admin_key(project_ref, use_cli), options=options)
    users = []
    page = 1
    while True:
        batch = administrative.auth.admin.list_users(page=page, per_page=1000)
        users.extend(batch)
        if len(batch) < 1000:
            break
        page += 1
    for role in ("admin",):
        account = record["accounts"][role]
        user = next((u for u in users if (u.email or "").casefold() == account["email"].casefold()), None)
        if user and user.app_metadata.get("inventory_seed") != SEED_TAG:
            raise ValueError("A seed email belongs to an unrelated account; refusing to change it.")
        if not user:
            user = administrative.auth.admin.create_user({"email": account["email"], "password": account["password"],
                "email_confirm": True, "user_metadata": {"display_name": "Sample Administrator"},
                "app_metadata": {"inventory_seed": SEED_TAG}}).user
        account["user_id"] = str(user.id)
        save_record(path, record)
    print("Seed accounts are ready (no verification emails sent).", flush=True)
    client = create_client(url, public_key, options=options)
    client.auth.sign_in_with_password({key: record["accounts"]["admin"][key] for key in ("email", "password")})
    owned = client.table("facilities").select("id,name,created_by").eq("created_by", record["accounts"]["admin"]["user_id"]).execute().data
    facility = next((f for f in owned if f["id"] == record.get("facility_id")), None)
    if not facility:
        facility = next((f for f in owned if f["name"] == record["facility_name"]), None)
    if not facility:
        facility_id = client.rpc("register_facility", {"p_name": record["facility_name"], "p_timezone": "Asia/Manila"}).execute().data
    else:
        facility_id = facility["id"]
    record["facility_id"] = facility_id
    save_record(path, record)
    model = seed(date.fromisoformat(record["seed_date"]))
    existing_categories = client.table("categories").select("*").eq("facility_id", facility_id).execute().data
    category_ids = {}
    for category in model["categories"]:
        existing = next((c for c in existing_categories if c["name"].casefold() == category["name"].casefold() and c["item_type"] == category["item_type"]), None)
        category_ids[category["id"]] = existing["id"] if existing else client.rpc("save_category", {
            "p_facility_id": facility_id, "p_name": category["name"], "p_item_type": category["item_type"]}).execute().data
    existing_items = client.table("items").select("id,code").eq("facility_id", facility_id).execute().data
    item_ids = {}
    fields = ("code", "name", "item_type", "unit", "generic_name", "brand", "strength", "dosage_form",
        "specification", "description", "expiry_required", "low_stock_threshold")
    for item in model["items"]:
        existing = next((i for i in existing_items if i["code"].casefold() == item["code"].casefold()), None)
        item_ids[item["id"]] = existing["id"] if existing else client.rpc("save_item", {
            "p_facility_id": facility_id, "p_category_id": category_ids[item["category_id"]],
            **{f"p_{field}": item[field] for field in fields}}).execute().data
    print("Categories and 19 inventory items are ready.", flush=True)
    fixture_batches = {batch["id"]: batch for batch in model["batches"]}
    for index, transaction in enumerate(model["transactions"]):
        original = transaction["request_payload"]
        params = {"p_facility_id": facility_id, "p_item_id": item_ids[transaction["item_id"]],
            "p_transaction_type": transaction["transaction_type"], "p_quantity": original["p_quantity"],
            "p_idempotency_key": str(uuid5(NAMESPACE_URL, f"{SEED_TAG}/{project_ref}/{facility_id}/{index}")),
            "p_source_destination": original.get("p_source_destination"),
            "p_reference_number": "SEED-OPENING" if transaction["transaction_type"] == "receipt" else "SEED-ISSUE",
            "p_reason": "Sample seed inventory"}
        if transaction["transaction_type"] == "receipt":
            batch = fixture_batches[original["p_batch_id"]]
            params.update(p_batch_number=batch["batch_number"], p_expiry_date=batch["expiry_date"])
        client.rpc("post_stock_transaction", params).execute()
    record["completed"] = True
    save_record(path, record)
    print(f"Seed complete: {len(model['categories'])} categories, {len(model['items'])} items, {len(model['transactions'])} stock transactions.")
    print(f"Facility: {record['facility_name']}")
    print(f"Login credentials saved to {path} (ignored by Git).")
    print("Re-running this command reuses the accounts and stock operation keys.")
    client.auth.sign_out({"scope": "local"})
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-cli", action="store_true", help="Use the logged-in CLI to obtain an admin key in memory.")
    args = parser.parse_args()
    try:
        seed_project(use_cli=args.use_cli)
    except Exception as error:
        print(f"Seed failed ({type(error).__name__}): {str(error)[:220]}", file=sys.stderr)
        raise SystemExit(1)
