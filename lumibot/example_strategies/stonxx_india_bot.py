"""Long-only daily swing execution for the stonxx paper/live workflow.

The model is trained on fully closed daily bars, so the strategy performs its
signal generation after the NSE cash session has closed and queues next-open
orders instead of trading incomplete same-day bars.
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta

import joblib
import pandas as pd

from lumibot.entities import Asset
from lumibot.strategies.strategy import Strategy

try:
    from state_manager import load_state, save_state
except ImportError:
    from lumibot.example_strategies.state_manager import load_state, save_state

from train_yf_model import (
    BENCHMARK_TICKER,
    FEATURE_COLUMNS,
    compute_true_range,
    normalize_history_frame,
    prepare_symbol_inference_frame,
)

DEFAULT_UNIVERSE = [
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
AFTER_CLOSE_CRON = "45 15 * * 1-5"
NEXT_OPEN_CRON = "16 9 * * 1-5"


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
    ranked = sorted(signals, key=lambda item: item["predicted_return"], reverse=True)
    filtered = [item for item in ranked if item["predicted_return"] >= minimum_predicted_return]
    return filtered[:max_positions]


class stonxx(Strategy):
    """Daily long-only swing strategy using next-open execution intents."""

    def initialize(self):
        self.set_market("NSE_INDIA")
        self.sleeptime = "1D"
        self.minutes_before_closing = 0
        self.minutes_after_closing = 15

        self.universe = [symbol.upper() for symbol in self.parameters.get("universe", DEFAULT_UNIVERSE)]
        self.model_path = self.parameters.get("model_path", DEFAULT_MODEL_PATH)
        self.benchmark_symbol = self.parameters.get("benchmark_symbol", BENCHMARK_TICKER)
        self.max_positions = int(self.parameters.get("max_positions", DEFAULT_MAX_POSITIONS))
        self.minimum_predicted_return = float(
            self.parameters.get("minimum_predicted_return", DEFAULT_MINIMUM_PREDICTED_RETURN)
        )
        self.risk_budget_pct = float(self.parameters.get("risk_budget_pct", DEFAULT_RISK_BUDGET_PCT))
        self.max_position_pct = float(self.parameters.get("max_position_pct", DEFAULT_MAX_POSITION_PCT))
        self.IS_PAPER_TRADING = bool(self.parameters.get("IS_PAPER_TRADING", True))
        self.paper_cash_seed = float(self.parameters.get("paper_cash", DEFAULT_PAPER_CASH))

        self.state = load_state()
        self.state.setdefault("active_trades", {})
        self.state.setdefault("pending_orders", [])
        self.state.setdefault("paper_cash", 0.0)
        self.state.setdefault("last_signal_date", None)
        self.state.setdefault("last_submission_date", None)
        if self.IS_PAPER_TRADING and self.state["paper_cash"] <= 0:
            self.state["paper_cash"] = self.paper_cash_seed
            save_state(self.state)

        self.model = None
        self.features = list(FEATURE_COLUMNS)
        try:
            artifact = joblib.load(self.model_path)
            if isinstance(artifact, dict):
                self.model = artifact["model"]
                self.features = artifact.get("features", list(FEATURE_COLUMNS))
                mean_metrics = artifact.get("meta", {}).get("mean_metrics", {})
                self.log_message(
                    f"[stonxx] Loaded daily model {self.model_path} | mean_metrics={mean_metrics}",
                    color="green",
                )
            else:
                self.model = artifact
                self.log_message(
                    f"[stonxx] Loaded legacy model object from {self.model_path}",
                    color="yellow",
                )
        except FileNotFoundError:
            self.log_message(
                f"[stonxx] Model file {self.model_path} not found. Run train_yf_model.py first.",
                color="red",
            )

        active = self.state.get("active_trades", {})
        if active:
            tracked = ", ".join(
                f"{symbol}@{info.get('fill_price', '?')}x{info.get('quantity', '?')}"
                for symbol, info in active.items()
            )
            self.log_message(f"[stonxx] Restored active positions: {tracked}", color="cyan")
        else:
            self.log_message("[stonxx] No active positions restored.", color="cyan")

        if not self.is_backtesting:
            self.register_cron_callback(AFTER_CLOSE_CRON, self.generate_after_close_plan)
            self.register_cron_callback(NEXT_OPEN_CRON, self.submit_pending_orders)

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

    def _benchmark_asset(self) -> Asset:
        return Asset(symbol=self.benchmark_symbol, asset_type=Asset.AssetType.INDEX)

    def _compute_atr_20(self, stock_history: pd.DataFrame) -> float | None:
        normalized = normalize_history_frame(stock_history)
        atr_series = compute_true_range(normalized).rolling(20).mean()
        value = atr_series.iloc[-1] if not atr_series.empty else None
        if value is None or pd.isna(value):
            return None
        return float(value)

    def _model_signal_for_symbol(self, symbol: str) -> dict | None:
        if self.model is None:
            return None

        asset = Asset(symbol=symbol, asset_type=Asset.AssetType.STOCK)
        stock_bars = self.get_historical_prices(asset, 80, "day")
        benchmark_bars = self.get_historical_prices(self._benchmark_asset(), 80, "day")

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

        normalized_stock = normalize_history_frame(stock_bars.df)
        atr_20 = self._compute_atr_20(normalized_stock)
        if atr_20 is None:
            self.log_message(f"[stonxx] ATR_20 unavailable for {symbol}.", color="yellow")
            return None

        current_price = float(normalized_stock["close"].iloc[-1])
        return {
            "symbol": symbol,
            "predicted_return": predicted_return,
            "current_price": current_price,
            "atr_20": atr_20,
        }

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

            quantity = compute_order_quantity(
                portfolio_value=portfolio_value,
                current_price=signal["current_price"],
                atr_20=signal["atr_20"],
                available_cash=available_cash,
                risk_budget_pct=self.risk_budget_pct,
                max_position_pct=self.max_position_pct,
            )
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
                    "order_note": "LONG_ENTRY",
                }
            )
            available_cash -= quantity * signal["current_price"]

        return pending_orders

    def generate_after_close_plan(self):
        today = self.get_datetime().date().isoformat()
        if self.state.get("last_signal_date") == today:
            return

        signals = []
        for symbol in self.universe:
            signal = self._model_signal_for_symbol(symbol)
            if signal is None:
                continue
            signals.append(signal)
            self.log_message(
                f"[stonxx] {symbol} predicted 5D return={signal['predicted_return']:.4%} "
                f"| close={signal['current_price']:.2f} | ATR20={signal['atr_20']:.2f}",
                color="blue",
            )

        pending_orders = self._queue_orders_for_next_open(signals)
        self.state["pending_orders"] = pending_orders
        self.state["last_signal_date"] = today
        save_state(self.state)

        if not pending_orders:
            self.log_message(
                "[stonxx] No symbols cleared the threshold. Existing positions will be exited and cash preserved."
                if self._current_holdings()
                else "[stonxx] No qualifying longs for next session. Holding cash.",
                color="yellow",
            )
            return

        summary = ", ".join(
            f"{order['side'].upper()} {order['symbol']} x{order['quantity']}"
            for order in pending_orders
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
            self.log_message(f"[stonxx] Skipping paper BUY for {order['symbol']} due to cash constraints.", color="yellow")
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

        due_orders = sorted(due_orders, key=lambda item: 0 if item["side"] == "sell" else 1)

        if self.IS_PAPER_TRADING:
            for order in due_orders:
                self._paper_execute_order(order)
        else:
            for order in due_orders:
                asset = Asset(symbol=order["symbol"], asset_type=Asset.AssetType.STOCK)
                lumi_order = self.create_order(
                    asset=asset,
                    quantity=int(order["quantity"]),
                    side=order["side"],
                    type="market",
                    time_in_force="day",
                    tag="NEXT_OPEN",
                )
                self.submit_order(lumi_order)
                self.log_message(
                    f"[stonxx] Submitted next-open market order: {order['side'].upper()} {order['symbol']} x{order['quantity']}",
                    color="green",
                )

        remaining = [
            order
            for order in self.state.get("pending_orders", [])
            if order not in due_orders
        ]
        self.state["pending_orders"] = remaining
        self.state["last_submission_date"] = today
        save_state(self.state)

    def on_trading_iteration(self):
        # Safety fallback: if the morning cron was missed, submit queued orders
        # during the first live iteration after the open.
        if self.is_backtesting:
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
            self.state["active_trades"][symbol] = {
                "fill_price": round(float(price), 4),
                "quantity": int(quantity),
            }
            save_state(self.state)
            self.log_message(
                f"[stonxx] BUY filled {symbol} qty={quantity} @ {price:.2f}",
                color="green",
            )
            return

        if order.side == "sell":
            pos_qty = getattr(position, "quantity", 0) or 0
            if pos_qty <= 0:
                self.state["active_trades"].pop(symbol, None)
            else:
                self.state["active_trades"][symbol] = {
                    "fill_price": round(float(price), 4),
                    "quantity": int(pos_qty),
                }
            save_state(self.state)
            self.log_message(f"[stonxx] SELL filled {symbol} qty={quantity} @ {price:.2f}", color="magenta")
