"""
lumibot/example_strategies/india_ai_trader.py
===============================================
Production-grade AI Algo Trading Agent for the Indian Stock Market (NSE/BSE).

This strategy uses LumiBot's native ``agents`` framework (Gemini-backed) to make
all trading decisions.  The AI agent is given a rich set of ``@agent_tool``
functions covering:

  * NSE / BSE price bars  (via DhanData → Yahoo Finance .NS/.BO)
  * Nifty 50 top movers   (via yfinance)
  * Indian market news    (via Economic Times RSS feed – free, no key)
  * Technical signals     (Supertrend + session VWAP)
  * Portfolio state       (cash, positions, P&L)

Session management
------------------
* ``sleeptime = "15 minutes"`` — bar-aligned intraday cycle
* Market hours guard in ``on_trading_iteration``
* MIS forced square-off at 15:15 IST via ``before_market_closes``

Usage
-----
Backtest::

    python run_india_backtest.py

Live::

    python run_india_live.py

Environment variables
---------------------
* ``GOOGLE_API_KEY``      — Gemini API key (required)
* ``DHAN_CLIENT_ID``      — Dhan broker client ID (live only)
* ``DHAN_ACCESS_TOKEN``   — Dhan broker access token (live only)
* ``STRATEGY_UNIVERSE``   — comma-separated NSE symbols, e.g. ``RELIANCE,INFY,TCS``
* ``PRODUCT_TYPE``        — ``MIS`` (default) or ``CNC``
* ``GOOGLE_MODEL``        — Gemini model name (default: ``gemini-2.0-flash``)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from lumibot.components.agents import agent_tool
from lumibot.entities import Asset, TradingFee
from lumibot.strategies.strategy import Strategy

# ---------------------------------------------------------------------------
# Default universe — top Nifty 50 stocks  (override via STRATEGY_UNIVERSE)
# ---------------------------------------------------------------------------

DEFAULT_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE",
    "HCLTECH", "SUNPHARMA", "TITAN", "WIPRO", "ULTRACEMCO",
]

# NSE / BSE market hours (IST)
_MARKET_OPEN_HH_MM   = (9, 15)
_MARKET_CLOSE_HH_MM  = (15, 30)
_MIS_SQUAREOFF_HH_MM = (15, 15)   # forced close before exchange auto-squareoff


def _ist_now() -> datetime:
    """Return current wall-clock time in IST."""
    try:
        import pytz
        return datetime.now(pytz.timezone("Asia/Kolkata"))
    except ImportError:
        from datetime import timezone, timedelta
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _is_market_open_ist() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    hm = (now.hour, now.minute)
    return _MARKET_OPEN_HH_MM <= hm < _MARKET_CLOSE_HH_MM


def _is_mis_squareoff_time() -> bool:
    now = _ist_now()
    return (now.hour, now.minute) >= _MIS_SQUAREOFF_HH_MM


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class IndiaAITrader(Strategy):
    """
    AI-powered intraday/swing trading strategy for NSE/BSE.

    Parameters (passed via ``parameters`` dict in ``backtest()`` / ``Trader``)
    ----------
    universe : list[str]
        List of NSE ticker symbols (without .NS suffix).
    product_type : str
        ``"MIS"`` (intraday, default) or ``"CNC"`` (delivery).
    risk_per_trade_pct : float
        Fraction of portfolio to risk per trade (default 1 %).
    max_positions : int
        Maximum simultaneous open positions (default 5).
    agent_run_every_n_bars : int
        How often the AI agent runs (default: every bar = 1).
    google_model : str
        Gemini model name (default ``gemini-2.0-flash``).
    """

    # ----------------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------------

    def initialize(
        self,
        universe: Optional[list] = None,
        product_type: str = "MIS",
        risk_per_trade_pct: float = 1.0,
        max_positions: int = 5,
        agent_run_every_n_bars: int = 1,
        google_model: str = "gemini-2.0-flash",
    ):
        # Bar cadence — 15-minute bars aligned to NSE intraday
        self.sleeptime = "15 minutes"

        # Universe
        env_universe = os.getenv("STRATEGY_UNIVERSE", "")
        if env_universe:
            self.universe = [s.strip().upper() for s in env_universe.split(",") if s.strip()]
        else:
            self.universe = [s.upper() for s in (universe or DEFAULT_UNIVERSE)]

        # Product type
        env_ptype = os.getenv("PRODUCT_TYPE", product_type).upper()
        self.product_type = env_ptype if env_ptype in {"MIS", "CNC", "MARGIN"} else "MIS"

        # Risk & position management
        self.risk_per_trade_pct  = float(os.getenv("RISK_PER_TRADE_PCT", risk_per_trade_pct))
        self.max_positions       = int(os.getenv("MAX_POSITIONS", max_positions))
        self.agent_run_every_n_bars = max(1, agent_run_every_n_bars)

        # State
        self.vars.bar_count = 0

        # Quote asset — Indian Rupee
        self.set_market("NSE_INDIA")

        # AI Agent
        model = os.getenv("GOOGLE_MODEL", google_model)
        self._google_model = model

        self.agents.create(
            name           = "india_trader",
            default_model  = model,
            system_prompt  = self._build_system_prompt(),
            tools=[
                self.get_nse_bars,
                self.get_nifty_movers,
                self.get_india_market_news,
                self.get_technical_signals,
                self.get_portfolio_stats,
            ],
        )

        self.log_message(
            f"[IndiaAITrader] Initialised | universe={self.universe} | "
            f"product_type={self.product_type} | model={model}",
            color="cyan",
        )

    def _build_system_prompt(self) -> str:
        universe_str = ", ".join(self.universe)
        return f"""
