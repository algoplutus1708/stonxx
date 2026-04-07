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

Fee model
---------
Uses ``make_india_equity_fees`` which hardcodes all NSE statutory costs:

    MIS (intraday)
    ─────────────
    • Brokerage        : ₹20 or 0.03 % (whichever lower per order)
    • STT              : 0.025 % on sell side
    • Exchange charges : 0.00345 % (NSE equity cash segment)
    • GST              : 18 % on (brokerage + exchange charges)
    • SEBI fee         : ₹10 per crore (0.0001 %)
    • Stamp duty       : 0.003 % on buy side
    • Slippage penalty : 0.05 % on market orders (taker only)

    CNC (delivery)
    ──────────────
    • Brokerage        : ₹0 (free)
    • STT              : 0.1 % on both sides
    • Exchange charges : 0.00345 %
    • GST              : 18 % on exchange charges
    • SEBI fee         : ₹10 per crore
    • Stamp duty       : 0.015 % on buy side
    • Slippage penalty : 0.05 % on market orders (taker only)
"""

import os
from datetime import datetime

from dotenv import load_dotenv

# ── Load secrets ─────────────────────────────────────────────────────────────
load_dotenv(".env.india")
load_dotenv(".secrets/lumi_secrets.env")

# ── Imports ───────────────────────────────────────────────────────────────────
from lumibot.backtesting import YahooDataBacktesting
from lumibot.entities import Asset
from lumibot.entities.india_trading_fees import make_india_equity_fees
from lumibot.example_strategies.india_ai_trader import IndiaAITrader

# ── Guard ──────────────────────────────────────────────────────────────────────
if not os.getenv("GOOGLE_API_KEY"):
    print(
        "\n[ERROR] GOOGLE_API_KEY is not set.\n"
        "The IndiaAITrader uses Gemini AI for decision making.\n"
        "Get a free key from: https://aistudio.google.com/apikey\n"
        "Then add it to your .env.india file:\n"
        "    GOOGLE_API_KEY=your_key_here\n"
    )
    raise SystemExit(1)

# ── Configuration ──────────────────────────────────────────────────────────────

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

# Exchange (NSE or BSE)
EXCHANGE = os.getenv("EXCHANGE", "NSE").upper()

# Risk management
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS",       "5"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))

# Gemini model (gemini-2.0-flash = fast + cost-effective)
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")

# ── Indian market fee model ───────────────────────────────────────────────────
# Returns two lists: buy_fees and sell_fees.
# Each list has a taker object (market orders + slippage) and a maker object
# (limit orders, no slippage). Lumibot selects the right object per order type.
buy_fees, sell_fees = make_india_equity_fees(
    product_type      = PRODUCT_TYPE,
    exchange          = EXCHANGE,
    include_slippage  = True,         # 0.05 % penalty on market orders
)

# ── Startup summary ────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("  IndiaAITrader — NSE Backtest")
print(f"{'='*65}")
print(f"  Period  : {BACKTEST_START.date()} → {BACKTEST_END.date()}")
print(f"  Universe: {', '.join(UNIVERSE)}")
print(f"  Product : {PRODUCT_TYPE}  |  Exchange : {EXCHANGE}")
print(f"  Model   : {GOOGLE_MODEL}")
print(f"{'─'*65}")
print("  Fee model (Indian regulatory charges):")
for label, fee_obj in [
    ("  BUY  market ", buy_fees[0]),
    ("  BUY  limit  ", buy_fees[1]),
    ("  SELL market ", sell_fees[0]),
    ("  SELL limit  ", sell_fees[1]),
]:
    bd = fee_obj.breakdown()
    print(
        f"  {label}  effective={bd['effective_cost_pct']:.5f}%"
        f"  (brokerage={bd['brokerage_inr']:.2f}"
        f"  STT={bd['stt_inr']:.2f}"
        f"  GST={bd['gst_inr']:.2f}"
        f"  slip={bd['slippage_penalty_inr']:.2f}  on ₹{bd['turnover_inr']:.0f})"
    )
print(f"{'='*65}\n")

# ── Run ────────────────────────────────────────────────────────────────────────
results = IndiaAITrader.backtest(
    YahooDataBacktesting,
    backtesting_start = BACKTEST_START,
    backtesting_end   = BACKTEST_END,

    # Nifty 50 index as benchmark — ^NSEI on Yahoo Finance
    benchmark_asset   = Asset("^NSEI", Asset.AssetType.INDEX),

    # Indian statutory fees + slippage applied to every fill
    buy_trading_fees  = buy_fees,
    sell_trading_fees = sell_fees,

    # Strategy parameters
    parameters = {
        "universe":               UNIVERSE,
        "product_type":           PRODUCT_TYPE,
        "risk_per_trade_pct":     RISK_PER_TRADE_PCT,
        "max_positions":          MAX_POSITIONS,
        "google_model":           GOOGLE_MODEL,
        "agent_run_every_n_bars": 1,
    },

    name       = "IndiaAITrader_NSE",
    quiet_logs = False,
)

print("\n[Backtest complete]  Check reports/ and logs/ for tearsheet + details.")
