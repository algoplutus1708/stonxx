"""Long-only daily swing execution for the stonxx paper/live workflow.

The model is trained on fully closed daily bars, so the strategy performs its
signal generation after the NSE cash session has closed and queues next-open
orders instead of trading incomplete same-day bars.
"""

from __future__ import annotations

import ast
import csv
import math
import os
import re
from datetime import date, timedelta

import joblib
import pandas as pd
import pytz

from lumibot.entities import Asset
from lumibot.strategies.strategy import Strategy

try:
    from sentiment_engine import SentimentAnalyzer
except ImportError:  # pragma: no cover - fallback for package installs that omit the repo root.
    SentimentAnalyzer = None

try:
    from state_manager import STATE_FILE, load_state, save_state
except ImportError:
    from lumibot.example_strategies.state_manager import STATE_FILE, load_state, save_state

from train_yf_model import (
    BENCHMARK_TICKER,
    FEATURE_COLUMNS,
    compute_true_range,
    normalize_history_frame,
    prepare_symbol_inference_frame,
)

MASTER_UNIVERSE = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "ITC",
    "SUNPHARMA",
    "LT",
    "TATAMOTORS",
    "HINDUNILVR",
    "BHARTIARTL",
    "MARUTI",
    "AXISBANK",
    "ASIANPAINT",
]
DEFAULT_MODEL_PATH = "stonxx_daily_panel_model.joblib"
DEFAULT_PAPER_CASH = 1_000_000.0
DEFAULT_MAX_POSITIONS = 3
DEFAULT_MINIMUM_PREDICTED_RETURN = 0.01
DEFAULT_RISK_BUDGET_PCT = 0.01
DEFAULT_MAX_POSITION_PCT = 0.10
DEFAULT_COOLDOWN_TRADING_DAYS = 5
DEFAULT_SENTIMENT_MODEL = "llama3.2"
DEFAULT_SENTIMENT_WEIGHT = 0.35
DEFAULT_SENTIMENT_THRESHOLD_BONUS = 0.75
DEFAULT_DYNAMIC_UNIVERSE_SIZE = 40
AFTER_CLOSE_CRON = "45 15 * * 1-5"
NEXT_OPEN_CRON = "16 9 * * 1-5"
WEEKLY_UNIVERSE_REFRESH_CRON = "0 8 * * 1"


def next_trading_day(trading_date: date) -> date:
    """Return the next weekday trading session."""
    candidate = trading_date + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def compute_order_quantity(
    *,
    portfolio_value: float,
    current_price: float,
    atr_20: float,
    available_cash: float,
    risk_budget_pct: float = DEFAULT_RISK_BUDGET_PCT,
    max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
) -> int:
    """ATR-bounded long-only sizing with a hard notional cap."""
    if portfolio_value <= 0 or current_price <= 0 or atr_20 <= 0 or available_cash <= 0:
        return 0

    risk_budget = portfolio_value * risk_budget_pct
    calculated_shares = int(risk_budget / atr_20)
    max_shares_allowed = int((portfolio_value * max_position_pct) / current_price)
    cash_limited_shares = int(available_cash / current_price)
    final_quantity = min(calculated_shares, max_shares_allowed, cash_limited_shares)
    return max(final_quantity, 0)


def rank_long_candidates(
    signals: list[dict],
    *,
    minimum_predicted_return: float,
    max_positions: int,
) -> list[dict]:
    """Return the top long-only candidates that clear the minimum return hurdle."""
    ranked = sorted(
        signals,
        key=lambda item: float(item.get("adjusted_predicted_return", item["predicted_return"])),
        reverse=True,
    )
    filtered = [
        item
        for item in ranked
        if float(item.get("adjusted_predicted_return", item["predicted_return"])) >= minimum_predicted_return
    ]
    return filtered[:max_positions]


