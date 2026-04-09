"""
stonxx_india_bot.py
=====================
stonxx AI/ML Strategy for Indian equities.

Key design decisions:
  • Loads a pre-trained RandomForest artifact that bundles the model + feature list,
    so training and inference are always in sync.
  • All features are scale-invariant (%, ratios, bounded oscillators) so the model
    trained on NIFTY 50 data generalises correctly to individual .NS stocks.
  • Uses predict_proba with a 0.55 confidence threshold — a hard binary predict()
    is too noisy on intraday data.
  • Position sizing: ATR-based Kelly (risk 1 % of portfolio per trade) capped at
    15 % of portfolio value. This replaces the broken quantity=1 constant.
  • Explicit exit: when ML signal drops to 0, open positions are closed on the
    next bar rather than waiting for stale bracket orders.
  • Circuit breaker: halts all trading if portfolio drops > 2 % intraday.
"""

import os
import csv
import requests

# ── State persistence (Memory Bank) ───────────────────────────────────────────
try:
    from state_manager import STATE_FILE, load_state, save_state
except ImportError:
    # Fallback when the module is imported from outside its own package
    from lumibot.example_strategies.state_manager import STATE_FILE, load_state, save_state

try:
    import google.genai as genai

    _GENAI_NEW = True
except ImportError:
    import google.generativeai as genai  # legacy fallback

    _GENAI_NEW = False
import joblib
import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401 — registers df.ta accessor

from lumibot.entities import Asset
from lumibot.strategies.strategy import Strategy

try:
    from sentiment_engine import SentimentAnalyzer
except ImportError:
    SentimentAnalyzer = None


# Minimum confidence threshold for predict_proba required to trigger a trade.
CONFIDENCE_THRESHOLD = 0.45

# Position size: allocating 10% of available portfolio capital per trade
POSITION_SIZE_PCT = 0.10


