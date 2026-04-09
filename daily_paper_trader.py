"""
daily_paper_trader.py
=====================
Execution runner for the stonxx (NiftySwingAlpha) strategy in paper-trading mode.

Usage:
    python daily_paper_trader.py

Prerequisites:
    1. Populate .env.india with DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN.
    2. Ensure nifty_xgb_model.joblib is present in the project root.
    3. Run:  pip install python-dotenv
"""

import os
import sys

from dotenv import load_dotenv

# ── 1. Load environment variables ─────────────────────────────────────────────
ENV_PATH = ".env.india"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)
    print(f"[stonxx] Loaded credentials from '{ENV_PATH}'.")
else:
    print(f"[stonxx] CRITICAL: '{ENV_PATH}' not found. Please create it from the template.")
    sys.exit(1)

# ── 2. Validate required credentials ──────────────────────────────────────────
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")

if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
    print("[stonxx] CRITICAL: DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN is missing from the environment.")
    sys.exit(1)

# ── 3. LumiBot imports ────────────────────────────────────────────────────────
from lumibot.brokers import Dhan
from lumibot.traders import Trader
from lumibot.example_strategies.stonxx_india_bot import stonxx as NiftySwingAlpha


# ── 4. Main entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("   STONXX — NiftySwingAlpha Paper Trader")
    print("=" * 60)

    # 4a. Broker — paper_trade=True ensures no real orders are sent
    broker = Dhan(
        client_id=DHAN_CLIENT_ID,
        access_token=DHAN_ACCESS_TOKEN,
        paper_trade=True,
    )

    # 4b. Strategy — use universe from env if provided, else fall back to default
    universe_raw = os.getenv("STRATEGY_UNIVERSE", "")
    universe = [s.strip() for s in universe_raw.split(",") if s.strip()] or None

    strategy_params = {}
    if universe:
        strategy_params["universe"] = universe
        print(f"[stonxx] Trading universe (from env): {universe}")
    else:
        print("[stonxx] Using default trading universe defined in strategy.")

    strategy = NiftySwingAlpha(
        broker=broker,
        parameters=strategy_params,
    )

    # 4c. Trader — orchestrates the strategy event loop
    trader = Trader()
    trader.add_strategy(strategy)

    print("[stonxx] Starting paper-trading session. Press Ctrl+C to stop.\n")
    trader.run_all()
