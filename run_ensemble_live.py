"""
Ensemble AI Trading Agent - Live Execution Runner
--------------------------------------------------
This script initializes the Ensemble AI strategy with live Dhan broker 
connectivity for the Indian Stock Market (NSE/BSE).

Prerequisites:
1. Ensure .env.india is populated with:
   - DHAN_CLIENT_ID
   - DHAN_ACCESS_TOKEN
   - GOOGLE_API_KEY
2. Ensure nifty_xgb_model.joblib is present in the root directory.
"""

import os
from dotenv import load_dotenv
from lumibot.brokers import Dhan
from lumibot.data_sources import DhanData
from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset
from lumibot.example_strategies.ensemble_india_bot import EnsembleTrader

def main():
    # 1. Load environment variables from .env.india
    env_path = ".env.india"
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"Loaded credentials from {env_path}")
    else:
        print(f"CRITICAL: {env_path} not found. Please create it from the template.")
        return

    # 2. Extract credentials
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
    
    if not client_id or not access_token:
        print("CRITICAL: Missing DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN in environment.")
        return

    # 3. Initialize the Data Source (Live DhanData)
    # By default, use_yfinance_historical=True for cost optimization
    data_source = DhanData(
        client_id=client_id,
        access_token=access_token,
        use_yfinance_historical=True
    )

    # 4. Initialize the Broker (Live Dhan)
    # default_product_type="INTRA" (MIS) for intraday trading
    broker = Dhan(
        client_id=client_id,
        access_token=access_token,
        default_product_type="INTRA",
        data_source=data_source
    )

    # 5. Initialize the Strategy
    # We use a default budget of ₹25,00,000 for position sizing (mock balance for live logic)
    strategy = EnsembleTrader(
        broker=broker,
        data_source=data_source,
        budget=2500000,
        quote_asset=Asset(symbol="INR", asset_type="forex")
    )

    # 6. Run the strategy live
    print("Starting Ensemble AI Agent in LIVE mode...")
    print("Market Hours: 09:15 - 15:30 IST (Mon-Fri)")
    
    try:
        # run_live() handles the main execution loop
        strategy.run_live()
    except KeyboardInterrupt:
        print("\nShutdown signal received. Closing connections...")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    main()
