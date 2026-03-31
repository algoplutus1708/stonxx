from datetime import date, datetime

import pandas as pd

from lumibot.backtesting import PandasDataBacktesting
from lumibot.components.agents import BuiltinTools
from lumibot.entities import Asset, Data
from lumibot.strategies import Strategy


class AgentOptionBacktest(Strategy):
    parameters = {
        "symbol": "SPY",
        "expiration": "2024-06-21",
        "strike": 500.0,
        "right": "CALL",
    }

    def initialize(self):
        self.set_market("NYSE")
        self.sleeptime = "1D"
        self.option_asset = Asset(
            self.parameters["symbol"],
            asset_type=Asset.AssetType.OPTION,
            expiration=date.fromisoformat(self.parameters["expiration"]),
            strike=self.parameters["strike"],
            right=self.parameters["right"],
        )

        self.agents.create(
            name="option_research",
            default_model="gemini-2.5-flash",
            system_prompt=(
                "You are a conservative options trading agent. "
                "Always inspect history with DuckDB before suggesting a trade."
            ),
            tools=[
                BuiltinTools.account.positions(),
                BuiltinTools.market.load_history_table(),
                BuiltinTools.duckdb.query(),
                BuiltinTools.orders.submit(),
                BuiltinTools.orders.open_orders(),
            ],
        )

    def on_trading_iteration(self):
        self.agents["option_research"].run(
            task_prompt="Review the configured option contract and decide whether a trade is justified.",
            context={
                "symbol": self.option_asset.symbol,
                "asset_type": "option",
                "expiration": self.parameters["expiration"],
                "strike": self.parameters["strike"],
                "right": self.parameters["right"],
                "length": 20,
                "timestep": "day",
                "table_name": "option_window",
                "sql": "SELECT COUNT(*) AS rows_seen, AVG(close) AS avg_close FROM option_window",
            },
        )


if __name__ == "__main__":
    index = pd.date_range("2024-05-01", periods=10, freq="B", tz="America/New_York")
    quote = Asset("USD", Asset.AssetType.FOREX)
    underlying = Asset("SPY", Asset.AssetType.STOCK)
    option = Asset(
        "SPY",
        asset_type=Asset.AssetType.OPTION,
        expiration=date.fromisoformat("2024-06-21"),
        strike=500.0,
        right="CALL",
    )
    underlying_df = pd.DataFrame(
        {
            "open": [500 + i for i in range(len(index))],
            "high": [501 + i for i in range(len(index))],
            "low": [499 + i for i in range(len(index))],
            "close": [500.5 + i for i in range(len(index))],
            "volume": [1000] * len(index),
        },
        index=index,
    )
    option_df = pd.DataFrame(
        {
            "open": [10.0 + i * 0.2 for i in range(len(index))],
            "high": [10.2 + i * 0.2 for i in range(len(index))],
            "low": [9.8 + i * 0.2 for i in range(len(index))],
            "close": [10.1 + i * 0.2 for i in range(len(index))],
            "volume": [100] * len(index),
        },
        index=index,
    )
    AgentOptionBacktest.run_backtest(
        datasource_class=PandasDataBacktesting,
        backtesting_start=datetime(2024, 5, 1),
        backtesting_end=datetime(2024, 5, 14),
        pandas_data={
            underlying: Data(underlying, underlying_df, timestep="day"),
            option: Data(option, option_df, quote=quote, timestep="day"),
        },
        benchmark_asset="SPY",
    )
