"""
daily_paper_trader.py
=====================
Execution runner for the stonxx (NiftySwingAlpha) strategy in paper-trading mode.

Usage:
    python daily_paper_trader.py

Prerequisites:
    1. Populate .env.india with DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN.
    2. Ensure stonxx_daily_panel_model.joblib is present in the project root.
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
from lumibot.data_sources import DhanData
from lumibot.traders import Trader
from lumibot.example_strategies.stonxx_india_bot import stonxx as NiftySwingAlpha


# ── 4. Main entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("   STONXX — Daily Swing Paper Trader")
    print("=" * 60)

    # 4a. Data source — DhanData uses Yahoo Finance for historical bars
    #     (cost-free, no Dhan subscription required for price history)
    data_source = DhanData(
        client_id=DHAN_CLIENT_ID,
        access_token=DHAN_ACCESS_TOKEN,
        use_yfinance_historical=True,
    )

    # 4b. Broker — must receive data_source explicitly
    # Note: Dhan has no paper_trade flag; paper trading is enforced inside
    # stonxx via IS_PAPER_TRADING=True, which skips real order submission
    # and logs simulated trades to paper_trades.csv instead.
    broker = Dhan(
        client_id=DHAN_CLIENT_ID,
        access_token=DHAN_ACCESS_TOKEN,
        default_product_type=os.getenv("PRODUCT_TYPE", "CNC"),
        data_source=data_source,
    )

    # 4b. Strategy
    # IS_PAPER_TRADING=True in parameters forces the strategy into paper mode:
    # orders are logged to paper_trades.csv; nothing is sent to Dhan.
    universe_raw = os.getenv("STRATEGY_UNIVERSE", "")
    universe = [s.strip() for s in universe_raw.split(",") if s.strip()] or None

    strategy_params = {
        "IS_PAPER_TRADING": True,
        "model_path": "stonxx_daily_panel_model.joblib",
        "minimum_predicted_return": 0.01,
        "risk_budget_pct": 0.01,
        "max_position_pct": 0.10,
        "max_positions": int(os.getenv("MAX_POSITIONS", "3")),
    }
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

    print("[stonxx] Daily model: stonxx_daily_panel_model.joblib")
    print("[stonxx] Signal generation runs after the close; queued orders execute next session.\n")
    print("[stonxx] Starting paper-trading session. Press Ctrl+C to stop.\n")
    trader.run_all()
