from types import SimpleNamespace

import pytest

from lumibot.example_strategies import india_ai_trader as india_ai_trader_module


class FakeSentimentAnalyzer:
    def __init__(self, scores: dict[str, float]):
        self.scores = scores
        self.calls: list[str] = []

    def fetch_text_data(self, asset: str = "NIFTY") -> list[str]:
        self.calls.append(f"fetch:{asset}")
        return [f"{asset} headline 1", f"{asset} headline 2"]

    def analyze_sentiment(self, text_list=None, asset: str = "NIFTY") -> float:
        self.calls.append(asset)
        return self.scores.get(asset, 0.0)


class FakeAgent:
    def __init__(self):
        self.calls: list[dict] = []

    def run(self, task_prompt=None, context=None):
        self.calls.append({"task_prompt": task_prompt, "context": context})
        return SimpleNamespace(summary="agent summary")


def _build_strategy():
    strategy = india_ai_trader_module.IndiaAITrader.__new__(india_ai_trader_module.IndiaAITrader)
    strategy.universe = ["RELIANCE", "INFY"]
    strategy.product_type = "MIS"
    strategy.risk_per_trade_pct = 1.0
    strategy.max_positions = 3
    strategy.agent_run_every_n_bars = 1
    strategy.sentiment_model = "llama3.2"
    strategy.sentiment_buy_block_threshold = 0.25
    strategy.sentiment_neutral_score = 0.5
    strategy.sentiment_timeout_seconds = 8
    strategy.sentiment_max_headlines = 5
    strategy._sentiment_snapshot_cache = {}
    strategy._blocked_buy_symbols = set()
    strategy.sentiment_engine = None
    strategy.vars = SimpleNamespace(bar_count=0)
    strategy.log_message = lambda *args, **kwargs: None
    strategy.set_market = lambda *args, **kwargs: None
    strategy.get_positions = lambda: []
    strategy.get_cash = lambda: 1_000_000.0
    strategy.get_portfolio_value = lambda: 1_000_000.0
    strategy.get_last_price = lambda asset: 100.0
    strategy.create_order = lambda *args, **kwargs: SimpleNamespace(asset=args[0], side=args[2])
    return strategy


def test_backtest_sentiment_snapshot_is_neutral():
    strategy = _build_strategy()
    strategy.is_backtesting = True
    strategy.sentiment_engine = FakeSentimentAnalyzer({"RELIANCE": -0.9})

    snapshot = strategy._fetch_sentiment_snapshot("RELIANCE")

    assert snapshot["current_technical_sentiment_score"] == pytest.approx(0.5)
    assert snapshot["buy_blocked_due_to_sentiment"] is False
    assert snapshot["sentiment_source"] == "backtest_neutral"


def test_live_iteration_passes_sentiment_context_and_blocks_low_scores(monkeypatch):
    strategy = _build_strategy()
    strategy.is_backtesting = False
    strategy.sentiment_engine = FakeSentimentAnalyzer({"RELIANCE": 0.8, "INFY": -0.5})

    agent = FakeAgent()
    strategy.agents = {"india_trader": agent}

    monkeypatch.setattr(india_ai_trader_module, "_is_market_open_ist", lambda: True)
    monkeypatch.setattr(india_ai_trader_module, "_is_mis_squareoff_time", lambda: False)

    strategy.on_trading_iteration()

    assert len(agent.calls) == 1
    call = agent.calls[0]
    assert "Current Technical Sentiment Score:" in call["task_prompt"]
    assert call["context"]["current_technical_sentiment_score"] == pytest.approx(0.57, rel=1e-2)
    assert call["context"]["sentiment_by_symbol"]["RELIANCE"]["current_technical_sentiment_score"] == pytest.approx(0.9)
    assert call["context"]["sentiment_by_symbol"]["INFY"]["buy_blocked_due_to_sentiment"] is True
    assert strategy._blocked_buy_symbols == {"INFY"}


def test_submit_order_blocks_low_sentiment_buy_orders():
    strategy = _build_strategy()
    strategy.is_backtesting = False
    strategy._blocked_buy_symbols = {"RELIANCE"}

    blocked_order = SimpleNamespace(asset=SimpleNamespace(symbol="RELIANCE"), side="buy")

    with pytest.raises(ValueError):
        strategy.submit_order(blocked_order)
