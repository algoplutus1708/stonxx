from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pandas as pd
import pytest

from lumibot.backtesting import BacktestingBroker
from lumibot.backtesting.interactive_brokers_rest_backtesting import InteractiveBrokersRESTBacktesting
from lumibot.entities import Asset
from lumibot.entities.order import Order
from lumibot.strategies.strategy import Strategy


class _DummyIbkrCryptoStrategy(Strategy):
    def initialize(self, parameters=None):
        self.sleeptime = "1M"
        self.include_cash_positions = True

    def on_trading_iteration(self):
        return


def test_ibkr_rest_backtesting_crypto_market_orders_fill_at_ask_and_bid(monkeypatch):
    import lumibot.tools.ibkr_helper as ibkr_helper

    idx = pd.date_range("2025-01-01 00:00", periods=3, freq="1min", tz="America/New_York")
    spread = 10.0
    df = pd.DataFrame(
        {
            "open": [20_000.0, 20_100.0, 20_200.0],
            "high": [20_050.0, 20_150.0, 20_250.0],
            "low": [19_900.0, 20_000.0, 20_100.0],
            "close": [20_010.0, 20_120.0, 20_230.0],
            "bid": [20_010.0 - spread / 2, 20_120.0 - spread / 2, 20_230.0 - spread / 2],
            "ask": [20_010.0 + spread / 2, 20_120.0 + spread / 2, 20_230.0 + spread / 2],
            "volume": [1_000, 1_000, 1_000],
        },
        index=idx,
    )

    def fake_get_price_data(*, asset, quote, timestep, start_dt, end_dt, exchange=None, include_after_hours=True, source=None):
        return df

    monkeypatch.setattr(ibkr_helper, "get_price_data", fake_get_price_data)

    data_source = InteractiveBrokersRESTBacktesting(
        datetime_start=idx[0].to_pydatetime(),
        datetime_end=(idx[-1] + pd.Timedelta(minutes=1)).to_pydatetime(),
        market="24/7",
        show_progress_bar=False,
        log_backtest_progress_to_file=False,
    )
    data_source.load_data()

    broker = BacktestingBroker(data_source=data_source)
    broker.initialize_market_calendars(data_source.get_trading_days_pandas())
    broker._first_iteration = False
    broker._update_datetime(idx[0].to_pydatetime())

    strategy = _DummyIbkrCryptoStrategy(
        broker=broker,
        budget=100_000.0,
        analyze_backtest=False,
        parameters={},
    )
    strategy._first_iteration = False

    base = Asset("BTC", asset_type=Asset.AssetType.CRYPTO)
    quote = Asset("USD", asset_type=Asset.AssetType.FOREX)

    data_source.get_historical_prices_between_dates(
        (base, quote),
        timestep="minute",
        quote=quote,
        start_date=idx[0].to_pydatetime(),
        end_date=idx[-1].to_pydatetime(),
    )

    q0 = broker.get_quote(base, quote=quote)
    expected_ask_0 = float(getattr(q0, "ask"))
    expected_bid_0 = float(getattr(q0, "bid"))
    assert expected_ask_0 > expected_bid_0

    buy = strategy.create_order(
        base,
        Decimal("0.5"),
        Order.OrderSide.BUY,
        order_type=Order.OrderType.MARKET,
        quote=quote,
    )

    strategy.submit_order(buy)
    broker.process_pending_orders(strategy)
    strategy._executor.process_queue()

    assert buy.is_filled()
    assert buy.get_fill_price() == pytest.approx(expected_ask_0, rel=1e-12)

    expected_cash_after_buy = 100_000.0 - (0.5 * expected_ask_0)
    assert strategy.cash == pytest.approx(expected_cash_after_buy, rel=1e-9)

    broker._update_datetime(idx[1].to_pydatetime())
    q1 = broker.get_quote(base, quote=quote)
    expected_bid_1 = float(getattr(q1, "bid"))
    expected_ask_1 = float(getattr(q1, "ask"))
    assert expected_ask_1 > expected_bid_1

    sell = strategy.create_order(
        base,
        Decimal("0.5"),
        Order.OrderSide.SELL,
        order_type=Order.OrderType.MARKET,
        quote=quote,
    )
    strategy.submit_order(sell)
    broker.process_pending_orders(strategy)
    strategy._executor.process_queue()

    assert sell.is_filled()
    assert sell.get_fill_price() == pytest.approx(expected_bid_1, rel=1e-12)


