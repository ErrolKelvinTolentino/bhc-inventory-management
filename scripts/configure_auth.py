"""Add app callback URLs, preserving all other Supabase Auth configuration."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PROJECT_REF = "hmapfyndwrvsapllythc"


def cli(arguments, workdir=None):
    command = ["npx.cmd" if os.name == "nt" else "npx", "--yes", "supabase", *arguments]
    if workdir:
        command.extend(["--workdir", str(workdir)])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def configure(origins, apply=False, set_site_url=False):
    if set_site_url and len(origins) != 1:
        raise ValueError("Choose one canonical origin when setting the Auth Site URL.")
    urls = []
    for origin in origins:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Provide an HTTP(S) origin without a path, credentials, query, or fragment.")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            raise ValueError("Non-local application URLs must use HTTPS.")
        urls.append(origin.rstrip("/") + "/auth/callback/**")
    preview = cli(["config", "pull", "--project-ref", PROJECT_REF, "--dry-run", "--output-format", "json"])
    redirect = next(c for c in preview["changes"] if c["path"] == ["auth", "additional_redirect_urls"])
    existing = redirect["remote"] or []
    allowed = list(dict.fromkeys([*existing, *urls]))
    folder = ROOT / "instance" / "auth-config"
    config = folder / "supabase" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    # Sparse config: only this explicitly declared property is pushed. Never push
    # generated local Auth defaults over the remote project's security settings.
    source = 'project_id = "bhc-inventory-management"\n[auth]\nadditional_redirect_urls = ' + json.dumps(allowed) + '\n'
    if set_site_url:
        source += 'site_url = ' + json.dumps(origins[0].rstrip('/')) + '\n'
    config.write_text(source, encoding="utf-8")
    difference = cli(["config", "diff", "--project-ref", PROJECT_REF, "--output-format", "json"], folder)
    changes = difference.get("changes", [])
    permitted = {("auth", "additional_redirect_urls")}
    if set_site_url:
        permitted.add(("auth", "site_url"))
    unexpected = [c for c in changes if c.get("class") == "update" and tuple(c.get("path", [])) not in permitted]
    if unexpected:
        raise ValueError("Refusing to push unrelated Auth configuration changes.")
    if apply:
        cli(["config", "push", "--project-ref", PROJECT_REF, "--yes", "--output-format", "json"], folder)
    print("Auth callback URLs " + ("configured:" if apply else "prepared (dry run):"))
    for url in urls:
        print(f"  {url}")
    if set_site_url:
        print("Auth Site URL: " + origins[0].rstrip('/'))
    print("Existing redirect URLs and unrelated Auth settings are preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--set-site-url", action="store_true")
    args = parser.parse_args()
    configure(args.origin, args.apply, args.set_site_url)
