"""
run_ensemble_live.py
====================
Live trading runner specifically designed for the AI/ML Ensemble trader.
This connects your Dhan API to the EnsembleTrader strategy to execute
trades in real time.
"""

import os
import sys
from dotenv import load_dotenv

# Load credentials
load_dotenv(".env.india")
load_dotenv(".secrets/lumi_secrets.env")

# Ensure required libraries are imported
from lumibot.brokers import Dhan
from lumibot.data_sources.dhan_data import DhanData
from lumibot.example_strategies.ensemble_india_bot import EnsembleTrader
from lumibot.traders import Trader

def run_live():
    print("\n" + "="*60)
    print("🚀 Running AI/ML Ensemble Live on Dhan (Indian Equities)")
    print("="*60)

    # 1. Fetch Environment Variables
    CLIENT_ID    = os.getenv("DHAN_CLIENT_ID")
    ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")
    GEMINI_KEY   = os.getenv("GEMINI_API_KEY")

    # 2. Safety Guards
    missing = []
    if not CLIENT_ID:    missing.append("DHAN_CLIENT_ID")
    if not ACCESS_TOKEN: missing.append("DHAN_ACCESS_TOKEN")
    
    if missing:
        print(f"[ERROR] Missing required broker credentials: {', '.join(missing)}")
        print("Please add them to your .env.india file before running live.\n")
        sys.exit(1)

    if not GEMINI_KEY:
        print("[WARNING] GEMINI_API_KEY is missing. Gemini macro veto logic will NOT function.")
    else:
        print("[OK] Gemini AI integrated for daily risk management.")

    if not os.path.exists("nifty_xgb_model.joblib"):
        print("[CRITICAL ERROR] nifty_xgb_model.joblib is missing!")
        print("You cannot trade live without the compiled machine learning model. Exiting.")
        sys.exit(1)

    # 3. Component Setup
    print("\nInitializing Dhan Data Source and Broker...")
    
    data_source = DhanData(
        client_id=CLIENT_ID,
        access_token=ACCESS_TOKEN,
        use_yfinance_historical=True,  # Backwards fallback for historical bars
        default_exchange="NSE",
    )

    broker = Dhan(
        client_id=CLIENT_ID,
        access_token=ACCESS_TOKEN,
        default_product_type="MIS",    # Strongly relying on MIS for algorithmic discipline
        data_source=data_source,
    )

    # 4. Strategy Initialization
    print("Mounting EnsembleTrader Strategy...")
    strategy = EnsembleTrader(
        broker=broker,
        parameters={},
    )

    # 5. Connect and Execute
    trader = Trader()
    trader.add_strategy(strategy)

    try:
        print("\n🟢 Connecting to live exchange... Press Ctrl+C to abort.")
        trader.run_all()
    except KeyboardInterrupt:
        print("\n🛑 Live session safely aborted by user.")

if __name__ == "__main__":
    run_live()
