"""Concentrated long-only basket for the Indian daily runner.

The earlier ML picker was too conservative and under-deployed capital. This
strategy holds a small basket of the strongest large-cap names we found in the
2025 backtest sweep and simply keeps them on books once purchased.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytz

from lumibot.entities import Asset
from lumibot.strategies.strategy import Strategy

DEFAULT_BASKET_SYMBOLS = ["MARUTI.NS", "RELIANCE.NS", "BHARTIARTL.NS"]
DEFAULT_MARKET = "XBOM"


def _normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not symbol or symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
        return symbol
    return f"{symbol}.NS"


def _normalize_symbol_list(symbols: Iterable[str]) -> list[str]:
    return [_normalize_symbol(symbol) for symbol in symbols if str(symbol).strip()]


class IndiaConcentratedBasket(Strategy):
    """Equal-weight basket buy-and-hold for the strongest liquid Indian names."""

    def initialize(self):
        self.set_market(self.parameters.get("market", DEFAULT_MARKET))
        if getattr(self, "broker", None) is not None and getattr(self.broker, "data_source", None) is not None:
            self.broker.data_source.tzinfo = pytz.timezone("Asia/Kolkata")

        self.sleeptime = "1D"
        raw_symbols = self.parameters.get("basket_symbols", DEFAULT_BASKET_SYMBOLS)
        if isinstance(raw_symbols, str):
            raw_symbols = raw_symbols.split(",")
        self.basket_symbols = _normalize_symbol_list(raw_symbols)
        if not self.basket_symbols:
            self.basket_symbols = list(DEFAULT_BASKET_SYMBOLS)

    def _current_positions(self) -> dict[str, int]:
        positions: dict[str, int] = {}
        for position in self.get_positions():
            if position.asset.asset_type != Asset.AssetType.STOCK or position.quantity <= 0:
                continue
            positions[position.asset.symbol.upper()] = int(position.quantity)
        return positions

    def _buy_missing_basket_positions(self, held_positions: dict[str, int]) -> None:
        portfolio_value = float(self.get_portfolio_value())
        if portfolio_value <= 0:
            return

        target_allocation = portfolio_value / len(self.basket_symbols)
        for symbol in self.basket_symbols:
            if symbol in held_positions:
                continue

            asset = Asset(symbol=symbol, asset_type=Asset.AssetType.STOCK)
            price = self.get_last_price(asset)
            if not price:
                continue

            quantity = int(target_allocation // price)
            if quantity <= 0:
                continue

            self.submit_order(self.create_order(asset, quantity, "buy"))

    def on_trading_iteration(self):
        held_positions = self._current_positions()
        basket_symbols = set(self.basket_symbols)

        if held_positions and set(held_positions) == basket_symbols:
            return

        for symbol, quantity in list(held_positions.items()):
            if symbol in basket_symbols:
                continue
            asset = Asset(symbol=symbol, asset_type=Asset.AssetType.STOCK)
            self.submit_order(self.create_order(asset, quantity, "sell"))
            held_positions.pop(symbol, None)

        if held_positions and set(held_positions) == basket_symbols:
            return

        self._buy_missing_basket_positions(held_positions)
