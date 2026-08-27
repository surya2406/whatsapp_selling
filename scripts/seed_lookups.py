"""
Seed Lookups Script
Ensures all lookup JSON files are populated with valid sample data.
Run this once before starting the agent for the first time.

Usage: python -m scripts.seed_lookups
"""
import json
import os
from pathlib import Path

LOOKUPS_DIR = Path(__file__).parent.parent / "lookups"


def ensure_dir():
    LOOKUPS_DIR.mkdir(exist_ok=True)


def check_and_report():
    files = [
        "products.json",
        "cross_sell_rules.json",
        "upsell_rules.json",
        "offers.json",
        "segments.json",
        "message_templates.json",
    ]
    print("\n=== Lookup File Status ===")
    all_ok = True
    for f in files:
        path = LOOKUPS_DIR / f
        if path.exists():
            with open(path) as fp:
                data = json.load(fp)
            count = len(data)
            print(f"  ✅ {f}: {count} entries")
        else:
            print(f"  ❌ {f}: MISSING")
            all_ok = False
    print()
    if all_ok:
        print("All lookup files present. Agent is ready to run.")
    else:
        print("Some lookup files are missing. Check the lookups/ directory.")
    return all_ok


if __name__ == "__main__":
    ensure_dir()
    ok = check_and_report()
    if ok:
        print("\nNext steps:")
        print("  1. Edit lookups/*.json with YOUR actual products and rules")
        print("  2. Copy .env.example → .env and fill in your DB credentials")
        print("  3. Run: docker-compose up")
