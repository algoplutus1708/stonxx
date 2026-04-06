"""
run_ensemble_backtest.py
========================
Backtest runner specifically designed for the AI/ML Ensemble trader.
This tests how the strategy would have performed on historical data,
including the simulated Gemini LLM macro bias logic.
"""

import os
from datetime import datetime
from dotenv import load_dotenv

# Load credentials (for Gemini API)
load_dotenv(".env.india")
load_dotenv(".secrets/lumi_secrets.env")

# Ensure required libraries are imported
from lumibot.backtesting import YahooDataBacktesting
from lumibot.entities import Asset, TradingFee
from lumibot.example_strategies.ensemble_india_bot import EnsembleTrader

def run_backtest():
    # Trading period
    backtesting_start = datetime(2025, 1, 1)
    backtesting_end   = datetime(2025, 4, 1)

    print("\n" + "="*60)
    print("🚀 Running AI/ML Ensemble Backtest for Indian Equities")
    print("="*60)
    
    if not os.getenv("GEMINI_API_KEY"):
        print("[WARNING] GEMINI_API_KEY is not set.")
        print("The daily macro bias will blindly default to NEUTRAL.")
        print("To test the LLM veto logic, add your key to .env.india\n")
    
    if not os.path.exists("nifty_xgb_model.joblib"):
        print("[WARNING] nifty_xgb_model.joblib is missing!")
        print("The XGBoost predictions will return 0 (Hold).")
        print("You must train and save your model to fully utilize this strategy.\n")

    # Define standard Indian Brokerage fee (e.g., Zerodha flat ₹20 approx simplified to 0.03%)
    trading_fee = TradingFee(percent_fee=0.0003)

    # Initialize and run
    EnsembleTrader.backtest(
        YahooDataBacktesting,
        backtesting_start=backtesting_start,
        backtesting_end=backtesting_end,
        
        # Benchmark against the NIFTY 50 index
        benchmark_asset=Asset("^NSEI", Asset.AssetType.INDEX),
        
        buy_trading_fees=[trading_fee],
        sell_trading_fees=[trading_fee],
        
        # We don't need the universe/agent param dictionary for this particular strategy 
        # as it is hardcoded to trade the NIFTY ETF in its on_trading_iteration.
        parameters={},
        
        name="Ensemble_India_Trader_Backtest",
        quiet_logs=False,       # Set to True to reduce console spam
        show_plot=True,         # Show the tearsheet at the end
    )

if __name__ == "__main__":
    run_backtest()
