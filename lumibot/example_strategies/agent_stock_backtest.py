from datetime import datetime

from lumibot.backtesting import YahooDataBacktesting
from lumibot.components.agents import BuiltinTools, agent_tool
from lumibot.strategies import Strategy


class AgentStockBacktest(Strategy):
    parameters = {
        "symbol": "SPY",
        "run_every_n_iterations": 5,
    }

    @agent_tool(
        name="get_watchlist_bias",
        description="Return a small structured discretionary bias payload for one symbol.",
    )
    def get_watchlist_bias(self, symbol: str) -> dict:
        return {"symbol": symbol, "bias": "neutral"}

    def initialize(self):
        self.set_market("NYSE")
        self.sleeptime = "1D"
        self.vars.iteration_count = 0

        self.agents.create(
            name="research",
            default_model="gemini-2.5-flash",
            system_prompt=(
                "You are a conservative stock trading agent. "
                "Use DuckDB for time-series analysis. "
                "Do not overtrade. If uncertain, do nothing."
            ),
            tools=[
                BuiltinTools.account.positions(),
                BuiltinTools.account.portfolio(),
                BuiltinTools.market.last_price(),
                BuiltinTools.market.load_history_table(),
                BuiltinTools.duckdb.query(),
                BuiltinTools.orders.submit(),
                BuiltinTools.orders.cancel(),
                self.get_watchlist_bias,
            ],
        )

    def on_trading_iteration(self):
        self.vars.iteration_count += 1
        if self.vars.iteration_count % self.parameters["run_every_n_iterations"] != 0:
            return

        self.agents["research"].run(
            context={
                "symbol": self.parameters["symbol"],
                "asset_type": "stock",
                "max_risk_pct": 0.01,
                "length": 30,
                "timestep": "day",
                "table_name": "recent_prices",
                "sql": "SELECT AVG(close) AS avg_close, MAX(close) AS max_close FROM recent_prices",
            }
        )

    def on_filled_order(self, position, order, price, quantity, multiplier):
        self.agents["research"].run(
            task_prompt="A fill occurred. Re-evaluate risk and any follow-up action.",
            context={
                "symbol": order.asset.symbol,
                "asset_type": "stock",
                "price": price,
                "quantity": quantity,
            },
            model="gemini-2.5-pro",
        )


if __name__ == "__main__":
    AgentStockBacktest.run_backtest(
        datasource_class=YahooDataBacktesting,
        backtesting_start=datetime(2024, 1, 2),
        backtesting_end=datetime(2024, 2, 2),
        benchmark_asset="SPY",
    )
