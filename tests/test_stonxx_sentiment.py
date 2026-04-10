from datetime import datetime

import math

import pytest

from lumibot.example_strategies.stonxx_india_bot import rank_long_candidates, stonxx


class FakeSentimentAnalyzer:
    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.calls: list[str] = []

    def analyze_sentiment(self, text_list=None, asset: str = "NIFTY") -> float:
        self.calls.append(asset)
        return self.scores.get(asset, 0.0)


def _build_strategy(*, is_backtesting: bool, sentiment_engine=None):
    strategy = stonxx.__new__(stonxx)
    strategy.sentiment_weight = 0.35
    strategy.sentiment_threshold_bonus = 0.75
    strategy.minimum_predicted_return = 0.01
    strategy.sentiment_engine = sentiment_engine
    strategy.sentiment_model = "llama3.2"
    strategy.is_backtesting = is_backtesting
    strategy.benchmark_symbol = "^NSEI"
    strategy._sentiment_cache = {}
    strategy.get_datetime = lambda: datetime(2025, 1, 2, 15, 45)
    strategy.log_message = lambda *args, **kwargs: None
    return strategy


def test_live_sentiment_overlay_boosts_the_model_score():
    engine = FakeSentimentAnalyzer({"^NSEI": 0.8, "RELIANCE": 0.4})
    strategy = _build_strategy(is_backtesting=False, sentiment_engine=engine)

    signal = {
        "symbol": "RELIANCE",
        "predicted_return": 0.015,
        "benchmark_return_30": 0.01,
        "benchmark_alpha": 0.0,
    }

    adjusted = strategy._apply_sentiment_overlay(signal)

    assert adjusted["sentiment_score"] > 0
    assert adjusted["adjusted_predicted_return"] > signal["predicted_return"]
    assert adjusted["sentiment_multiplier"] > 1.0
    assert engine.calls == ["^NSEI", "RELIANCE"]


def test_backtest_sentiment_uses_the_proxy_without_news_calls():
    engine = FakeSentimentAnalyzer({"^NSEI": -0.9, "RELIANCE": -0.9})
    strategy = _build_strategy(is_backtesting=True, sentiment_engine=engine)

    signal = {
        "symbol": "RELIANCE",
        "predicted_return": 0.015,
        "benchmark_return_30": 0.04,
        "benchmark_alpha": 0.01,
    }

    score = strategy._combined_sentiment_score(signal)
    expected = math.tanh((0.04 + (0.5 * 0.01)) / 0.04)

    assert score == pytest.approx(expected)
    assert engine.calls == []


def test_queue_orders_rank_and_size_by_adjusted_sentiment():
    strategy = _build_strategy(is_backtesting=True, sentiment_engine=None)
    strategy.max_positions = 2
    strategy.risk_budget_pct = 0.01
    strategy.max_position_pct = 1.0
    strategy.IS_PAPER_TRADING = False
    strategy.paper_cash_seed = 100_000.0
    strategy.state = {
        "active_trades": {},
        "pending_orders": [],
        "paper_cash": 0.0,
        "last_signal_date": None,
        "last_submission_date": None,
        "symbol_cooldowns": {},
    }
    strategy._current_holdings = lambda: {}
    strategy._is_symbol_on_cooldown = lambda symbol: False
    strategy._reference_prices_for_holdings = lambda holdings, signals: {}
    strategy.get_portfolio_value = lambda: 100_000.0
    strategy.get_cash = lambda: 100_000.0

    stronger_signal = strategy._apply_sentiment_overlay(
        {
            "symbol": "LEADER",
            "predicted_return": 0.012,
            "current_price": 100.0,
            "atr_20": 5.0,
            "benchmark_return_30": 0.03,
            "benchmark_alpha": 0.0,
        }
    )
    weaker_signal = strategy._apply_sentiment_overlay(
        {
            "symbol": "LAGGARD",
            "predicted_return": 0.014,
            "current_price": 100.0,
            "atr_20": 5.0,
            "benchmark_return_30": -0.03,
            "benchmark_alpha": 0.0,
        }
    )

    pending_orders = strategy._queue_orders_for_next_open([stronger_signal, weaker_signal])

    assert [order["symbol"] for order in pending_orders] == ["LEADER"]
    assert pending_orders[0]["quantity"] > 200
    assert pending_orders[0]["adjusted_predicted_return"] > pending_orders[0]["predicted_return"]


def test_rank_long_candidates_prefers_adjusted_scores():
    candidates = [
        {"symbol": "A", "predicted_return": 0.030, "adjusted_predicted_return": 0.020},
        {"symbol": "B", "predicted_return": 0.020, "adjusted_predicted_return": 0.025},
    ]

    ranked = rank_long_candidates(candidates, minimum_predicted_return=0.01, max_positions=2)

    assert [item["symbol"] for item in ranked] == ["B", "A"]