def test_ibkr_rest_backtesting_crypto_limit_orders_fill_against_quotes(monkeypatch):
    import lumibot.tools.ibkr_helper as ibkr_helper

    idx = pd.date_range("2025-01-01 00:00", periods=3, freq="1min", tz="America/New_York")
    df = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "bid": [100.4, 101.4, 102.4],
            "ask": [100.6, 101.6, 102.6],
            "volume": [1_000, 1_000, 1_000],
        },
        index=idx,
    )

    def fake_get_price_data(*, asset, quote, timestep, start_dt, end_dt, exchange=None, include_after_hours=True, source=None):
        return df

    monkeypatch.setattr(ibkr_helper, "get_price_data", fake_get_price_data)

    data_source = InteractiveBrokersRESTBacktesting(
        datetime_start=idx[0].to_pydatetime(),
        datetime_end=(idx[-1] + pd.Timedelta(minutes=1)).to_pydatetime(),
        market="24/7",
        show_progress_bar=False,
        log_backtest_progress_to_file=False,
    )
    data_source.load_data()

    broker = BacktestingBroker(data_source=data_source)
    broker.initialize_market_calendars(data_source.get_trading_days_pandas())
    broker._first_iteration = False

    strategy = _DummyIbkrCryptoStrategy(
        broker=broker,
        budget=10_000.0,
        analyze_backtest=False,
        parameters={},
    )
    strategy._first_iteration = False

    base = Asset("BTC", asset_type=Asset.AssetType.CRYPTO)
    quote = Asset("USD", asset_type=Asset.AssetType.FOREX)

    data_source.get_historical_prices_between_dates(
        (base, quote),
        timestep="minute",
        quote=quote,
        start_date=idx[0].to_pydatetime(),
        end_date=idx[-1].to_pydatetime(),
    )

    broker._update_datetime(idx[0].to_pydatetime())
    q0 = broker.get_quote(base, quote=quote)
    expected_ask_0 = float(getattr(q0, "ask"))
    expected_bid_0 = float(getattr(q0, "bid"))
    assert expected_ask_0 > expected_bid_0

    buy_marketable = strategy.create_order(
        base,
        Decimal("1"),
        Order.OrderSide.BUY,
        order_type=Order.OrderType.LIMIT,
        limit_price=Decimal("999999"),
        quote=quote,
    )
    strategy.submit_order(buy_marketable)
    broker.process_pending_orders(strategy)
    strategy._executor.process_queue()

    assert buy_marketable.is_filled()
    assert buy_marketable.get_fill_price() == pytest.approx(expected_ask_0, rel=1e-12)

    broker._update_datetime(idx[1].to_pydatetime())
    q1 = broker.get_quote(base, quote=quote)
    expected_bid_1 = float(getattr(q1, "bid"))
    expected_ask_1 = float(getattr(q1, "ask"))
    assert expected_ask_1 > expected_bid_1

    sell_marketable = strategy.create_order(
        base,
        Decimal("1"),
        Order.OrderSide.SELL,
        order_type=Order.OrderType.LIMIT,
        limit_price=Decimal("0"),
        quote=quote,
    )
    strategy.submit_order(sell_marketable)
    broker.process_pending_orders(strategy)
    strategy._executor.process_queue()

    assert sell_marketable.is_filled()
    assert sell_marketable.get_fill_price() == pytest.approx(expected_bid_1, rel=1e-12)
