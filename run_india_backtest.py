import os
from datetime import datetime
from dotenv import load_dotenv
from lumibot.example_strategies.india_ai_momentum import IndiaAIMomentum
from lumibot.data_sources.dhan_data import DhanData
from lumibot.brokers import Dhan

# 1. Load Secrets and Config
load_dotenv(".env.india")
load_dotenv(".secrets/lumi_secrets.env")

# 2. Get Credentials
CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")

# 3. Setup Strategy
backtesting_start = datetime(2025, 1, 1)
backtesting_end = datetime(2025, 4, 1)

# 4. Execute Backtest
IndiaAIMomentum.backtest(
    DhanData,
    backtesting_start,
    backtesting_end,
    # Source initialization parameters
    client_id=CLIENT_ID,
    access_token=ACCESS_TOKEN,
    use_yfinance_historical=True,
    # Parameters for strategy
    symbol="RELIANCE",
    quantity=10,
    name="NSE_Backtest_Reliance"
)
