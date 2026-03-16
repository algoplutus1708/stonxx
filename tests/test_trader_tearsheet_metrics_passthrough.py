from __future__ import annotations

from datetime import datetime

from lumibot.traders.trader import Trader


class _DummyBroker:
    def is_backtesting_broker(self):
        return True


class _DummyStrategy:
    def __init__(self):
        self.broker = _DummyBroker()
        self._analyze_backtest = True
        self._name = "DummyStrategy"
        self.backtesting_start = datetime(2019, 1, 2)
        self.backtesting_end = datetime(2019, 1, 3)
        self.backtest_analysis_kwargs = None

    def verify_backtest_inputs(self, start, end):
        return start, end

    def backtest_analysis(self, **kwargs):
        self.backtest_analysis_kwargs = kwargs


def test_trader_run_all_passes_tearsheet_metrics_file(monkeypatch):
    trader = Trader(backtest=True, logfile="")
    strategy = _DummyStrategy()
    trader.add_strategy(strategy)

    monkeypatch.setattr(trader, "_set_logger", lambda: None)
    monkeypatch.setattr(trader, "_init_pool", lambda: None)
    monkeypatch.setattr(trader, "_start_pool", lambda: None)
    monkeypatch.setattr(trader, "_join_pool", lambda: None)
    monkeypatch.setattr(trader, "_collect_analysis", lambda: {strategy._name: {}})

    trader.run_all(
        show_plot=False,
        show_tearsheet=False,
        save_tearsheet=True,
        show_indicators=False,
        tearsheet_file="dummy_tearsheet.html",
        tearsheet_metrics_file="dummy_tearsheet_metrics.json",
        base_filename=strategy._name,
    )

    assert strategy.backtest_analysis_kwargs is not None
    assert strategy.backtest_analysis_kwargs["tearsheet_metrics_file"] == "dummy_tearsheet_metrics.json"
