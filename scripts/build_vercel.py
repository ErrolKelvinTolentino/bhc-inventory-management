"""Copy local CSS/JS/icons into Vercel's public CDN directory at build time."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = ROOT / "inventory" / "static"
    destination = ROOT / "public" / "static"
    shutil.copytree(source, destination, dirs_exist_ok=True)
    print("Prepared public/static assets for Vercel.")


if __name__ == "__main__":
    build()
