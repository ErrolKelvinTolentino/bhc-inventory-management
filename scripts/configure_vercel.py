"""Configure the linked production project without printing secret values."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
from scripts.seed_supabase import get_admin_key

PROJECT = "bhc-inventory"
SCOPE = "inaagapay"
ORIGIN = "https://bhc-inventory.vercel.app"


def cli(arguments, value=None):
    result = subprocess.run(["npx.cmd" if os.name == "nt" else "npx", "--yes", "vercel", *arguments,
        "--scope", SCOPE], cwd=ROOT, input=value, capture_output=True, text=True)
    if result.returncode:
        # CLI output may contain values: fail without dumping it or command input.
        raise RuntimeError("Vercel command failed: " + " ".join(arguments[:3]))
    return result.stdout


def configure():
    link = json.loads((ROOT / ".vercel" / "project.json").read_text())
    project = json.loads(cli(["api", "/v9/projects/" + PROJECT, "--raw"]))
    if link["projectId"] != project["id"] or project["link"]["repo"] != ROOT.name or project["link"]["org"] != "ErrolKelvinTolentino":
        raise ValueError("The linked Vercel project does not match the authorized GitHub repository.")
    local = dotenv_values(ROOT / ".env")
    source = json.loads(cli(["env", "list", "--environment", "production", "--json"]))
    entries = source if isinstance(source, list) else source.get("envs", source.get("env", []))
    existing = {entry["key"]: entry for entry in entries}
    values = {"SUPABASE_URL": local["SUPABASE_URL"], "SUPABASE_PUBLISHABLE_KEY": local["SUPABASE_PUBLISHABLE_KEY"],
        "APP_URL": ORIGIN, "SESSION_BACKEND": "supabase", "COOKIE_SECURE": "1", "APP_TIMEZONE": "Asia/Manila"}
    if "SUPABASE_SECRET_KEY" not in existing:
        values["SUPABASE_SECRET_KEY"] = get_admin_key("hmapfyndwrvsapllythc", use_cli=True)
    if "SECRET_KEY" not in existing:
        # Vercel keeps the generated value encrypted; no local copy is necessary.
        values["SECRET_KEY"] = secrets.token_hex(32)
    private = {"SUPABASE_SECRET_KEY", "SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY"}
    for name, value in values.items():
        if name in existing:
            print(f"Preserved existing production variable: {name}", flush=True)
            continue
        cli(["env", "add", name, "--environment", "production", "--yes",
            "--sensitive" if name in private else "--no-sensitive"], value=value)
        print(f"Configured production variable: {name}", flush=True)
    print("Production environment configured. Secret values were not printed or written to source files.")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    configure()