You are an AI trading agent specialising in the Indian Stock Market (NSE/BSE).
You trade equities in Indian Rupees (INR) during NSE market hours (09:15 – 15:30 IST).

UNIVERSE: {universe_str}

PRODUCT TYPE: {self.product_type}
- If MIS: ALL positions MUST be closed before 15:15 IST (intraday only, no overnight holding).
- If CNC: Positions may carry overnight; apply stricter quality criteria.

YOUR OBJECTIVE:
1. Use your tools to analyse the universe and identify the best 1–{self.max_positions} trading opportunities.
2. Rank them by expected risk-adjusted return. Don't trade just to be active.
3. Size trades so each risks ~{self.risk_per_trade_pct}% of portfolio value (ATR-based or momentum-based stop).
4. Indian equities often move on sector rotation, FII flows, and global cues — factor these in.

EXECUTION RULES:
- Place BUY orders for bullish setups, SELL orders to close or short (if allowed).
- Use limit orders near the current bid/ask to avoid slippage.
- Never invest more than 20% of portfolio in a single stock.
- Always check current positions and cash before placing new orders.
- If no clear edge is found, do nothing. Dry powder is valid.

KEY INDIA-SPECIFIC CONSIDERATIONS:
- Market opens with a pre-open auction 09:00–09:15 IST; first 5 min can be erratic.
- Large caps (Nifty 50) are most liquid; prefer them for MIS.
- Avoid trading on Budget days, RBI policy days, or during major global risk events unless the signal is very strong.
- Nifty movers give macro context; align individual stock trades with the market trend.
- Volume confirmation is important — do not buy on declining volume.

