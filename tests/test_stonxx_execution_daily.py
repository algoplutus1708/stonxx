import os
from datetime import datetime
from types import SimpleNamespace

from lumibot.entities import Asset
from lumibot.example_strategies.india_concentrated_basket import (
    DEFAULT_BASKET_SYMBOLS,
    IndiaConcentratedBasket,
)


def test_initialize_binds_timezone_and_normalizes_symbols(monkeypatch):
    strategy = IndiaConcentratedBasket.__new__(IndiaConcentratedBasket)
    strategy.parameters = {"basket_symbols": ["maruti", "RELIANCE.NS", "bhartiartl"]}
    strategy.broker = SimpleNamespace(data_source=SimpleNamespace(tzinfo=None))
    strategy.log_message = lambda *args, **kwargs: None
    strategy.set_market = lambda market: setattr(strategy, "_market", market)

    strategy.initialize()

    assert strategy._market == "XBOM"
    assert strategy.broker.data_source.tzinfo.zone == "Asia/Kolkata"
    assert strategy.sleeptime == "1D"
    assert strategy.basket_symbols == ["MARUTI.NS", "RELIANCE.NS", "BHARTIARTL.NS"]


def test_run_daily_backtest_forces_yahoo_datasource(monkeypatch, capsys):
    import importlib

    original_data_source = os.environ.get("BACKTESTING_DATA_SOURCE")
    original_data_sources = os.environ.get("BACKTESTING_DATA_SOURCES")

    module = importlib.import_module("run_daily_backtest")
    captured = {}

    monkeypatch.delenv("BASKET_SYMBOLS", raising=False)
    assert module._load_basket_symbols() == list(module.DEFAULT_BASKET_SYMBOLS)

    monkeypatch.setenv("BASKET_SYMBOLS", "MARUTI,RELIANCE,BHARTIARTL")

    def fake_backtest(datasource_class, **kwargs):
        captured["datasource_class"] = datasource_class
        captured["kwargs"] = kwargs
        return {
            "india_concentrated_basket_backtest": {
                "cagr": 0.1234,
                "total_return": 0.4567,
                "max_drawdown": {"drawdown": 0.0789},
                "sharpe": 1.23,
            }
        }

    monkeypatch.setattr(module.IndiaConcentratedBasket, "backtest", fake_backtest)

    results = module.run_backtest()
    output = capsys.readouterr().out

    assert os.environ["BACKTESTING_DATA_SOURCE"] == "yahoo"
    assert captured["datasource_class"] is module.YahooDataBacktesting
    assert captured["kwargs"]["backtesting_start"] == datetime(2010, 12, 31)
    assert captured["kwargs"]["backtesting_end"] == datetime(2025, 12, 31)
    assert captured["kwargs"]["parameters"]["basket_symbols"] == ["MARUTI.NS", "RELIANCE.NS", "BHARTIARTL.NS"]
    assert captured["kwargs"]["benchmark_asset"].symbol == "^NSEI"
    assert captured["kwargs"]["show_tearsheet"] is False
    assert captured["kwargs"]["show_indicators"] is False
    assert "CAGR" in output
    assert "12.34%" in output
    assert "Max Drawdown" in output
    assert results["india_concentrated_basket_backtest"]["cagr"] == 0.1234

    if original_data_source is None:
        monkeypatch.delenv("BACKTESTING_DATA_SOURCE", raising=False)
    else:
        monkeypatch.setenv("BACKTESTING_DATA_SOURCE", original_data_source)

    if original_data_sources is None:
        monkeypatch.delenv("BACKTESTING_DATA_SOURCES", raising=False)
    else:
        monkeypatch.setenv("BACKTESTING_DATA_SOURCES", original_data_sources)


def test_basket_strategy_buys_missing_positions(monkeypatch):
    strategy = IndiaConcentratedBasket.__new__(IndiaConcentratedBasket)
    strategy.parameters = {"basket_symbols": ["MARUTI.NS", "RELIANCE.NS", "BHARTIARTL.NS"]}
    strategy.basket_symbols = ["MARUTI.NS", "RELIANCE.NS", "BHARTIARTL.NS"]
    strategy.get_positions = lambda: []
    strategy.get_portfolio_value = lambda: 9_000_000.0
    strategy.get_last_price = lambda asset: {"MARUTI.NS": 16000.0, "RELIANCE.NS": 1550.0, "BHARTIARTL.NS": 2150.0}[
        asset.symbol
    ]

    submitted_orders = []
    strategy.submit_order = lambda order: submitted_orders.append(order)
    strategy.create_order = lambda asset, quantity, side: {"symbol": asset.symbol, "quantity": quantity, "side": side}

    strategy.on_trading_iteration()

    assert [order["symbol"] for order in submitted_orders] == ["MARUTI.NS", "RELIANCE.NS", "BHARTIARTL.NS"]
    assert all(order["side"] == "buy" for order in submitted_orders)


def test_basket_strategy_holds_existing_basket(monkeypatch):
    strategy = IndiaConcentratedBasket.__new__(IndiaConcentratedBasket)
    strategy.parameters = {"basket_symbols": list(DEFAULT_BASKET_SYMBOLS)}
    strategy.basket_symbols = list(DEFAULT_BASKET_SYMBOLS)

    positions = []
    for symbol in DEFAULT_BASKET_SYMBOLS:
        positions.append(
            SimpleNamespace(
                asset=SimpleNamespace(symbol=symbol, asset_type=Asset.AssetType.STOCK),
                quantity=100,
            )
        )
    strategy.get_positions = lambda: positions
    strategy.get_portfolio_value = lambda: 10_000_000.0
    strategy.get_last_price = lambda asset: 1.0
    strategy.submit_order = lambda order: (_ for _ in ()).throw(AssertionError("strategy should not rebalance"))
    strategy.create_order = lambda asset, quantity, side: {"symbol": asset.symbol, "quantity": quantity, "side": side}

    strategy.on_trading_iteration()
