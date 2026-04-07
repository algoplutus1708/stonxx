"""
run_india_live.py
=================
Live trading runner for the IndiaAITrader strategy via the Dhan broker.

Usage
-----
    # 1.  Fill in your credentials in .env.india
    # 2.  Run:
    python run_india_live.py

Pre-requisites
--------------
    pip install dhanhq pytz

Safety notes
-----------
* The default product type is MIS (intraday).  ALL positions will be
  closed by 15:15 IST, before the exchange auto-squareoff at ~15:20 IST.
* Start with a small capital allocation and monitor logs closely.
* Telegram alerts are sent on startup/shutdown if TELEGRAM_BOT_TOKEN is set.
"""

import os
import sys

from dotenv import load_dotenv

# ── Load secrets ────────────────────────────────────────────────────────────
load_dotenv(".env.india")
load_dotenv(".secrets/lumi_secrets.env")

# ── Imports ──────────────────────────────────────────────────────────────────
from lumibot.brokers import Dhan
from lumibot.data_sources.dhan_data import DhanData
from lumibot.entities.india_trading_fees import make_india_equity_fees
from lumibot.example_strategies.india_ai_trader import IndiaAITrader
from lumibot.traders import Trader

# ── Guards ────────────────────────────────────────────────────────────────────
CLIENT_ID    = os.getenv("DHAN_CLIENT_ID")
ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN")
GOOGLE_KEY   = os.getenv("GOOGLE_API_KEY")

missing = []
if not CLIENT_ID:    missing.append("DHAN_CLIENT_ID")
if not ACCESS_TOKEN: missing.append("DHAN_ACCESS_TOKEN")
if not GOOGLE_KEY:   missing.append("GOOGLE_API_KEY")

if missing:
    print(f"\n[ERROR] Missing environment variables: {', '.join(missing)}")
    print("Set them in .env.india before running live.\n")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────
RAW_UNIVERSE = os.getenv(
    "STRATEGY_UNIVERSE",
    "RELIANCE,INFY,TCS,HDFCBANK,ICICIBANK"
)
UNIVERSE     = [s.strip().upper() for s in RAW_UNIVERSE.split(",") if s.strip()]
PRODUCT_TYPE = os.getenv("PRODUCT_TYPE", "MIS").upper()
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
MAX_POSITIONS      = int(os.getenv("MAX_POSITIONS",       "5"))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))

# ── Optional Telegram alert ──────────────────────────────────────────────────
def _telegram_alert(msg: str):
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import urllib.request, urllib.parse, json as _json
        payload = _json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"[Telegram alert failed] {exc}")

# ── Build components ──────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print("  IndiaAITrader — LIVE NSE Trading")
print(f"{'='*65}")
print(f"  Universe  : {', '.join(UNIVERSE)}")
print(f"  Product   : {PRODUCT_TYPE}")
print(f"  Model     : {GOOGLE_MODEL}")
print(f"  Positions : max {MAX_POSITIONS}")
print(f"{'─'*65}")
print("  Fee model applied by live broker (NSE statutory charges):")
_buy_fees, _sell_fees = make_india_equity_fees(PRODUCT_TYPE, include_slippage=False)
for _label, _fee in [
    ("  BUY  market", _buy_fees[0]),
    ("  BUY  limit ", _buy_fees[1]),
    ("  SELL market", _sell_fees[0]),
    ("  SELL limit ", _sell_fees[1]),
]:
    _bd = _fee.breakdown()
    print(
        f"{_label}  effective={_bd['effective_cost_pct']:.5f}%"
        f"  (brkr={_bd['brokerage_inr']:.2f}"
        f"  STT={_bd['stt_inr']:.2f}"
        f"  GST={_bd['gst_inr']:.2f}  on ₹{_bd['turnover_inr']:.0f})"
    )
print(f"{'='*65}\n")

# Data source — uses Yahoo Finance for historical + Dhan for live quotes
data_source = DhanData(
    client_id             = CLIENT_ID,
    access_token          = ACCESS_TOKEN,
    use_yfinance_historical = True,
    default_exchange      = "NSE",
)

# Broker — full live execution via Dhan API
broker = Dhan(
    client_id            = CLIENT_ID,
    access_token         = ACCESS_TOKEN,
    default_product_type = PRODUCT_TYPE,
    data_source          = data_source,
)

# Strategy
strategy = IndiaAITrader(
    broker     = broker,
    parameters = {
        "universe":           UNIVERSE,
        "product_type":       PRODUCT_TYPE,
        "risk_per_trade_pct": RISK_PER_TRADE_PCT,
        "max_positions":      MAX_POSITIONS,
        "google_model":       GOOGLE_MODEL,
    },
)

# ── Start ─────────────────────────────────────────────────────────────────────
_telegram_alert(
    f"🚀 IndiaAITrader STARTED\n"
    f"Universe: {', '.join(UNIVERSE)}\n"
    f"Product: {PRODUCT_TYPE} | Model: {GOOGLE_MODEL}"
)

trader = Trader()
trader.add_strategy(strategy)

try:
    trader.run_all()
finally:
    _telegram_alert("🛑 IndiaAITrader STOPPED")
    print("\n[Live session ended]")