END EVERY RUN WITH: RESULT: <brief summary of decisions made and reasoning>
""".strip()

    # ----------------------------------------------------------------
    # Iteration
    # ----------------------------------------------------------------

    def on_trading_iteration(self):
        self.vars.bar_count += 1

        # Market hours guard (live mode only; backtesting uses simulated time)
        if not self.is_backtesting and not _is_market_open_ist():
            self.log_message("[IndiaAITrader] Outside market hours — skipping.", color="yellow")
            return

        # MIS square-off guard
        if self.product_type == "MIS" and _is_mis_squareoff_time():
            self.log_message(
                "[IndiaAITrader] 15:15 IST — forcing MIS square-off!", color="red"
            )
            self._square_off_all_mis()
            return

        # Run agent on schedule
        if self.vars.bar_count % self.agent_run_every_n_bars != 0:
            return

        self.log_message(
            f"[IndiaAITrader] Running AI agent (bar #{self.vars.bar_count})…",
            color="cyan",
        )
        try:
            result = self.agents["india_trader"].run()
            self.log_message(f"[IndiaAITrader] Agent result: {result.summary}", color="cyan")
        except Exception as exc:
            self.log_message(f"[IndiaAITrader] Agent error: {exc}", color="red")

    def before_market_closes(self):
        """Hard MIS square-off hook — fires 5 minutes before market close."""
        if self.product_type == "MIS":
            self.log_message(
                "[IndiaAITrader] before_market_closes: squaring off all MIS positions.",
                color="red",
            )
            self._square_off_all_mis()

    def _square_off_all_mis(self):
        """Close all open positions immediately (market orders)."""
        positions = self.get_positions()
        if not positions:
            return
        for position in positions:
            if position.quantity != 0:
                try:
                    order = self.create_order(
                        position.asset,
                        abs(position.quantity),
                        "sell" if position.quantity > 0 else "buy",
                        type="market",
                    )
                    self.submit_order(order)
                    self.log_message(
                        f"[IndiaAITrader] Square-off: {position.asset.symbol} "
                        f"qty={position.quantity}",
                        color="yellow",
                    )
                except Exception as exc:
                    self.log_message(
                        f"[IndiaAITrader] Square-off error for {position.asset.symbol}: {exc}",
                        color="red",
                    )

    # ----------------------------------------------------------------
    # Agent Tools
    # ----------------------------------------------------------------

    @agent_tool(
        name="get_nse_bars",
        description=(
            "Fetch recent OHLCV price bars for an NSE-listed stock. "
            "Returns up to 30 bars of daily or 15-minute data. "
            "Use this to analyse price trends, momentum, and volume for any "
            "stock in the universe like RELIANCE, TCS, INFY, HDFCBANK, etc."
        ),
    )
    def get_nse_bars(
        self,
        symbol: str,
        length: int = 20,
        timestep: str = "day",
    ) -> dict:
        """Fetch historical OHLCV bars for an NSE-listed stock.

        Args:
            symbol: NSE ticker symbol, e.g. RELIANCE, INFY, TCS (no .NS suffix).
            length: Number of bars to return (default 20, max 60).
            timestep: Bar size — "day" (daily) or "15 minutes" (intraday).

        Returns:
            dict with keys 'symbol', 'timestep', 'count', 'bars'.
            Each bar: {'date', 'open', 'high', 'low', 'close', 'volume'}.
        """
        length = min(int(length), 60)
        symbol = str(symbol).strip().upper()
        asset  = Asset(symbol=symbol, asset_type="stock")
        try:
            bars = self.get_historical_prices(asset, length, timestep=timestep)
            if bars is None:
                return {"error": f"No data for {symbol}", "symbol": symbol}
            df = bars.df.tail(length)
            return {
                "symbol":   symbol,
                "timestep": timestep,
                "count":    len(df),
                "bars": [
                    {
                        "date":   str(idx)[:19],
                        "open":   round(float(row.get("open",   0)), 2),
                        "high":   round(float(row.get("high",   0)), 2),
                        "low":    round(float(row.get("low",    0)), 2),
                        "close":  round(float(row.get("close",  0)), 2),
                        "volume": int(row.get("volume", 0)),
                    }
                    for idx, row in df.iterrows()
                ],
            }
        except Exception as exc:
            return {"error": str(exc), "symbol": symbol}

    @agent_tool(
        name="get_nifty_movers",
        description=(
            "Get the top gaining and losing Nifty 50 stocks for today. "
            "Use this to understand overall market sentiment and which sectors "
            "are in play. A rising market (more gainers) favours momentum longs."
        ),
    )
    def get_nifty_movers(self, top_n: int = 10) -> dict:
        """Fetch intraday % change for the full universe to find top movers.

        Args:
            top_n: Number of top gainers and losers to return (default 10, max 20).

        Returns:
            dict with 'gainers' and 'losers' lists. Each: {'symbol', 'change_pct', 'last_price'}.
        """
        import yfinance as yf

        top_n = min(int(top_n), 20)
        movers = []
        for sym in self.universe:
            try:
                ticker = yf.Ticker(f"{sym}.NS")
                info   = ticker.fast_info
                prev   = float(getattr(info, "previous_close", 0) or 0)
                last   = float(getattr(info, "last_price",     0) or 0)
                if prev > 0 and last > 0:
                    change_pct = round((last - prev) / prev * 100, 2)
                    movers.append({"symbol": sym, "change_pct": change_pct, "last_price": last})
            except Exception:
                continue

        movers.sort(key=lambda x: x["change_pct"])
        losers  = movers[:top_n]
        gainers = movers[-top_n:][::-1]
        return {"gainers": gainers, "losers": losers}

    @agent_tool(
        name="get_india_market_news",
        description=(
            "Fetch recent Indian stock market headlines from the Economic Times. "
            "Use this to check for market-moving events, RBI announcements, "
            "FII/DII flows, sector news, and corporate actions. "
            "Headlines are from the last 24 hours."
        ),
    )
    def get_india_market_news(self, limit: int = 10) -> dict:
        """Fetch recent Indian market headlines from Economic Times RSS.

        Args:
            limit: Maximum number of articles to return (default 10, max 20).

        Returns:
            dict with 'count' and 'articles'. Each: {'headline', 'published'}.
        """
        import xml.etree.ElementTree as ET
        import urllib.request

        limit = min(int(limit), 20)
        feed_urls = [
            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",  # Markets
            "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",  # Stocks
        ]
        articles = []
        for url in feed_urls:
            if len(articles) >= limit:
                break
            try:
                req  = urllib.request.Request(url, headers={"User-Agent": "LumiBot/1.0"})
                resp = urllib.request.urlopen(req, timeout=8)
                root = ET.fromstring(resp.read())
                for item in root.iter("item"):
                    title = item.findtext("title", "").strip()
                    pub   = item.findtext("pubDate", "").strip()
                    if title:
                        articles.append({"headline": title, "published": pub})
                    if len(articles) >= limit:
                        break
            except Exception:
                continue

        return {"count": len(articles), "articles": articles[:limit]}

    @agent_tool(
        name="get_technical_signals",
        description=(
            "Compute technical indicators (Supertrend, session VWAP, RSI) for a stock. "
            "Use this to validate entry/exit signals. Supertrend direction: 1 = uptrend "
            "(bullish), -1 = downtrend (bearish). Price above VWAP = bullish intraday bias. "
            "RSI > 60 = strong momentum; RSI < 40 = oversold."
        ),
    )
    def get_technical_signals(
        self,
        symbol: str,
        length: int = 30,
        timestep: str = "15 minutes",
    ) -> dict:
        """Run Supertrend + VWAP on recent bars for a stock.

        Args:
            symbol: NSE ticker symbol, e.g. RELIANCE.
            length: Number of bars to compute indicators on (default 30).
            timestep: "15 minutes" for intraday or "day" for daily signals.

        Returns:
            dict with 'symbol', 'supertrend_direction' (1=up/-1=down),
            'price_vs_vwap' ('above'/'below'), 'rsi_14', 'last_close'.
        """
        symbol = str(symbol).strip().upper()
        asset  = Asset(symbol=symbol, asset_type="stock")
        length = min(int(length), 60)

        bars = self.get_historical_prices(asset, length, timestep=timestep)
        if bars is None:
            return {"error": f"No data for {symbol}", "symbol": symbol}

        df = bars.df.copy()
        if df.empty or len(df) < 5:
            return {"error": "Insufficient bars", "symbol": symbol}

        result: dict = {"symbol": symbol, "bars_used": len(df)}

        # --- Supertrend ---
        try:
            from lumibot.tools.technical_indicators import supertrend
            st = supertrend(df, period=10, multiplier=3.0)
            if st is not None and not st.empty:
                direction_col = [c for c in st.columns if "SUPERTd" in c]
                if direction_col:
                    result["supertrend_direction"] = int(st[direction_col[0]].iloc[-1])
                    result["supertrend_signal"] = (
                        "BULLISH (uptrend)" if result["supertrend_direction"] == 1
                        else "BEARISH (downtrend)"
                    )
        except Exception as exc:
            result["supertrend_error"] = str(exc)

        # --- Session VWAP ---
        try:
            from lumibot.tools.technical_indicators import session_vwap
            vwap = session_vwap(df)
            if vwap is not None and not vwap.empty:
                last_vwap  = float(vwap.iloc[-1])
                last_close = float(df["close"].iloc[-1])
                result["vwap"]          = round(last_vwap, 2)
                result["last_close"]    = round(last_close, 2)
                result["price_vs_vwap"] = "above" if last_close > last_vwap else "below"
        except Exception as exc:
            result["vwap_error"] = str(exc)

        # --- RSI(14) ---
        try:
            closes = df["close"].dropna()
            if len(closes) >= 15:
                delta  = closes.diff()
                gain   = delta.clip(lower=0).rolling(14).mean()
                loss   = (-delta.clip(upper=0)).rolling(14).mean()
                rs     = gain / loss.replace(0, float("nan"))
                rsi_s  = 100 - (100 / (1 + rs))
                result["rsi_14"] = round(float(rsi_s.iloc[-1]), 1)
        except Exception as exc:
            result["rsi_error"] = str(exc)

        return result

    @agent_tool(
        name="get_portfolio_stats",
        description=(
            "Get current portfolio state: cash balance, open positions, "
            "total portfolio value, and today's P&L. "
            "Always call this before placing orders to understand available capital "
            "and existing exposure."
        ),
    )
    def get_portfolio_stats(self) -> dict:
        """Return current cash, positions, and portfolio value.

        Returns:
            dict with 'cash_inr', 'portfolio_value_inr', 'open_positions',
            'product_type', 'universe'.
        """
        try:
            cash     = float(self.get_cash())
            pv       = float(self.get_portfolio_value())
            positions = self.get_positions()

            open_pos = []
            for pos in positions:
                try:
                    sym   = pos.asset.symbol
                    qty   = pos.quantity
                    price = self.get_last_price(pos.asset) or 0
                    value = float(qty) * float(price)
                    open_pos.append({
                        "symbol":    sym,
                        "quantity":  qty,
                        "last_price_inr": round(float(price), 2),
                        "value_inr": round(value, 2),
                    })
                except Exception:
                    continue

            return {
                "cash_inr":            round(cash, 2),
                "portfolio_value_inr": round(pv, 2),
                "open_positions":      open_pos,
                "positions_count":     len(open_pos),
                "max_positions":       self.max_positions,
                "product_type":        self.product_type,
                "universe":            self.universe,
                "market_open_ist":     "09:15 - 15:30",
            }
        except Exception as exc:
            return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Standalone backtest entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    from datetime import datetime
    from dotenv import load_dotenv
    from lumibot.backtesting import YahooDataBacktesting

    load_dotenv(".env.india")
    load_dotenv(".secrets/lumi_secrets.env")

    if not os.getenv("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY is required. Set it in .env.india or environment.")
        raise SystemExit(1)

    trading_fee = TradingFee(percent_fee=0.0003)  # ~0.03% (Zerodha flat fee)

    IndiaAITrader.backtest(
        YahooDataBacktesting,
        backtesting_start = datetime(2025, 1, 1),
        backtesting_end   = datetime(2025, 4, 1),
        benchmark_asset   = Asset("^NSEI", Asset.AssetType.INDEX),
        buy_trading_fees  = [trading_fee],
        sell_trading_fees = [trading_fee],
        parameters={
            "universe":      ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ICICIBANK"],
            "product_type":  "MIS",
            "max_positions": 3,
        },
        name        = "IndiaAITrader_NSE",
        quiet_logs  = False,
    )
