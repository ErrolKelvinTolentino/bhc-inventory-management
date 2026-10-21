"""Remove only the labeled sample staff login, preserving historical attribution."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory import create_app
from supabase import create_client
from supabase_auth.errors import AuthApiError
from scripts.seed_supabase import get_admin_key, save_record, SEED_TAG


def remove(use_cli=False):
    path = ROOT / "instance" / "seed-credentials.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    config = create_app().config
    client = create_client(config["SUPABASE_URL"], get_admin_key(record["project_ref"], use_cli))
    staff = record["accounts"].get("staff")
    if not staff:
        print("No sample staff credential remains. Nothing to remove.")
        return
    user = client.auth.admin.get_user_by_id(staff["user_id"]).user
    if user.email != "staff@seed.bhc-inventory.test" or user.app_metadata.get("inventory_seed") != SEED_TAG:
        raise ValueError("Refusing to remove an account without the expected sample identity.")
    memberships = client.table("facility_memberships").select("role").eq("user_id", user.id).execute().data
    if memberships:
        raise ValueError("Apply the administrators-only migration first; it removes staff access.")
    client.auth.admin.delete_user(user.id, should_soft_delete=True)
    public = create_client(config["SUPABASE_URL"], config["SUPABASE_PUBLISHABLE_KEY"])
    try:
        public.auth.sign_in_with_password({"email": staff["email"], "password": staff["password"]})
    except AuthApiError:
        pass
    else:
        raise AssertionError("Removed staff credentials unexpectedly still work.")
    record["removed_staff_user_id"] = staff["user_id"]
    record["accounts"].pop("staff")
    save_record(path, record)
    print("Sample staff login removed; sign-in rejected. Inventory and history preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-cli", action="store_true")
    remove(parser.parse_args().use_cli)
