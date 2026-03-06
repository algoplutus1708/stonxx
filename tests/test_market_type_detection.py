from datetime import datetime

import pytest

from lumibot.backtesting import BacktestingBroker, PandasDataBacktesting
from lumibot.strategies.strategy import Strategy
from lumibot.strategies.strategy_executor import StrategyExecutor


class _NoopStrategy(Strategy):
    """Minimal strategy stub for StrategyExecutor tests."""

    def initialize(self):
        self.set_market("us_futures")

    def on_trading_iteration(self):
        pass


class _DailyNoopStrategy(Strategy):
    def initialize(self):
        self.sleeptime = "1D"
        self.set_market("NYSE")

    def on_trading_iteration(self):
        pass


class _MinuteNoopStrategy(Strategy):
    def initialize(self):
        self.sleeptime = "1M"
        self.set_market("NYSE")

    def on_trading_iteration(self):
        pass


@pytest.fixture
def strategy_executor():
    broker = PandasDataBacktesting(
        datetime_start=datetime(2025, 10, 28),
        datetime_end=datetime(2025, 11, 6),
    )
    backtesting_broker = BacktestingBroker(data_source=broker)
    strat = _NoopStrategy(broker=backtesting_broker)
    return StrategyExecutor(strategy=strat)


def test_us_futures_treated_as_non_continuous(strategy_executor):
    """us_futures closes over the weekend; it must not be flagged as continuous."""
    assert strategy_executor._is_continuous_market("us_futures") is False


def test_true_continuous_markets_remain_continuous(strategy_executor):
    """24/7 markets should still be recognised as continuous."""
    assert strategy_executor._is_continuous_market("24/7") is True


def test_ensure_progress_inside_open_session(strategy_executor, mocker):
    """When time_to_close stalls during open market, executor should advance clock."""
    broker = strategy_executor.broker
    mocker.patch.object(broker, "is_market_open", return_value=True)
    update_spy = mocker.patch.object(broker, "_update_datetime")
    mocker.patch.object(broker, "get_time_to_close", return_value=15)

    result = strategy_executor._ensure_progress_inside_open_session(0)

    update_spy.assert_called_once_with(1)
    assert result == 15


def test_ensure_progress_noop_when_market_closed(strategy_executor, mocker):
    broker = strategy_executor.broker
    mocker.patch.object(broker, "is_market_open", return_value=False)
    update_spy = mocker.patch.object(broker, "_update_datetime")

    result = strategy_executor._ensure_progress_inside_open_session(0)

    update_spy.assert_not_called()
    assert result == 0


def test_initialize_seeds_day_cadence_for_daily_backtests():
    data_source = PandasDataBacktesting(
        datetime_start=datetime(2025, 10, 28),
        datetime_end=datetime(2025, 11, 6),
    )
    backtesting_broker = BacktestingBroker(data_source=data_source)
    strat = _DailyNoopStrategy(broker=backtesting_broker)
    executor = StrategyExecutor(strategy=strat)

    assert data_source._timestep == "minute"
    executor._initialize()
    assert data_source._timestep == "day"


def test_initialize_keeps_minute_cadence_for_intraday_backtests():
    data_source = PandasDataBacktesting(
        datetime_start=datetime(2025, 10, 28),
        datetime_end=datetime(2025, 11, 6),
    )
    backtesting_broker = BacktestingBroker(data_source=data_source)
    strat = _MinuteNoopStrategy(broker=backtesting_broker)
    executor = StrategyExecutor(strategy=strat)

    assert data_source._timestep == "minute"
    executor._initialize()
    assert data_source._timestep == "minute"
