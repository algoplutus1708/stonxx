"""Backtest runner for the concentrated Indian basket strategy on Yahoo Finance.

This runner forces Yahoo Finance backtesting regardless of any ThetaData routing
configured in local environment files or the shell environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime

os.environ["BACKTESTING_DATA_SOURCE"] = "yahoo"
os.environ.pop("BACKTESTING_DATA_SOURCES", None)

from dotenv import load_dotenv

load_dotenv(".env.india")

# Reassert after loading env files so local settings cannot reintroduce Theta routing.
os.environ["BACKTESTING_DATA_SOURCE"] = "yahoo"
os.environ.pop("BACKTESTING_DATA_SOURCES", None)

from lumibot.backtesting import YahooDataBacktesting
from lumibot.entities import Asset
from lumibot.entities.india_trading_fees import make_india_equity_fees
from lumibot.example_strategies.india_concentrated_basket import DEFAULT_BASKET_SYMBOLS, IndiaConcentratedBasket

BACKTEST_START = datetime(2024, 12, 20)
BACKTEST_END = datetime(2025, 12, 31)
DEFAULT_BENCHMARK = "^NSEI"


def _to_yahoo_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not symbol or symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
        return symbol
    return f"{symbol}.NS"


def _load_basket_symbols() -> list[str]:
    raw_symbols = os.getenv("BASKET_SYMBOLS", "")
    symbols = [_to_yahoo_symbol(symbol) for symbol in raw_symbols.split(",") if symbol.strip()]
    if not symbols:
        symbols = list(DEFAULT_BASKET_SYMBOLS)
    return symbols


def _extract_primary_metrics(results: object) -> Mapping[str, object] | None:
    if isinstance(results, tuple) and results:
        return _extract_primary_metrics(results[0])

    if isinstance(results, list):
        for item in results:
            metrics = _extract_primary_metrics(item)
            if metrics is not None:
                return metrics
        return None

    if isinstance(results, Mapping):
        if "cagr" in results:
            return results

        for value in results.values():
            if isinstance(value, Mapping) and "cagr" in value:
                return value

    return None


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_max_drawdown(metrics: Mapping[str, object]) -> float:
    max_drawdown = metrics.get("max_drawdown", 0.0)
    if isinstance(max_drawdown, Mapping):
        max_drawdown = max_drawdown.get("drawdown", 0.0)
    return _coerce_float(max_drawdown)


def _print_backtest_summary(results: object) -> None:
    metrics = _extract_primary_metrics(results)
    if metrics is None:
        print("\n[summary] Backtest returned no metrics; CAGR unavailable.\n")
        return

    total_return = _coerce_float(metrics.get("total_return", 0.0))
    cagr = _coerce_float(metrics.get("cagr", 0.0))
    max_drawdown = _extract_max_drawdown(metrics)
    sharpe = metrics.get("sharpe")

    print("\n" + "=" * 50)
    print("FINAL RESULTS")
    print("=" * 50)
    print(f"Total Return : {total_return * 100:.2f}%")
    print(f"CAGR         : {cagr * 100:.2f}%")
    print(f"Max Drawdown : {max_drawdown * 100:.2f}%")
    if sharpe is not None:
        print(f"Sharpe       : {_coerce_float(sharpe):.2f}")
    print("=" * 50 + "\n")


def run_backtest():
    os.environ["BACKTESTING_DATA_SOURCE"] = "yahoo"
    os.environ.pop("BACKTESTING_DATA_SOURCES", None)

    product_type = os.getenv("PRODUCT_TYPE", "CNC").upper()
    exchange = os.getenv("EXCHANGE", "NSE").upper()
    basket_symbols = _load_basket_symbols()

    buy_fees, sell_fees = make_india_equity_fees(
        product_type=product_type,
        exchange=exchange,
        include_slippage=True,
    )

    results = IndiaConcentratedBasket.backtest(
        YahooDataBacktesting,
        backtesting_start=BACKTEST_START,
        backtesting_end=BACKTEST_END,
        benchmark_asset=Asset(DEFAULT_BENCHMARK, Asset.AssetType.INDEX),
        buy_trading_fees=buy_fees,
        sell_trading_fees=sell_fees,
        budget=10_000_000,
        parameters={"basket_symbols": basket_symbols},
        name="india_concentrated_basket_backtest",
        quiet_logs=False,
        show_plot=False,
        show_indicators=False,
        show_tearsheet=False,
        save_logfile=True,
    )

    _print_backtest_summary(results)
    return results


if __name__ == "__main__":
    run_backtest()
