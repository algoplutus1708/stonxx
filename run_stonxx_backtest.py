"""
run_stonxx_backtest.py
========================
Backtest runner for the AI/ML stonxx trader on Indian equities.

Backtest period: 2025-01-01 → 2025-12-31  (full OOS year)
Warm-up starts 2024-12-20 so the bot has enough bars to trade on day 1 of Jan 2025.
The model was trained exclusively on 2015-2024 data — genuine out-of-sample performance.

FEE & SLIPPAGE VERIFICATION (CRITICAL)
  • Brokerage fee  : TradingFee(flat_fee=20)     → flat ₹20 per order leg
  • Slippage       : TradingSlippage(amount=23)  → ~0.1% of ₹23,000 Nifty index per fill
  Both are applied symmetrically to buy AND sell legs.
"""

import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(".env.india")
load_dotenv(".secrets/lumi_secrets.env")

import pandas as pd
from lumibot.backtesting import PandasDataBacktesting
from lumibot.entities import Asset, Data, TradingFee, TradingSlippage
from lumibot.example_strategies.stonxx_india_bot import stonxx


def run_backtest():
    # ── True OOS window — model has NEVER seen this period ───────────────────
    # Warm-up starts Dec 20 so the model has ≥40 bars available from Jan 1.
    backtesting_start = datetime(2024, 12, 20)   # warm-up period start
    backtesting_end   = datetime(2025, 12, 31)   # full 2025 OOS window

    print("\n" + "=" * 65)
    print("  🚀  stonxx AI/ML Backtest — Indian Equities (2025 True OOS)")
    print("=" * 65)

    if not os.getenv("GEMINI_API_KEY"):
        print("[INFO] GEMINI_API_KEY not set — macro bias will default to NEUTRAL.")
        print("       All ML signals will be acted on (no LLM veto applied).\n")

    if not os.path.exists("nifty_xgb_model.joblib"):
        print("[CRITICAL] nifty_xgb_model.joblib not found!")
        print("           Run:  python train_nifty_model.py  first.\n")
        return

    # ── Fee & Slippage (VERIFIED) ─────────────────────────────────────────────
    # Flat ₹20 commission per order leg (Zerodha/Dhan standard for F&O/equity)
    trading_fee = TradingFee(flat_fee=20)

    # 0.1% market-impact slippage per fill.
    # At Nifty ≈ 23,000, 0.1% = ₹23 absolute price units per fill.
    # TradingSlippage takes an absolute amount in quote-currency units.
    trading_slippage = TradingSlippage(amount=23)

    # Load 15-minute CSV to bypass Yahoo limit
    df = pd.read_csv("data/NIFTY 50_15minute.csv")
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"date": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    df.sort_index(inplace=True)
    if df.index.tz is None:
        df = df.tz_localize("Asia/Kolkata")
        
    pandas_data = {
        Asset("NIFTY50", Asset.AssetType.INDEX): Data(Asset("NIFTY50", Asset.AssetType.INDEX), df.copy()),
        Asset("^NSEI", Asset.AssetType.INDEX): Data(Asset("^NSEI", Asset.AssetType.INDEX), df.copy())
    }
    
    stonxx.backtest(
        PandasDataBacktesting,
        pandas_data=pandas_data,
        backtesting_start=backtesting_start,
        backtesting_end=backtesting_end,

        # ₹1 crore starting capital — realistic for institutional/HNI
        budget=10_000_000,

        # Benchmark: NIFTY 50 index
        benchmark_asset=Asset("^NSEI", Asset.AssetType.INDEX),

        # Fee: ₹20 flat per leg
        buy_trading_fees=[trading_fee],
        sell_trading_fees=[trading_fee],

        # Slippage: 0.1% (₹23 absolute at 23,000 Nifty) per fill
        buy_trading_slippages=[trading_slippage],
        sell_trading_slippages=[trading_slippage],

        parameters={"universe": ["NIFTY50"]},
        name="stonxx",
        quiet_logs=False,
        show_plot=True,
        show_tearsheet=True,
        save_logfile=True,
    )


if __name__ == "__main__":
    run_backtest()
