from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lumibot.backtesting import PandasDataBacktesting
from lumibot.components.agents import AgentRunResult, AgentTraceEvent, BuiltinTools
from lumibot.entities import Asset, Data
from lumibot.strategies import Strategy


def _utc_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _event(kind: str, *, text: str | None = None, tool_name: str | None = None, payload: dict | None = None):
    return AgentTraceEvent(
        kind=kind,
        text=text,
        tool_name=tool_name,
        payload=payload,
        timestamp=_utc_iso_timestamp(),
    )


def _invoke_tool(request, events, tool_name: str, **kwargs):
    tool_map = {tool.name: tool.function for tool in request.bound_tools}
    events.append(_event("tool_call", tool_name=tool_name, payload=kwargs))
    result = tool_map[tool_name](**kwargs)
    payload = result if isinstance(result, dict) else {"value": result}
    events.append(_event("tool_result", tool_name=tool_name, payload=payload))
    return result


class MinuteDuckDBStressRuntime:
    def run(self, request):
        events = [_event("thinking", text="Stress-testing minute-level DuckDB history refresh.")]
        positions = _invoke_tool(request, events, "account_positions")
        table = _invoke_tool(
            request,
            events,
            "market_load_history_table",
            symbol=request.context["symbol"],
            length=request.context["length"],
            timestep=request.context["timestep"],
            asset_type="stock",
            table_name="minute_window",
        )
        _invoke_tool(
            request,
            events,
            "duckdb_query",
            sql=f"SELECT COUNT(*) AS rows_seen, AVG(close) AS avg_close, MAX(close) AS max_close FROM {table['table_name']}",
        )

        has_position = any(
            pos.get("asset", {}).get("symbol") == request.context["symbol"] and float(pos.get("quantity") or 0) > 0
            for pos in positions["positions"]
            if isinstance(pos, dict) and isinstance(pos.get("asset"), dict)
        )
        if not has_position:
            _invoke_tool(
                request,
                events,
                "orders_submit_order",
                symbol=request.context["symbol"],
                quantity=1,
                side="buy",
                asset_type="stock",
                order_type="market",
            )
            summary = "Minute stress run bought once."
        else:
            summary = "Minute stress run held."

        events.append(_event("text", text=summary))
        return AgentRunResult(summary=summary, model=request.model, events=events)


class AgentMinuteDuckDBStressBacktest(Strategy):
    parameters = {
        "symbol": "AGMS",
        "length": 120,
        "timestep": "minute",
    }

    def initialize(self):
        self.set_market("NYSE")
        self.sleeptime = "1M"
        self.asset = Asset(self.parameters["symbol"], Asset.AssetType.STOCK)
        self.agents.create(
            name="research",
            default_model="stub-minute-stress",
            system_prompt=(
                "You are a LumiBot validation agent. "
                "Use DuckDB for minute-level time-series analysis and only buy once."
            ),
            tools=[
                BuiltinTools.account.positions(),
                BuiltinTools.market.load_history_table(),
                BuiltinTools.duckdb.query(),
                BuiltinTools.orders.submit(),
            ],
            _runtime=MinuteDuckDBStressRuntime(),
        )

    def on_trading_iteration(self):
        self.agents["research"].run(
            context={
                "symbol": self.asset.symbol,
                "length": self.parameters["length"],
                "timestep": self.parameters["timestep"],
            }
        )


def _minute_stress_data():
    day_one = pd.date_range("2025-01-06 09:30", periods=390, freq="min", tz="America/New_York")
    day_two = pd.date_range("2025-01-07 09:30", periods=390, freq="min", tz="America/New_York")
    index = day_one.append(day_two)
    base = [100.0 + i * 0.02 for i in range(len(index))]
    df = pd.DataFrame(
        {
            "open": base,
            "high": [value + 0.15 for value in base],
            "low": [value - 0.15 for value in base],
            "close": [value + 0.05 for value in base],
            "volume": [1000 + (i % 100) for i in range(len(index))],
        },
        index=index,
    )
    asset = Asset("AGMS", Asset.AssetType.STOCK)
    return {asset: Data(asset, df, timestep="minute")}


if __name__ == "__main__":
    AgentMinuteDuckDBStressBacktest.run_backtest(
        datasource_class=PandasDataBacktesting,
        backtesting_start=datetime(2025, 1, 6, 9, 30),
        backtesting_end=datetime(2025, 1, 7, 15, 59),
        pandas_data=_minute_stress_data(),
        benchmark_asset=None,
        show_plot=False,
        show_tearsheet=False,
        show_indicators=False,
        quiet_logs=False,
    )
