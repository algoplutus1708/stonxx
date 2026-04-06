"""
run_india_backtest.py
=====================
Backtest runner for the IndiaAITrader strategy on NSE-listed equities.

Usage
-----
    # 1.  Copy .env.india.example → .env.india and fill in your keys
    # 2.  Run:
    python run_india_backtest.py

Environment
-----------
    GOOGLE_API_KEY    — required for the Gemini AI agent
    DHAN_CLIENT_ID    — optional for DhanData (omit to use pure Yahoo Finance)
    DHAN_ACCESS_TOKEN — optional for DhanData

The backtest uses Yahoo Finance historical data (free, no Dhan credentials needed).
Brokerage fees default to ₹20 flat per trade (Zerodha / Dhan style).
"""

import os
from datetime import datetime

from dotenv import load_dotenv

# ── Load secrets ────────────────────────────────────────────────────────────
load_dotenv(".env.india")
load_dotenv(".secrets/lumi_secrets.env")

# ── Imports ──────────────────────────────────────────────────────────────────
from lumibot.backtesting import YahooDataBacktesting
from lumibot.entities import Asset, TradingFee
from lumibot.example_strategies.india_ai_trader import IndiaAITrader

# ── Guard ─────────────────────────────────────────────────────────────────────
if not os.getenv("GOOGLE_API_KEY"):
    print(
        "\n[ERROR] GOOGLE_API_KEY is not set.\n"
        "The IndiaAITrader uses Gemini AI for decision making.\n"
        "Get a free key from: https://aistudio.google.com/apikey\n"
        "Then add it to your .env.india file:\n"
        "    GOOGLE_API_KEY=your_key_here\n"
    )
    raise SystemExit(1)

# ── Configuration ─────────────────────────────────────────────────────────────

# Date range (edit freely)
BACKTEST_START = datetime(2025, 1, 1)
BACKTEST_END   = datetime(2025, 4, 1)

# Universe — comma-separated NSE symbols in .env.india, or override here
RAW_UNIVERSE = os.getenv(
    "STRATEGY_UNIVERSE",
    "RELIANCE,INFY,TCS,HDFCBANK,ICICIBANK,SBIN,BHARTIARTL,ITC"
)
UNIVERSE = [s.strip().upper() for s in RAW_UNIVERSE.split(",") if s.strip()]

# Product type: MIS (intraday) or CNC (delivery)
PRODUCT_TYPE = os.getenv("PRODUCT_TYPE", "MIS").upper()

# Risk management
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS",       "5"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))

# Gemini model (gemini-2.0-flash = fast + cost-effective)
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")

# Brokerage fees — Zerodha / Dhan flat ₹20 per order ≈ 0.03 % on ₹70k trade
# Represented as 0.03 % percent fee per trade
TRADING_FEE = TradingFee(percent_fee=0.0003)

# ── Run ──────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("  IndiaAITrader — NSE Backtest")
print(f"{'='*60}")
print(f"  Period  : {BACKTEST_START.date()} → {BACKTEST_END.date()}")
print(f"  Universe: {', '.join(UNIVERSE)}")
print(f"  Product : {PRODUCT_TYPE}")
print(f"  Model   : {GOOGLE_MODEL}")
print(f"{'='*60}\n")

results = IndiaAITrader.backtest(
    YahooDataBacktesting,
    backtesting_start = BACKTEST_START,
    backtesting_end   = BACKTEST_END,

    # Nifty 50 index as benchmark — ^NSEI on Yahoo Finance
    benchmark_asset   = Asset("^NSEI", Asset.AssetType.INDEX),

    # Trading fees (applied to both buys and sells)
    buy_trading_fees  = [TRADING_FEE],
    sell_trading_fees = [TRADING_FEE],

    # Strategy parameters
    parameters = {
        "universe":              UNIVERSE,
        "product_type":          PRODUCT_TYPE,
        "risk_per_trade_pct":    RISK_PER_TRADE_PCT,
        "max_positions":         MAX_POSITIONS,
        "google_model":          GOOGLE_MODEL,
        "agent_run_every_n_bars": 1,
    },

    name       = "IndiaAITrader_NSE",
    quiet_logs = False,
)

print("\n[Backtest complete]  Check reports/ and logs/ for tearsheet + details.")
