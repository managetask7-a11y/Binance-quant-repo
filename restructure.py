import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

OLD_FILES = [
    "live_multi_trader.py",
    "LIVE_TRADER.bat",
    "LIVE_TRADING_GUIDE.md",
]

def main():
    print("=" * 60)
    print("  AZALYST ALPHA X — PROJECT RESTRUCTURE")
    print("=" * 60)
    print()

    deleted = 0
    for filename in OLD_FILES:
        filepath = BASE_DIR / filename
        if filepath.exists():
            os.remove(filepath)
            print(f"  DELETED: {filename}")
            deleted += 1
        else:
            print(f"  SKIPPED: {filename} (not found)")

    print()
    print(f"  Removed {deleted} old file(s).")
    print()

    new_structure = [
        "azalyst/__init__.py",
        "azalyst/config.py",
        "azalyst/logger.py",
        "azalyst/indicators.py",
        "azalyst/consensus.py",
        "azalyst/trader.py",
        "azalyst/notifications.py",
        "azalyst/strategies/__init__.py",
        "azalyst/strategies/zamco.py",
        "azalyst/strategies/bnf.py",
        "azalyst/strategies/jadecap.py",
        "azalyst/strategies/marci.py",
        "azalyst/strategies/nbb.py",
        "azalyst/strategies/umar.py",
        "azalyst/strategies/kane.py",
        "azalyst/dashboard/__init__.py",
        "azalyst/dashboard/server.py",
        "azalyst/dashboard/templates/index.html",
        "azalyst/dashboard/static/style.css",
        "azalyst/dashboard/static/app.js",
        "run.py",
        "requirements.txt",
        "README.md",
    ]

    print("  Verifying new structure:")
    all_ok = True
    for f in new_structure:
        fp = BASE_DIR / f
        status = "OK" if fp.exists() else "MISSING"
        if status == "MISSING":
            all_ok = False
        print(f"    [{status}] {f}")

    print()
    if all_ok:
        print("  All files present. Restructure complete!")
    else:
        print("  WARNING: Some files are missing.")

    print()
    print("  Usage:")
    print("    python run.py --dry-run --api-key KEY --api-secret SECRET")
    print("    Dashboard: http://localhost:8080")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
