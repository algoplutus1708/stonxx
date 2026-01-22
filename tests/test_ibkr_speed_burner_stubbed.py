from __future__ import annotations

from datetime import date
from decimal import Decimal
from time import perf_counter

import pandas as pd
import pytest

from lumibot.backtesting import BacktestingBroker
from lumibot.backtesting.interactive_brokers_rest_backtesting import InteractiveBrokersRESTBacktesting
from lumibot.entities import Asset
from lumibot.entities.order import Order
from lumibot.strategies.strategy import Strategy


class _SpeedBurnerBase(Strategy):
    def initialize(self, parameters=None):
        # Minute-cadence backtest loop.
        self.sleeptime = "1M"
        self._i = 0
        self.include_cash_positions = True

    def _burn_one_asset(self, asset: Asset):
        # Hot path: these are the calls that dominate runtime in real strategies.
        _ = self.get_last_price(asset)
        _ = self.get_historical_prices(asset, length=100, timestep="minute").df
        _ = self.get_historical_prices(asset, length=20, timestep="day").df


class _FuturesSpeedBurnerStrategy(_SpeedBurnerBase):
    def initialize(self, parameters=None):
        super().initialize(parameters=parameters)
        self.futs = parameters["futs"]

    def on_trading_iteration(self):
        for fut in self.futs:
            self._burn_one_asset(fut)

        side = Order.OrderSide.BUY if (self._i % 2 == 0) else Order.OrderSide.SELL
        for fut in self.futs:
            order = self.create_order(fut, Decimal("1"), side, order_type=Order.OrderType.MARKET)
            self.submit_order(order)
        self._i += 1


class _CryptoSpeedBurnerStrategy(_SpeedBurnerBase):
    def initialize(self, parameters=None):
        super().initialize(parameters=parameters)
        self.coins = parameters["coins"]

    def on_trading_iteration(self):
        for coin in self.coins:
            self._burn_one_asset(coin)

        side = Order.OrderSide.BUY if (self._i % 2 == 0) else Order.OrderSide.SELL
        for coin in self.coins:
            order = self.create_order(coin, Decimal("0.01"), side, order_type=Order.OrderType.MARKET)
            self.submit_order(order)
        self._i += 1


def _minute_df(index: pd.DatetimeIndex, start_price: float) -> pd.DataFrame:
    prices = start_price + (pd.Series(range(len(index))) * 0.01).to_numpy()
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices + 0.01,
            "low": prices - 0.01,
            "close": prices,
            "volume": 1000,
        },
        index=index,
    )


def _day_df(index: pd.DatetimeIndex, start_price: float) -> pd.DataFrame:
    prices = start_price + (pd.Series(range(len(index))) * 1.0).to_numpy()
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices + 1.0,
            "low": prices - 1.0,
            "close": prices,
            "volume": 1_000_000,
        },
        index=index,
    )