class stonxx(Strategy):
    """
    stonxx AI/ML Strategy — ML signal (RandomForest) + Gemini LLM macro filter.
    """

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def initialize(self):
        # ── Memory Bank: restore persisted state on (re)start ─────────────────
        self.state = load_state()
        active = self.state.get("active_trades", {})
        if active:
            self.log_message(
                f"[stonxx] Memory Bank restored — tracking {len(active)} active trade(s): "
                + ", ".join(
                    f"{sym}@{info.get('fill_price', '?')}"
                    for sym, info in active.items()
                ),
                color="cyan",
            )
        else:
            self.log_message(
                "[stonxx] Memory Bank: no previous trades found. Starting fresh.",
                color="cyan",
            )

        # Match ML training resolution: 15 minutes
        self.sleeptime = "15M"

        self.universe = self.parameters.get(
            "universe",
            ["NIFTY50"],
        )

        # ── Load model artifact ───────────────────────────────────────────────
        self.model = None
        self.features = None
        model_path = "nifty_xgb_model.joblib"
        try:
            artifact = joblib.load(model_path)
            # Support both old format (bare model) and new format (dict artifact)
            if isinstance(artifact, dict):
                self.model = artifact["model"]
                self.features = artifact["features"]
                meta = artifact.get("meta", {})
                self.log_message(
                    f"[stonxx] Model loaded. "
                    f"OOS acc={meta.get('oos_accuracy', '?')}, "
                    f"AUC={meta.get('oos_roc_auc', '?')}",
                    color="green",
                )
            else:
                # Legacy bare-model format
                self.model = artifact
                self.features = ["RSI_14", "MACD_12_26_9", "ATRr_14"]
                self.log_message(
                    "[stonxx] Legacy model loaded (no feature metadata).",
                    color="yellow",
                )
        except FileNotFoundError:
            self.log_message(
                f"[stonxx] {model_path} not found! Run train_nifty_model.py first.",
                color="red",
            )

        self.daily_macro_bias = "NEUTRAL"
        self.halt_trading = False

        self.IS_PAPER_TRADING = True
        self.sentiment_engine = SentimentAnalyzer(model_name="llama3.2")
        self.local_sentiment_score = 0.0

        self.paper_trade_file = "paper_trades.csv"
        if self.IS_PAPER_TRADING and not os.path.exists(self.paper_trade_file):
            with open(self.paper_trade_file, mode="w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["Timestamp", "Asset", "Direction", "Quantity", "Entry", "TakeProfit", "StopLoss"])

    # ── Daily macro bias via Gemini ───────────────────────────────────────────

    def get_market_news(self):
        """Placeholder headlines; replace with a real news API in production."""
        return [
            "RBI expected to keep rates unchanged in the upcoming policy meeting.",
            "FPIs turn net sellers as valuation concerns rise in the short term.",
            "IT stocks rally tracking strong overnight gains in the US tech sector.",
            "Monsoon progress better than expected, aiding rural FMCG themes.",
            "Auto sector sales hit record highs ahead of the festive season.",
        ]

    def before_market_opens(self):
        """Set daily macro bias from Gemini. Falls back to NEUTRAL if unavailable."""
        self.halt_trading = False
        self.starting_portfolio_value = self.get_portfolio_value()

        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            self.log_message(
                "[stonxx] GEMINI_API_KEY not set — macro bias = NEUTRAL.",
                color="yellow",
            )
            self.daily_macro_bias = "NEUTRAL"
            return

        if _GENAI_NEW:
            client = genai.Client(api_key=gemini_api_key)
        else:
            genai.configure(api_key=gemini_api_key)
        # Model handle differs between new and old SDK

        headlines = self.get_market_news()
        news_text = "\n".join(f"- {h}" for h in headlines)
        prompt = (
            f"You are a ruthless hedge-fund risk manager.\n"
            f"Headlines:\n{news_text}\n\n"
            f"Give the single-word overall macro sentiment for Indian equities today: "
            f"BULLISH, BEARISH, or NEUTRAL. Reply with that one word only."
        )

        try:
            if _GENAI_NEW:
                response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            else:
                response = genai.GenerativeModel("gemini-2.5-flash").generate_content(prompt)
            bias = response.text.strip().upper()
            if bias in {"BULLISH", "BEARISH", "NEUTRAL"}:
                self.daily_macro_bias = bias
            else:
                self.log_message(
                    f"[stonxx] Unexpected Gemini output: '{bias}'. Using NEUTRAL.",
                    color="yellow",
                )
                self.daily_macro_bias = "NEUTRAL"
        except Exception as exc:
            self.log_message(f"[stonxx] Gemini error: {exc}. Using NEUTRAL.", color="red")
            self.daily_macro_bias = "NEUTRAL"

        self.log_message(f"Daily macro bias (Gemini): {self.daily_macro_bias}", color="cyan")

        # ── Daily local sentiment bias via Llama 3.2 ──────────────────────────
        if hasattr(self, "sentiment_engine"):
            try:
                news = self.sentiment_engine.fetch_text_data("Indian Stock Market")
                self.local_sentiment_score = self.sentiment_engine.analyze_sentiment(news)
                self.log_message(f"Local NLP Sentiment Score (Llama 3.2): {self.local_sentiment_score}", color="cyan")
            except Exception as e:
                self.log_message(f"Sentiment Engine Error: {e}", color="red")

    # ── Feature computation ───────────────────────────────────────────────────

    def _compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute the strictly stationary features used during training.
        No raw price inputs or time-of-day inputs are used.
        """
        df = df.copy()

        # Normalize column names — LumiBot broker returns Title-Case columns
        # (Open, High, Low, Close, Volume). Training data used lowercase.
        df.columns = [c.lower() for c in df.columns]

        # 1. log_return
        df["log_return"] = np.log(df["close"] / df["close"].shift(1))

        # 2. volatility_20
        df["volatility_20"] = df["log_return"].rolling(window=20).std()

        # 3. volume_delta
        high_low = df["high"] - df["low"]
        buying_selling_pressure = (df["close"] - df["low"]) - (df["high"] - df["close"])
        df["volume_delta"] = (buying_selling_pressure / (high_low + 1e-8)) * df["volume"]

        # 4. hl_spread
        df["hl_spread"] = high_low / df["close"]

        # 5. atr_pct
        df.ta.atr(length=14, append=True)
        atr_col = "ATRr_14" if "ATRr_14" in df.columns else "ATR_14"
        df["atr_pct"] = df[atr_col] / df["close"]

        # 6. bb_width (Bollinger Bandwidth percentage)
        middle_band = df["close"].rolling(window=20).mean()
        std_dev = df["close"].rolling(window=20).std()
        upper_band = middle_band + (2 * std_dev)
        lower_band = middle_band - (2 * std_dev)
        df["bb_width"] = (upper_band - lower_band) / (middle_band + 1e-8)

        # 7. vwap_dist (Daily VWAP distance)
        df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
        df["typical_volume"] = df["typical_price"] * df["volume"]
        df["date_only"] = df.index.date
        cum_vol = df.groupby("date_only")["volume"].cumsum()
        cum_typ_vol = df.groupby("date_only")["typical_volume"].cumsum()
        df["vwap"] = cum_typ_vol / (cum_vol + 1e-8)
        df["vwap_dist"] = (df["close"] - df["vwap"]) / (df["vwap"] + 1e-8)
        df.drop(columns=["typical_price", "typical_volume", "date_only", "vwap"], inplace=True, errors="ignore")

        # 8. htf_trend (Percentage distance from 200 EMA)
        df.ta.ema(length=200, append=True)
        ema_cols = [c for c in df.columns if c.startswith("EMA_")]
        ema_col = ema_cols[-1] if ema_cols else "EMA_200"
        df["htf_trend"] = (df["close"] - df[ema_col]) / (df[ema_col] + 1e-8)

        # Drop NaNs created by rolling windows / shifts / ATR / EMA_200
        df.dropna(inplace=True)
        return df

    # ── ML prediction ─────────────────────────────────────────────────────────

    def _get_ml_prediction(self, asset: Asset) -> tuple[int, float]:
        """
        Returns (signal, confidence) where:
            signal     = 1 (buy) or 0 (hold/exit)
            confidence = probability of the 'up' class from predict_proba
        """
        if self.model is None or self.features is None:
            return 0, 0.0

        # Fetch daily bars — swing trading anchors all indicators to daily timeframe.
        # 250 daily bars covers EMA(200) warm-up comfortably.
        # Note: self.sleeptime="15M" controls scan frequency; timeframe here
        #       controls the resolution of the historical data fetched.
        bars = self.get_historical_prices(asset, 250, "day")
        if bars is None or len(bars.df) < 200:
            self.log_message(f"Not enough bars for {asset.symbol} — skipping.", color="yellow")
            return 0, 0.0

        # ── ONE-TIME DIAGNOSTIC: log raw columns from broker bars ──────────────
        if not getattr(self, "_diag_logged", False):
            self._diag_logged = True
            self.log_message(f"[DIAG] bars.df.columns = {list(bars.df.columns)}", color="yellow")
            self.log_message(f"[DIAG] bars.df.dtypes = {bars.df.dtypes.to_dict()}", color="yellow")

        df = self._compute_features(bars.df)

        # ── ONE-TIME DIAGNOSTIC: log feature values ────────────────────────────
        if not getattr(self, "_feat_diag_logged", False):
            self._feat_diag_logged = True
            self.log_message(f"[DIAG] computed df.columns = {list(df.columns)}", color="yellow")
            if not df.empty:
                self.log_message(
                    f"[DIAG] last feature row = {df[self.features].iloc[-1].to_dict() if self.features and all(f in df.columns for f in self.features) else 'FEATURES MISSING'}",
                    color="yellow",
                )

        if df.empty:
            return 0, 0.0

        # Identify which features are available
        missing = [f for f in self.features if f not in df.columns]
        if missing:
            self.log_message(f"Missing features for {asset.symbol}: {missing}", color="red")
            return 0, 0.0

        latest = df[self.features].iloc[-1:]

        try:
            probas = self.model.predict_proba(latest)[0]
            # Sklearn orders classes naturally: [-1, 0, 1] -> [p_down, p_hold, p_up]
            p_down = probas[0]
            p_hold = probas[1]
            p_up = probas[2]

            # Debug log for distribution analysis
            self.log_message(
                f"[{asset.symbol}] Logic check: Short={p_down:.3f} | Hold={p_hold:.3f} | Long={p_up:.3f}", color="blue"
            )

            if p_up > CONFIDENCE_THRESHOLD:
                return 1, float(p_up)
            elif p_down > CONFIDENCE_THRESHOLD:
                return -1, float(p_down)
            else:
                return 0, float(p_hold)

        except Exception as exc:
            self.log_message(f"Prediction error for {asset.symbol}: {exc}", color="red")
            return 0, 0.0

    # ── ATR for position sizing ───────────────────────────────────────────────

    def _get_current_atr(self, asset: Asset) -> float | None:
        """Fetch recent daily bars to compute ATR on the swing trading timeframe."""
        bars = self.get_historical_prices(asset, 30, "day")
        if bars is None or len(bars.df) < 15:
            return None
        df = bars.df.copy()
        df.ta.atr(length=14, append=True)
        atr_col = "ATRr_14" if "ATRr_14" in df.columns else "ATR_14"
        if atr_col not in df.columns:
            return None
        val = df[atr_col].iloc[-1]
        return float(val) if pd.notna(val) else None

    # ── Position sizing ───────────────────────────────────────────────────────

    def _calc_quantity(self, current_price: float) -> int:
        """Allocate exactly exactly 10% of portfolio capital per trade."""
        portfolio_value = self.get_portfolio_value()
        alloc_amount = portfolio_value * POSITION_SIZE_PCT

        qty = int(alloc_amount / current_price)

        # Ensure we have cash for the order
        available_cash = self.get_cash()
        max_by_cash = int(available_cash * 0.95 / current_price)
        qty = min(qty, max_by_cash)

        return max(qty, 0)

    # ── Paper trade logging ───────────────────────────────────────────────────

    def _record_paper_trade(self, asset_symbol, direction, quantity, entry, tp, sl):
        timestamp = self.get_datetime().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Log to console
        msg = f"PAPER TRADE (Direction: {direction}, Asset: {asset_symbol}, Quantity: {quantity}, Entry: ~{entry:.2f}, TP: {tp:.2f}, SL: {sl:.2f})"
        self.log_message(msg, color="cyan")

        # 2. Save to CSV
        try:
            with open(self.paper_trade_file, mode="a", newline="") as file:
                writer = csv.writer(file)
                writer.writerow([timestamp, asset_symbol, direction, quantity, entry, tp, sl])
        except Exception as e:
            self.log_message(f"Failed to write to CSV: {e}", color="red")

        # 3. Send Telegram Alert
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if bot_token and chat_id:
            try:
                tg_msg = f"🚨 <b>PAPER TRADE ALERT</b> 🚨\n\n<b>Asset:</b> {asset_symbol}\n<b>Side:</b> {direction}\n<b>Qty:</b> {quantity}\n<b>Entry:</b> {entry:.2f}\n<b>TP:</b> {tp:.2f}\n<b>SL:</b> {sl:.2f}\n<b>Time:</b> {timestamp}"
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {"chat_id": chat_id, "text": tg_msg, "parse_mode": "HTML"}
                requests.post(url, json=payload, timeout=5)
            except Exception as e:
                self.log_message(f"Failed to send Telegram alert: {e}", color="red")

    # ── Main iteration ────────────────────────────────────────────────────────

    def is_market_open(self):
        """Guard for NSE market hours (9:15 AM - 3:30 PM IST)."""
        now = self.get_datetime()
        # Ensure we are in Asia/Kolkata or comparison is safe
        # NSE hours: 09:15 to 15:30
        current_time = now.time()
        start_time = pd.Timestamp("09:15").time()
        end_time = pd.Timestamp("15:30").time()

        # Check weekday (0=Mon, 4=Fri)
        if now.weekday() > 4:
            return False

        return start_time <= current_time <= end_time

    def on_trading_iteration(self):
        if getattr(self, "halt_trading", False):
            return

        if not self.is_market_open():
            return

        # ── Circuit breaker ────────────────────────────────────────────────
        current_pv = self.get_portfolio_value()
        starting = getattr(self, "starting_portfolio_value", 0)
        if starting > 0 and (starting - current_pv) / starting > 0.02:
            self.log_message(
                f"CIRCUIT BREAKER: portfolio down > 2 % ({(starting - current_pv) / starting:.2%}). "
                "Selling all and halting.",
                color="red",
            )
            self.sell_all()
            self.halt_trading = True
            return

        # ── Determine macro filter ─────────────────────────────────────────
        # During backtesting without Gemini, NEUTRAL is treated as permissive
        # (not a veto). This ensures Short signals are not blocked when LLM is off.
        macro_bias = getattr(self, "daily_macro_bias", "NEUTRAL")
        if self.is_backtesting and macro_bias == "NEUTRAL":
            is_bullish_or_neutral = True
            is_bearish = True
        else:
            is_bullish_or_neutral = macro_bias in {"BULLISH", "NEUTRAL"}
            is_bearish = macro_bias == "BEARISH"

        # Extract the local sentiment score to apply as a secondary strict filter
        local_score = getattr(self, "local_sentiment_score", 0.0)

        for symbol in self.universe:
            asset = Asset(
                symbol=symbol,
                asset_type="index" if symbol == "NIFTY50" else "stock",
            )

            ml_signal, confidence = self._get_ml_prediction(asset)
            self.log_message(f"{asset.symbol} | ML={ml_signal} | conf={confidence:.3f} | bias={self.daily_macro_bias}")

            position = self.get_position(asset)
            holding = position is not None and position.quantity > 0

            # ── LONG ENTRY: Class 1 bracket logic ──────────────────────────
            if ml_signal == 1 and is_bullish_or_neutral and not holding:
                news = self.sentiment_engine.fetch_text_data(asset.symbol)
                llm_score = self.sentiment_engine.analyze_sentiment(news)
                if llm_score < -0.25:
                    self.log_message("VETO: LLM blocked BUY (bearish sentiment)", color="yellow")
                    continue

                current_atr = self._get_current_atr(asset)
                if current_atr is None or current_atr <= 0:
                    continue
                current_price = self.get_last_price(asset)
                stop_loss_price = current_price - (current_atr * 1.0)
                take_profit_price = current_price + (current_atr * 1.5)
                quantity = self._calc_quantity(current_price)

                if quantity <= 0:
                    continue

                if not self.IS_PAPER_TRADING:
                    order = self.create_order(
                        asset=asset,
                        quantity=quantity,
                        side="buy",
                        take_profit_price=take_profit_price,
                        stop_loss_price=stop_loss_price,
                        type="market",
                    )
                    self.submit_order(order)
                    self.log_message(
                        f"LONG {asset.symbol}: qty={quantity} @ ~{current_price:.2f} | "
                        f"SL={stop_loss_price:.2f} TP={take_profit_price:.2f} | "
                        f"conf={confidence:.3f}",
                        color="green",
                    )
                else:
                    self._record_paper_trade(
                        asset.symbol, "BUY", quantity, current_price, take_profit_price, stop_loss_price
                    )

            # ── SHORT ENTRY: Class -1 bracket logic ─────────────────────────
            elif ml_signal == -1 and is_bearish and not holding:
                news = self.sentiment_engine.fetch_text_data(asset.symbol)
                llm_score = self.sentiment_engine.analyze_sentiment(news)
                if llm_score > 0.25:
                    self.log_message("VETO: LLM blocked SELL (bullish sentiment)", color="yellow")
                    continue

                current_atr = self._get_current_atr(asset)
                if current_atr is None or current_atr <= 0:
                    continue
                current_price = self.get_last_price(asset)
                stop_loss_price = current_price + (current_atr * 1.0)
                take_profit_price = current_price - (current_atr * 1.5)
                quantity = self._calc_quantity(current_price)

                if quantity <= 0:
                    continue

                if not self.IS_PAPER_TRADING:
                    order = self.create_order(
                        asset=asset,
                        quantity=quantity,
                        side="sell",
                        take_profit_price=take_profit_price,
                        stop_loss_price=stop_loss_price,
                        type="market",
                    )
                    self.submit_order(order)
                    self.log_message(
                        f"SHORT {asset.symbol}: qty={quantity} @ ~{current_price:.2f} | "
                        f"SL={stop_loss_price:.2f} TP={take_profit_price:.2f} | "
                        f"conf={confidence:.3f}",
                        color="red",
                    )
                else:
                    self._record_paper_trade(
                        asset.symbol, "SELL", quantity, current_price, take_profit_price, stop_loss_price
                    )

            # ── HOLD / NO TRADE ─────────────────────────────────────────────
            elif not holding and ml_signal == 0:
                pass

            # ── MACRO VETO LOGIC ────────────────────────────────────────────
            elif ml_signal == 1 and is_bearish:
                self.log_message(
                    f"VETO LONG {asset.symbol}: blocked by BEARISH macro bias.",
                    color="yellow",
                )
            elif ml_signal == 1 and local_score <= -0.5:
                self.log_message(
                    f"VETO LONG {asset.symbol}: blocked by strong negative local sentiment ({local_score}).",
                    color="yellow",
                )
            elif ml_signal == -1 and is_bullish_or_neutral:
                self.log_message(
                    f"VETO SHORT {asset.symbol}: blocked by BULLISH/NEUTRAL macro bias.",
                    color="yellow",
                )
            elif ml_signal == -1 and local_score >= 0.5:
                self.log_message(
                    f"VETO SHORT {asset.symbol}: blocked by strong positive local sentiment ({local_score}).",
                    color="yellow",
                )

    # ── Memory Bank lifecycle hook ────────────────────────────────────────────

    def on_filled_order(self, position, order, price, quantity, multiplier):
        """
        Called by LumiBot whenever an order is fully filled.

        • BUY fill  → record the trade in self.state["active_trades"] and persist.
        • SELL fill → if the resulting position is flat (qty == 0), remove the
                      ticker from state and persist.

        This hook runs on the broker's callback thread and is intentionally
        lightweight — only dict mutations + a single file write — so it does
        not block on_trading_iteration.
        """
        symbol = order.asset.symbol

        if order.side == "buy":
            self.state["active_trades"][symbol] = {
                "fill_price": round(float(price), 4),
                "quantity": int(quantity),
            }
            save_state(self.state)
            self.log_message(
                f"[Memory Bank] BUY recorded — {symbol}: "
                f"qty={quantity} @ {price:.2f}",
                color="green",
            )

        elif order.side == "sell":
            # A position with qty == 0 (or None) means it has been fully closed
            pos_qty = getattr(position, "quantity", None)
            if pos_qty is None or pos_qty == 0:
                removed = self.state["active_trades"].pop(symbol, None)
                if removed is not None:
                    save_state(self.state)
                    self.log_message(
                        f"[Memory Bank] SELL closed — {symbol} removed from active trades.",
                        color="magenta",
                    )
            else:
                # Partial fill: update the stored quantity
                if symbol in self.state["active_trades"]:
                    self.state["active_trades"][symbol]["quantity"] = int(pos_qty)
                    save_state(self.state)
                    self.log_message(
                        f"[Memory Bank] PARTIAL SELL — {symbol} qty updated to {pos_qty}.",
                        color="yellow",
                    )


if __name__ == "__main__":
    from datetime import datetime

    from lumibot.backtesting import YahooDataBacktesting

    backtest_start = datetime(2025, 1, 1)
    backtest_end = datetime(2025, 12, 31)

    stonxx.backtest(
        YahooDataBacktesting,
        backtesting_start=backtest_start,
        backtesting_end=backtest_end,
        budget=10_000_000,  # ₹1 crore
        benchmark_asset=Asset("^NSEI", Asset.AssetType.INDEX),
        show_plot=True,
        show_tearsheet=True,
        save_logfile=True,
        name="stonxx",
    )
