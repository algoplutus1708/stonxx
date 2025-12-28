import datetime
import math
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from lumibot.backtesting.backtesting_broker import BacktestingBroker
from lumibot.entities import Asset, Order, Quote
from lumibot.tools.lumibot_logger import get_logger


class DummyStrategy:
    def __init__(self, parameters=None):
        self.parameters = parameters or {}
        self.messages = []

    def log_message(self, message, color=None):
        self.messages.append((message, color))


def _build_order(side: Order.OrderSide, limit_price: float) -> Order:
    order = Order(
        strategy="TestStrategy",
        asset=Asset("CVNA", asset_type=Asset.AssetType.OPTION, expiration=None, strike=None, right="CALL"),
        quantity=Decimal("1"),
        side=side,
        order_type=Order.OrderType.LIMIT,
        limit_price=limit_price,
    )
    order.quote = Asset("USD", asset_type=Asset.AssetType.FOREX)
    return order


def _build_broker(quote: Quote) -> BacktestingBroker:
    broker = BacktestingBroker.__new__(BacktestingBroker)
    broker.logger = get_logger("quote_fallback_test")
    broker.data_source = object()
    broker._trade_event_log_df = None  # not used in these unit tests
    broker.get_quote = MagicMock(return_value=quote)
    broker._is_thetadata_source = MagicMock(return_value=True)
    return broker


def test_try_fill_with_quote_returns_ask_for_buy_order():
    quote = Quote(
        asset=Asset("CVNA"),
        bid=44.0,
        ask=45.0,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    broker = _build_broker(quote)
    order = _build_order(Order.OrderSide.BUY, limit_price=60.0)
    strategy = DummyStrategy(parameters={"max_spread_buy_pct": 0.5})

    price = broker._try_fill_with_quote(order, strategy, math.nan, math.nan, math.nan)

    assert price == pytest.approx(45.0)
    assert getattr(order, "_price_source", None) == "quote"
    assert any("ThetaData quote" in msg for msg, _ in strategy.messages)


def test_try_fill_with_quote_respects_limit_price():
    quote = Quote(
        asset=Asset("CVNA"),
        bid=44.0,
        ask=45.0,
    )
    broker = _build_broker(quote)
    order = _build_order(Order.OrderSide.BUY, limit_price=40.0)
    strategy = DummyStrategy()

    price = broker._try_fill_with_quote(order, strategy, math.nan, math.nan, math.nan)

    assert price is None
    assert not hasattr(order, "_price_source")


def test_thetadata_option_market_order_prefers_quote_fill_without_ohlc(monkeypatch):
    """ThetaData option market orders should fill from NBBO without forcing OHLC downloads."""
    quote = Quote(
        asset=Asset("SPXW", asset_type=Asset.AssetType.OPTION, expiration=None, strike=None, right="CALL"),
        bid=10.0,
        ask=11.0,
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )

    broker = BacktestingBroker.__new__(BacktestingBroker)
    broker.logger = get_logger("thetadata_quote_fill_market_test")
    broker.hybrid_prefetcher = None
    broker.prefetcher = None

    class _OrderList:
        def __init__(self, items):
            self._items = list(items)

        def get_list(self):
            return list(self._items)

    class _DummyDataSource:
        SOURCE = "PANDAS"
        _timestep = "minute"

        def get_datetime(self):
            return datetime.datetime(2024, 1, 2, 9, 30, tzinfo=datetime.timezone.utc)

        def get_historical_prices(self, *args, **kwargs):
            raise AssertionError("OHLC should not be fetched when quote fill succeeds")

    broker.data_source = _DummyDataSource()
    broker.get_quote = MagicMock(return_value=quote)
    broker._is_thetadata_source = MagicMock(return_value=True)
    broker._trade_event_log_df = None
    broker.process_expired_option_contracts = MagicMock()

    order = Order(
        strategy="TestStrategy",
        asset=quote.asset,
        quantity=Decimal("1"),
        side=Order.OrderSide.SELL,
        order_type=Order.OrderType.MARKET,
    )
    order.quote = Asset("USD", asset_type=Asset.AssetType.FOREX)

    broker._unprocessed_orders = _OrderList([])
    broker._new_orders = _OrderList([order])
    broker._execute_filled_order = MagicMock()
    broker.cancel_order = MagicMock()

    strategy = DummyStrategy(parameters={"max_spread_pct": 1.0})
    strategy.name = "TestStrategy"

    broker.process_pending_orders(strategy)

    broker._execute_filled_order.assert_called_once()
    fill_kwargs = broker._execute_filled_order.call_args.kwargs
    assert fill_kwargs["price"] == pytest.approx(10.0)