def test_ibkr_speed_burner_prefetches_once_and_slices_forever(monkeypatch):
    import lumibot.tools.ibkr_helper as ibkr_helper

    # 2–3 symbols each (user requirement); keep the dataset small enough for unit tests but
    # large enough to catch per-iteration refetching.
    tz = "America/New_York"
    minute_index = pd.date_range("2025-12-08 09:30", periods=600, freq="1min", tz=tz)  # 10 hours
    day_index = pd.date_range("2025-12-01 00:00", periods=40, freq="1D", tz=tz)

    fut_mes = Asset("MES", asset_type=Asset.AssetType.FUTURE, expiration=date(2025, 12, 19), multiplier=5)
    fut_mnq = Asset("MNQ", asset_type=Asset.AssetType.FUTURE, expiration=date(2025, 12, 19), multiplier=2)

    btc = Asset("BTC", asset_type=Asset.AssetType.CRYPTO)
    eth = Asset("ETH", asset_type=Asset.AssetType.CRYPTO)
    sol = Asset("SOL", asset_type=Asset.AssetType.CRYPTO)

    datasets: dict[tuple[str, str], pd.DataFrame] = {
        ("MES", "minute"): _minute_df(minute_index, 6400.0),
        ("MES", "day"): _day_df(day_index, 6300.0),
        ("MNQ", "minute"): _minute_df(minute_index, 17000.0),
        ("MNQ", "day"): _day_df(day_index, 16500.0),
        ("BTC", "minute"): _minute_df(minute_index, 40000.0),
        ("BTC", "day"): _day_df(day_index, 39000.0),
        ("ETH", "minute"): _minute_df(minute_index, 2000.0),
        ("ETH", "day"): _day_df(day_index, 1900.0),
        ("SOL", "minute"): _minute_df(minute_index, 100.0),
        ("SOL", "day"): _day_df(day_index, 95.0),
    }

    calls: dict[tuple[str, str], int] = {}

    def fake_get_price_data(*, asset, quote, timestep, start_dt, end_dt, exchange=None, include_after_hours=True, source=None):
        sym = getattr(asset, "symbol", "")
        key = (sym, str(timestep))
        calls[key] = calls.get(key, 0) + 1
        df = datasets.get(key)
        if df is None:
            raise AssertionError(f"Missing stub dataset for {key}")
        return df

    monkeypatch.setattr(ibkr_helper, "get_price_data", fake_get_price_data)

    data_source = InteractiveBrokersRESTBacktesting(
        datetime_start=minute_index[0].to_pydatetime(),
        datetime_end=minute_index[-1].to_pydatetime(),
        market="24/7",
        show_progress_bar=False,
        log_backtest_progress_to_file=False,
    )
    data_source.load_data()

    broker = BacktestingBroker(data_source=data_source)
    broker.initialize_market_calendars(data_source.get_trading_days_pandas())
    broker._first_iteration = False
    # Start after enough history exists for the lookbacks (minute=100, day=20).
    broker._update_datetime(minute_index[200].to_pydatetime())

    futures = _FuturesSpeedBurnerStrategy(
        broker=broker,
        budget=100_000.0,
        analyze_backtest=False,
        parameters={"futs": [fut_mes, fut_mnq]},
    )
    futures._first_iteration = False
    # Unit tests call `on_trading_iteration()` directly; ensure `initialize()` has run.
    futures.initialize(parameters={"futs": [fut_mes, fut_mnq]})

    crypto = _CryptoSpeedBurnerStrategy(
        broker=broker,
        budget=100_000.0,
        analyze_backtest=False,
        parameters={"coins": [btc, eth, sol]},
    )
    crypto._first_iteration = False
    crypto.initialize(parameters={"coins": [btc, eth, sol]})

    # Multi-timeframe request should work in backtesting without strategy-layer resampling.
    bars_15m = futures.get_historical_prices(fut_mes, length=10, timestep="15min")
    assert bars_15m is not None
    assert len(bars_15m.df) == 10

    # Run a few hundred iterations of each loop. This is a correctness/speed-structure test:
    # it should not refetch the same series per iteration.
    iterations = 200

    t0 = perf_counter()
    for _ in range(iterations):
        futures.on_trading_iteration()
        broker.process_pending_orders(futures)
        futures._executor.process_queue()
        broker._update_datetime(60)

    for _ in range(iterations):
        crypto.on_trading_iteration()
        broker.process_pending_orders(crypto)
        crypto._executor.process_queue()
        broker._update_datetime(60)
    t1 = perf_counter()

    # Sanity: this is not a strict perf gate (CI machines vary), but it should not be pathological.
    assert (t1 - t0) < 60.0

    # Prefetch once → slice forever: each (symbol, timestep) should be loaded once.
    # If this fails, backtests will be dominated by redundant pandas/disk work.
    for key, count in sorted(calls.items()):
        assert count == 1, f"Expected 1 load for {key}, got {count}"