class stonxx(Strategy):
    """Daily long-only swing strategy using next-open execution intents."""

    def _state_file_path(self) -> str:
        return getattr(self, "state_file", STATE_FILE)

    def _parameter(self, *names, default=None):
        parameters = getattr(self, "parameters", None) or {}
        for name in names:
            if name in parameters:
                value = parameters[name]
                if value is not None:
                    return value
        return default

    def _log_message(self, message: str, *, color: str | None = None) -> None:
        logger = getattr(self, "log_message", None)
        if callable(logger):
            try:
                if color is None:
                    logger(message)
                else:
                    logger(message, color=color)
                return
            except TypeError:
                logger(message)
                return

        fallback_logger = getattr(self, "logger", None)
        if fallback_logger is not None and hasattr(fallback_logger, "info"):
            fallback_logger.info(message)
            return

        print(message)

    def _coerce_universe(self, universe_source) -> list[str]:
        if universe_source is None:
            return []

        if isinstance(universe_source, str):
            text = universe_source.strip()
            if not text:
                return []

            parsed = None
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None

            if isinstance(parsed, (list, tuple, set)):
                universe_source = list(parsed)
            else:
                universe_source = [part for part in re.split(r"[\s,;]+", text) if part.strip()]
        elif isinstance(universe_source, dict):
            universe_source = [
                universe_source.get("symbol") or universe_source.get("ticker") or universe_source.get("name")
            ]
        elif hasattr(universe_source, "__iter__"):
            universe_source = list(universe_source)
        else:
            universe_source = [universe_source]

        normalized: list[str] = []
        seen: set[str] = set()
        for item in universe_source:
            if isinstance(item, dict):
                raw_symbol = item.get("symbol") or item.get("ticker") or item.get("name")
            else:
                raw_symbol = getattr(item, "symbol", item)

            if raw_symbol is None:
                continue

            symbol = str(raw_symbol).strip().strip("[](){}'\"")
            if not symbol or symbol.lower() in {"none", "nan"}:
                continue

            normalized_symbol = symbol.upper()
            if normalized_symbol in seen:
                continue

            seen.add(normalized_symbol)
            normalized.append(normalized_symbol)

        return normalized

    def _build_stock_asset(self, symbol: str):
        symbol = str(symbol).strip()
        if not symbol:
            return None

        create_asset = getattr(self, "create_asset", None)
        if callable(create_asset):
            for kwargs in ({}, {"asset_type": Asset.AssetType.STOCK}, {"type": "stock"}):
                try:
                    return create_asset(symbol, **kwargs)
                except TypeError:
                    continue
                except Exception:
                    continue

        return Asset(symbol=symbol, asset_type=Asset.AssetType.STOCK)

    def _history_by_symbol(self, history_map) -> dict[str, object]:
        if not isinstance(history_map, dict):
            return {}

        normalized: dict[str, object] = {}
        for key, value in history_map.items():
            key_symbol = getattr(key, "symbol", key)
            if key_symbol is None:
                continue
            normalized[str(key_symbol).upper()] = value
        return normalized

    def _extract_close_series(self, history) -> pd.Series | None:
        if history is None:
            return None

        if hasattr(history, "df"):
            history = history.df
        elif hasattr(history, "to_pandas"):
            history = history.to_pandas()

        if not isinstance(history, pd.DataFrame):
            try:
                history = pd.DataFrame(history)
            except Exception:
                return None

        if history.empty:
            return None

        history = history.sort_index()
        if not history.index.is_unique:
            history = history[~history.index.duplicated(keep="last")]

        close_column = None
        for column in history.columns:
            if str(column).strip().lower() == "close":
                close_column = column
                break

        if close_column is None:
            close_candidates = [column for column in history.columns if "close" in str(column).strip().lower()]
            if len(close_candidates) == 1:
                close_column = close_candidates[0]

        if close_column is None and len(history.columns) == 1:
            close_column = history.columns[0]

        if close_column is None:
            return None

        closes = pd.to_numeric(history[close_column], errors="coerce").dropna()
        closes = closes[closes > 0]
        return closes if not closes.empty else None

    def _load_master_universe(self) -> list[str]:
        universe_source = self._parameter(
            "master_universe",
            "MASTER_UNIVERSE",
            "universe",
            "UNIVERSE",
            default=MASTER_UNIVERSE,
        )
        return self._coerce_universe(universe_source)

    def _load_master_universe_histories(self, master_universe: list[str]) -> dict[str, object]:
        histories_by_symbol: dict[str, object] = {}
        asset_pairs = []

        for symbol in master_universe:
            asset = self._build_stock_asset(symbol)
            if asset is None:
                continue
            asset_pairs.append((symbol.upper(), asset))

        if asset_pairs:
            fetch_many = getattr(self, "get_historical_prices_for_assets", None)
            if callable(fetch_many):
                try:
                    raw_histories = fetch_many(
                        [asset for _, asset in asset_pairs],
                        200,
                        timestep="day",
                        max_workers=min(16, len(asset_pairs)),
                    )
                except Exception as exc:
                    self._log_message(
                        f"[stonxx] bulk history fetch failed; falling back to per-symbol scans: {exc}",
                        color="yellow",
                    )
                else:
                    histories_by_symbol.update(self._history_by_symbol(raw_histories))

        missing_symbols = [symbol for symbol in master_universe if symbol.upper() not in histories_by_symbol]
        if not missing_symbols:
            return histories_by_symbol

        fetch_one = getattr(self, "get_historical_prices", None)
        if not callable(fetch_one):
            return histories_by_symbol

        for symbol in missing_symbols:
            asset = self._build_stock_asset(symbol)
            if asset is None:
                continue

            try:
                bars = fetch_one(asset, 200, "day")
            except Exception as exc:
                self._log_message(f"[stonxx] history fetch failed for {symbol}: {exc}", color="yellow")
                continue

            histories_by_symbol[symbol.upper()] = bars

        return histories_by_symbol

    def _schedule_weekly_universe_refresh(self) -> None:
        register_cron_callback = getattr(self, "register_cron_callback", None)
        if not callable(register_cron_callback):
            self._log_message("[stonxx] register_cron_callback unavailable; weekly universe refresh not scheduled")
            return

        register_cron_callback(WEEKLY_UNIVERSE_REFRESH_CRON, self.refresh_active_universe)

    def refresh_active_universe(self):
        master_universe = self._load_master_universe()
        if not master_universe:
            self._log_message("[stonxx] MASTER_UNIVERSE is empty; keeping the current universe.", color="yellow")
            return list(getattr(self, "universe", []))

        self.master_universe = list(master_universe)
        histories_by_symbol = self._load_master_universe_histories(master_universe)
        if not histories_by_symbol:
            self._log_message(
                f"[stonxx] refresh skipped; no usable 200-day history loaded for {len(master_universe)} symbols",
                color="yellow",
            )
            return list(getattr(self, "universe", master_universe))

        ranked_candidates: list[tuple[str, float]] = []
        scanned_any = False

        for symbol in master_universe:
            closes = self._extract_close_series(histories_by_symbol.get(symbol.upper()))
            if closes is None or len(closes) < 200:
                continue

            scanned_any = True
            closes = closes.tail(200)
            current_price = float(closes.iloc[-1])
            sma_200 = float(closes.mean())

            if current_price < sma_200:
                continue

            close_90_days_ago = float(closes.iloc[-91])
            if close_90_days_ago <= 0:
                continue

            roc_90 = ((current_price / close_90_days_ago) - 1.0) * 100.0
            ranked_candidates.append((symbol, roc_90))

        if not scanned_any:
            self._log_message(
                f"[stonxx] refresh skipped; no symbols reached the 200-bar minimum out of {len(master_universe)}",
                color="yellow",
            )
            return list(getattr(self, "universe", master_universe))

        ranked_candidates.sort(key=lambda item: (-item[1], item[0]))

        try:
            top_n = int(self._parameter("dynamic_universe_size", default=DEFAULT_DYNAMIC_UNIVERSE_SIZE))
        except (TypeError, ValueError):
            top_n = DEFAULT_DYNAMIC_UNIVERSE_SIZE
        top_n = max(0, top_n)

        self.universe = [symbol for symbol, _ in ranked_candidates[:top_n]]

        if self.universe:
            preview = ", ".join(f"{symbol} ({roc:.1f}%)" for symbol, roc in ranked_candidates[:top_n])
            self._log_message(
                f"[stonxx] refreshed active universe {len(self.universe)}/{len(master_universe)}: {preview}",
                color="green",
            )
        else:
            self._log_message(
                f"[stonxx] refreshed active universe 0/{len(master_universe)}: no names passed the momentum filters",
                color="yellow",
            )

        return list(self.universe)

    def initialize(self):
        self.set_market("XBOM")
        self.broker.data_source.tzinfo = pytz.timezone("Asia/Kolkata")
        self.sleeptime = "1D"
        self.minutes_before_closing = 0
        self.minutes_after_closing = 15

        self.master_universe = self._load_master_universe()
        self.universe = list(self.master_universe)
        self.model_path = self.parameters.get("model_path", DEFAULT_MODEL_PATH)
        self.benchmark_symbol = self.parameters.get("benchmark_symbol", BENCHMARK_TICKER)
        self._benchmark_asset = Asset(symbol=self.benchmark_symbol, asset_type=Asset.AssetType.INDEX)
        self.state_file = self.parameters.get("state_file") or STATE_FILE
        self.max_positions = int(self.parameters.get("max_positions", DEFAULT_MAX_POSITIONS))
        self.minimum_predicted_return = float(
            self.parameters.get("minimum_predicted_return", DEFAULT_MINIMUM_PREDICTED_RETURN)
        )
        self.risk_budget_pct = float(self.parameters.get("risk_budget_pct", DEFAULT_RISK_BUDGET_PCT))
        self.max_position_pct = float(self.parameters.get("max_position_pct", DEFAULT_MAX_POSITION_PCT))
        self.cooldown_trading_days = int(self.parameters.get("cooldown_trading_days", DEFAULT_COOLDOWN_TRADING_DAYS))
        self.sentiment_model = self.parameters.get("sentiment_model", DEFAULT_SENTIMENT_MODEL)
        self.sentiment_weight = float(self.parameters.get("sentiment_weight", DEFAULT_SENTIMENT_WEIGHT))
        self.sentiment_threshold_bonus = float(
            self.parameters.get("sentiment_threshold_bonus", DEFAULT_SENTIMENT_THRESHOLD_BONUS)
        )
        self.IS_PAPER_TRADING = bool(self.parameters.get("IS_PAPER_TRADING", True))
        self.paper_cash_seed = float(self.parameters.get("paper_cash", DEFAULT_PAPER_CASH))
        self._sentiment_cache: dict[str, float] = {}
        self.sentiment_engine = SentimentAnalyzer(self.sentiment_model) if SentimentAnalyzer is not None else None

        self.state = load_state(self._state_file_path())
        self.state.setdefault("active_trades", {})
        self.state.setdefault("pending_orders", [])
        self.state.setdefault("paper_cash", 0.0)
        self.state.setdefault("last_signal_date", None)
        self.state.setdefault("last_submission_date", None)
        self.state.setdefault("symbol_cooldowns", {})
        if self.IS_PAPER_TRADING and self.state["paper_cash"] <= 0:
            self.state["paper_cash"] = self.paper_cash_seed
            save_state(self.state, self._state_file_path())

        self.model = None
        self.features = list(FEATURE_COLUMNS)
        try:
            artifact = joblib.load(self.model_path)
            if isinstance(artifact, dict):
                self.model = artifact["model"]
                self.features = artifact.get("features", list(FEATURE_COLUMNS))
                mean_metrics = artifact.get("meta", {}).get("mean_metrics", {})
                self._log_message(
                    f"[stonxx] Loaded daily model {self.model_path} | mean_metrics={mean_metrics}",
                    color="green",
                )
            else:
                self.model = artifact
                self._log_message(
                    f"[stonxx] Loaded legacy model object from {self.model_path}",
                    color="yellow",
                )
        except FileNotFoundError:
            self._log_message(
                f"[stonxx] Model file {self.model_path} not found. Run train_yf_model.py first.",
                color="red",
            )

        if self.sentiment_engine is None:
            self._log_message(
                "[stonxx] Sentiment engine import unavailable; using the benchmark proxy only.",
                color="yellow",
            )

        active = self.state.get("active_trades", {})
        if active:
            tracked = ", ".join(
                f"{symbol}@{info.get('fill_price', '?')}x{info.get('quantity', '?')}" for symbol, info in active.items()
            )
            self._log_message(f"[stonxx] Restored active positions: {tracked}", color="cyan")
        else:
            self._log_message("[stonxx] No active positions restored.", color="cyan")

        try:
            self.refresh_active_universe()
        except Exception as exc:
            self._log_message(
                f"[stonxx] initial universe refresh failed; keeping master universe fallback: {exc}",
                color="yellow",
            )

        if not self.is_backtesting:
            self.register_cron_callback(AFTER_CLOSE_CRON, self.generate_after_close_plan)
            self.register_cron_callback(NEXT_OPEN_CRON, self.submit_pending_orders)
            self._schedule_weekly_universe_refresh()

        self.paper_trade_file = "paper_trades.csv"
        self._ensure_paper_trade_file()

    def _ensure_paper_trade_file(self) -> None:
        if os.path.exists(self.paper_trade_file):
            return
        with open(self.paper_trade_file, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Asset", "Direction", "Quantity", "Entry", "TakeProfit", "StopLoss"])

    def _current_holdings(self) -> dict[str, dict]:
        if self.IS_PAPER_TRADING:
            return {
                symbol: dict(info)
                for symbol, info in self.state.get("active_trades", {}).items()
                if int(info.get("quantity", 0)) > 0
            }

        holdings: dict[str, dict] = {}
        for position in self.get_positions():
            if position.asset.asset_type != Asset.AssetType.STOCK or position.quantity <= 0:
                continue
            holdings[position.asset.symbol.upper()] = {
                "quantity": int(position.quantity),
                "fill_price": float(getattr(position, "avg_fill_price", 0.0) or 0.0),
            }
        return holdings

    def _paper_portfolio_value(self, reference_prices: dict[str, float]) -> float:
        cash = float(self.state.get("paper_cash", self.paper_cash_seed))
        holdings_value = 0.0
        for symbol, info in self.state.get("active_trades", {}).items():
            price = reference_prices.get(symbol, float(info.get("fill_price", 0.0) or 0.0))
            holdings_value += int(info.get("quantity", 0)) * price
        return cash + holdings_value

    def _record_paper_trade(
        self,
        asset_symbol: str,
        direction: str,
        quantity: int,
        price: float,
        *,
        extra_note: str = "",
    ) -> None:
        timestamp = self.get_datetime().strftime("%Y-%m-%d %H:%M:%S")
        self.log_message(
            f"PAPER {direction} {asset_symbol} qty={quantity} price={price:.2f} {extra_note}".strip(),
            color="cyan",
        )
        with open(self.paper_trade_file, mode="a", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([timestamp, asset_symbol, direction, quantity, round(price, 4), extra_note, ""])

    def _compute_atr_20(self, stock_history: pd.DataFrame) -> float | None:
        normalized = normalize_history_frame(stock_history)
        atr_series = compute_true_range(normalized).rolling(20).mean()
        value = atr_series.iloc[-1] if not atr_series.empty else None
        if value is None or pd.isna(value):
            return None
        return float(value)

    def _advance_trading_days(self, trading_date, trading_days: int):
        candidate = trading_date
        for _ in range(max(trading_days, 0)):
            candidate = next_trading_day(candidate)
        return candidate

    def _cooldown_until_for_symbol(self, symbol: str):
        symbol_cooldowns = self.state.get("symbol_cooldowns", {})
        return symbol_cooldowns.get(symbol)

    def _is_symbol_on_cooldown(self, symbol: str) -> bool:
        if int(getattr(self, "cooldown_trading_days", 0) or 0) <= 0:
            return False

        cooldown_until = self._cooldown_until_for_symbol(symbol)
        if not cooldown_until:
            return False

        today = self.get_datetime().date().isoformat()
        return today < str(cooldown_until)

    def _mark_symbol_cooldown(self, symbol: str) -> None:
        cooldown_trading_days = int(getattr(self, "cooldown_trading_days", 0) or 0)
        if cooldown_trading_days <= 0:
            return

        cooldown_until = self._advance_trading_days(self.get_datetime().date(), cooldown_trading_days).isoformat()
        self.state.setdefault("symbol_cooldowns", {})[symbol] = cooldown_until
        self.log_message(
            f"[stonxx] {symbol} entered cooldown until {cooldown_until}",
            color="yellow",
        )

    def _clear_symbol_cooldown(self, symbol: str) -> None:
        self.state.setdefault("symbol_cooldowns", {}).pop(symbol, None)

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            return default

        if math.isnan(candidate) or math.isinf(candidate):
            return default
        return candidate

    def _market_proxy_sentiment(self, signal: dict) -> float:
        benchmark_return_30 = self._safe_float(signal.get("benchmark_return_30"), 0.0)
        benchmark_alpha = self._safe_float(signal.get("benchmark_alpha"), 0.0)
        raw_score = benchmark_return_30 + 0.5 * benchmark_alpha
        return max(-1.0, min(1.0, math.tanh(raw_score / 0.04)))

    def _news_sentiment_score(self, asset_symbol: str) -> float:
        if self.sentiment_engine is None or self.is_backtesting:
            return 0.0

        cache_key = f"{self.get_datetime().date().isoformat()}:{asset_symbol.upper()}"
        cached = self._sentiment_cache.get(cache_key)
        if cached is not None:
            return self._safe_float(cached, 0.0)

        try:
            score = float(self.sentiment_engine.analyze_sentiment(asset=asset_symbol))
        except Exception as exc:
            self.log_message(f"[stonxx] Sentiment lookup failed for {asset_symbol}: {exc}", color="yellow")
            score = 0.0

        self._sentiment_cache[cache_key] = score
        return score

    def _combined_sentiment_score(self, signal: dict) -> float:
        proxy_score = self._market_proxy_sentiment(signal)
        if self.is_backtesting or self.sentiment_engine is None:
            return proxy_score

        market_news = self._news_sentiment_score(self.benchmark_symbol)
        symbol_news = self._news_sentiment_score(signal["symbol"])
        blended_news = (market_news + symbol_news) / 2.0
        return max(-1.0, min(1.0, proxy_score + (self.sentiment_weight * blended_news)))

    def _apply_sentiment_overlay(self, signal: dict) -> dict:
        sentiment_score = self._combined_sentiment_score(signal)
        sentiment_shift = self.sentiment_threshold_bonus * max(self.minimum_predicted_return, 0.005) * sentiment_score
        adjusted_predicted_return = self._safe_float(signal["predicted_return"], 0.0) + sentiment_shift
        sentiment_multiplier = max(0.5, 1.0 + (self.sentiment_weight * sentiment_score))

        adjusted_signal = dict(signal)
        adjusted_signal["sentiment_score"] = sentiment_score
        adjusted_signal["sentiment_multiplier"] = sentiment_multiplier
        adjusted_signal["adjusted_predicted_return"] = adjusted_predicted_return
        return adjusted_signal

    def _model_signal_for_symbol(self, symbol: str) -> dict | None:
        if self.model is None:
            return None

        asset = Asset(symbol=symbol, asset_type=Asset.AssetType.STOCK)
        stock_bars = self.get_historical_prices(asset, 80, "day")
        benchmark_bars = self.get_historical_prices(self._benchmark_asset, 80, "day")

        if stock_bars is None or benchmark_bars is None:
            self.log_message(f"[stonxx] Missing daily history for {symbol} or benchmark.", color="yellow")
            return None

        try:
            feature_frame = prepare_symbol_inference_frame(
                stock_bars.df,
                benchmark_bars.df,
                ticker=symbol,
            )
        except Exception as exc:
            self.log_message(f"[stonxx] Feature build failed for {symbol}: {exc}", color="red")
            return None

        if feature_frame.empty:
            self.log_message(f"[stonxx] Feature frame empty for {symbol}.", color="yellow")
            return None

        missing = [feature for feature in self.features if feature not in feature_frame.columns]
        if missing:
            self.log_message(f"[stonxx] Missing features for {symbol}: {missing}", color="red")
            return None

        latest = feature_frame[self.features].iloc[[-1]]
        predicted_return = float(self.model.predict(latest)[0])
        latest_row = feature_frame.iloc[-1]

        normalized_stock = normalize_history_frame(stock_bars.df)
        atr_20 = self._compute_atr_20(normalized_stock)
        if atr_20 is None:
            self.log_message(f"[stonxx] ATR_20 unavailable for {symbol}.", color="yellow")
            return None

        current_price = float(normalized_stock["close"].iloc[-1])
        signal = {
            "symbol": symbol,
            "predicted_return": predicted_return,
            "current_price": current_price,
            "atr_20": atr_20,
            "benchmark_return_30": self._safe_float(latest_row.get("benchmark_return_30"), 0.0),
            "benchmark_alpha": self._safe_float(latest_row.get("benchmark_alpha"), 0.0),
            "rsi_5": self._safe_float(latest_row.get("rsi_5"), 0.0),
        }
        return self._apply_sentiment_overlay(signal)

    def _reference_prices_for_holdings(self, holdings: dict[str, dict], signals: list[dict]) -> dict[str, float]:
        prices = {signal["symbol"]: signal["current_price"] for signal in signals}
        for symbol, info in holdings.items():
            prices.setdefault(symbol, float(info.get("fill_price", 0.0) or 0.0))
        return prices

    def _queue_orders_for_next_open(self, signals: list[dict]) -> list[dict]:
        holdings = self._current_holdings()
        selected = rank_long_candidates(
            signals,
            minimum_predicted_return=self.minimum_predicted_return,
            max_positions=self.max_positions,
        )
        selected_symbols = {signal["symbol"] for signal in selected}
        reference_prices = self._reference_prices_for_holdings(holdings, signals)

        if self.IS_PAPER_TRADING:
            portfolio_value = self._paper_portfolio_value(reference_prices)
            available_cash = float(self.state.get("paper_cash", self.paper_cash_seed))
        else:
            portfolio_value = float(self.get_portfolio_value())
            available_cash = float(self.get_cash())

        pending_orders: list[dict] = []

        for symbol, info in holdings.items():
            if symbol not in selected_symbols:
                pending_orders.append(
                    {
                        "symbol": symbol,
                        "side": "sell",
                        "quantity": int(info["quantity"]),
                        "signal_date": self.get_datetime().date().isoformat(),
                        "execution_date": next_trading_day(self.get_datetime().date()).isoformat(),
                        "reference_price": reference_prices.get(symbol, float(info.get("fill_price", 0.0) or 0.0)),
                        "predicted_return": None,
                        "order_note": "EXIT_TO_CASH",
                    }
                )
                available_cash += int(info["quantity"]) * reference_prices.get(symbol, 0.0)

        for signal in selected:
            symbol = signal["symbol"]
            if symbol in holdings:
                continue
            if self._is_symbol_on_cooldown(symbol):
                self.log_message(
                    f"[stonxx] Skipping {symbol} due to cooldown until {self._cooldown_until_for_symbol(symbol)}.",
                    color="yellow",
                )
                continue

            quantity = compute_order_quantity(
                portfolio_value=portfolio_value,
                current_price=signal["current_price"],
                atr_20=signal["atr_20"],
                available_cash=available_cash,
                risk_budget_pct=self.risk_budget_pct,
                max_position_pct=self.max_position_pct,
            )
            quantity = int(quantity * self._safe_float(signal.get("sentiment_multiplier"), 1.0))
            max_shares_allowed = (
                int((portfolio_value * self.max_position_pct) / signal["current_price"])
                if signal["current_price"] > 0
                else 0
            )
            max_affordable = int(available_cash / signal["current_price"]) if signal["current_price"] > 0 else 0
            quantity = max(0, min(quantity, max_shares_allowed, max_affordable))
            if quantity <= 0:
                self.log_message(
                    f"[stonxx] {symbol} cleared the threshold but size resolved to 0.",
                    color="yellow",
                )
                continue

            pending_orders.append(
                {
                    "symbol": symbol,
                    "side": "buy",
                    "quantity": quantity,
                    "signal_date": self.get_datetime().date().isoformat(),
                    "execution_date": next_trading_day(self.get_datetime().date()).isoformat(),
                    "reference_price": signal["current_price"],
                    "predicted_return": signal["predicted_return"],
                    "adjusted_predicted_return": signal.get("adjusted_predicted_return"),
                    "sentiment_score": signal.get("sentiment_score"),
                    "order_note": "LONG_ENTRY",
                }
            )
            available_cash -= quantity * signal["current_price"]

        return pending_orders

    def _submit_order_batch(self, orders: list[dict]) -> None:
        if not orders:
            return

        ordered_orders = sorted(orders, key=lambda item: 0 if item["side"] == "sell" else 1)

        if self.IS_PAPER_TRADING:
            for order in ordered_orders:
                self._paper_execute_order(order)
            return

        for order in ordered_orders:
            asset = Asset(symbol=order["symbol"], asset_type=Asset.AssetType.STOCK)
            lumi_order = self.create_order(
                asset=asset,
                quantity=int(order["quantity"]),
                side=order["side"],
                order_type="market",
                time_in_force="day",
            )
            self.submit_order(lumi_order)
            self.log_message(
                (
                    f"[stonxx] Submitted next-open market order: "
                    f"{order['side'].upper()} {order['symbol']} x{order['quantity']}"
                ),
                color="green",
            )

    def generate_after_close_plan(self):
        today = self.get_datetime().date().isoformat()
        if self.state.get("last_signal_date") == today:
            return

        # Backtests do not run the live morning cron callback, so flush any
        # pending next-open orders here before we overwrite the queue with the
        # next day's signals. This keeps the simulated equity curve from staying
        # flat when the strategy is run in historical mode.
        if self.is_backtesting:
            self.submit_pending_orders()

        signals = []
        for symbol in self.universe:
            signal = self._model_signal_for_symbol(symbol)
            if signal is None:
                continue
            signals.append(signal)
            sentiment_score = signal.get("sentiment_score", 0.0)
            self.log_message(
                f"[stonxx] {symbol} predicted 5D return={signal['predicted_return']:.4%} "
                f"| adjusted={signal['adjusted_predicted_return']:.4%} "
                f"| sentiment={sentiment_score:+.2f} | close={signal['current_price']:.2f} | ATR20={signal['atr_20']:.2f}",
                color="blue",
            )

        pending_orders = self._queue_orders_for_next_open(signals)
        self.state["pending_orders"] = pending_orders
        self.state["last_signal_date"] = today
        save_state(self.state, self._state_file_path())

        if self.is_backtesting and pending_orders:
            self._submit_order_batch(pending_orders)
            self.state["pending_orders"] = []
            self.state["last_submission_date"] = today
            save_state(self.state, self._state_file_path())

        if not pending_orders:
            self.log_message(
                "[stonxx] No symbols cleared the threshold. Existing positions will be exited and cash preserved."
                if self._current_holdings()
                else "[stonxx] No qualifying longs for next session. Holding cash.",
                color="yellow",
            )
            return

        summary = ", ".join(
            f"{order['side'].upper()} {order['symbol']} x{order['quantity']}" for order in pending_orders
        )
        self.log_message(f"[stonxx] Queued next-open orders: {summary}", color="green")

        if self.IS_PAPER_TRADING:
            for order in pending_orders:
                direction = f"{order['side'].upper()}_NEXT_OPEN"
                note = order["order_note"]
                if order.get("predicted_return") is not None:
                    note = f"{note} pred={order['predicted_return']:.4%}"
                self._record_paper_trade(
                    order["symbol"],
                    direction,
                    order["quantity"],
                    order["reference_price"],
                    extra_note=note,
                )

    def _paper_execute_order(self, order: dict) -> None:
        asset = Asset(symbol=order["symbol"], asset_type=Asset.AssetType.STOCK)
        fill_price = float(self.get_last_price(asset) or order["reference_price"])

        if order["side"] == "sell":
            current = self.state["active_trades"].pop(order["symbol"], None)
            if current is None:
                return
            quantity = min(int(order["quantity"]), int(current.get("quantity", 0)))
            self.state["paper_cash"] += quantity * fill_price
            self._record_paper_trade(order["symbol"], "SELL_FILLED", quantity, fill_price, extra_note="NEXT_OPEN")
            return

        quantity = int(order["quantity"])
        max_affordable = int(float(self.state["paper_cash"]) / fill_price) if fill_price > 0 else 0
        quantity = min(quantity, max_affordable)
        if quantity <= 0:
            self.log_message(
                f"[stonxx] Skipping paper BUY for {order['symbol']} due to cash constraints.",
                color="yellow",
            )
            return

        self.state["paper_cash"] -= quantity * fill_price
        self.state["active_trades"][order["symbol"]] = {
            "fill_price": round(fill_price, 4),
            "quantity": quantity,
        }
        self._record_paper_trade(order["symbol"], "BUY_FILLED", quantity, fill_price, extra_note="NEXT_OPEN")

    def submit_pending_orders(self):
        today = self.get_datetime().date().isoformat()
        if self.state.get("last_submission_date") == today:
            return

        due_orders = [
            order
            for order in self.state.get("pending_orders", [])
            if order.get("execution_date") and order["execution_date"] <= today
        ]
        if not due_orders:
            return

        self._submit_order_batch(due_orders)

        remaining = [order for order in self.state.get("pending_orders", []) if order not in due_orders]
        self.state["pending_orders"] = remaining
        self.state["last_submission_date"] = today
        save_state(self.state, self._state_file_path())

    def on_trading_iteration(self):
        # Backtests do not register the live cron callbacks, so reuse the
        # morning submission path here to keep queued next-open orders from
        # staying stranded and producing a flat equity curve.
        if self.is_backtesting:
            self.submit_pending_orders()
            return

        now = self.get_datetime()
        if now.weekday() >= 5:
            return
        if (now.hour, now.minute) >= (9, 16) and (now.hour, now.minute) <= (9, 30):
            self.submit_pending_orders()

    def after_market_closes(self):
        self.generate_after_close_plan()

    def on_filled_order(self, position, order, price, quantity, multiplier):
        symbol = order.asset.symbol

        if order.side == "buy":
            self._clear_symbol_cooldown(symbol)
            self.state["active_trades"][symbol] = {
                "fill_price": round(float(price), 4),
                "quantity": int(quantity),
            }
            save_state(self.state, self._state_file_path())
            self.log_message(
                f"[stonxx] BUY filled {symbol} qty={quantity} @ {price:.2f}",
                color="green",
            )
            return

        if order.side == "sell":
            current_trade = self.state["active_trades"].get(symbol)
            if current_trade is not None:
                entry_price = float(current_trade.get("fill_price", 0.0) or 0.0)
                if entry_price > 0:
                    realized_return = (float(price) - entry_price) / entry_price
                    if realized_return <= 0:
                        self._mark_symbol_cooldown(symbol)
                    else:
                        self._clear_symbol_cooldown(symbol)

            pos_qty = getattr(position, "quantity", 0) or 0
            if pos_qty <= 0:
                self.state["active_trades"].pop(symbol, None)
            else:
                self.state["active_trades"][symbol] = {
                    "fill_price": round(float(price), 4),
                    "quantity": int(pos_qty),
                }
            save_state(self.state, self._state_file_path())
            self.log_message(f"[stonxx] SELL filled {symbol} qty={quantity} @ {price:.2f}", color="magenta")
