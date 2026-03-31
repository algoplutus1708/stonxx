AI Agents Quick Start
=====================

This page shows the core patterns for creating and running AI trading agents inside a LumiBot strategy. Whether you want to backtest an AI trading agent with external MCP tools or build an agentic backtesting workflow, these examples get you started in minutes. For background on why LumiBot is the only framework that puts the LLM inside the backtest loop, see :doc:`agents`.

The pattern is simple:

- Create the agent once in ``initialize()``
- Run the agent from lifecycle methods like ``on_trading_iteration()``
- The agent reasons, calls tools, and executes trades on each bar
- The same code works in backtests and live trading

Imports
-------

.. code-block:: python

    from lumibot.components.agents import MCPServer, agent_tool
    from lumibot.strategies import Strategy

Built-in tools are included by default -- no import needed for those.

Minimal Example (Built-in Tools Only)
--------------------------------------

This strategy creates an agent that uses only the default built-in tools. No external MCP servers, no explicit tool list.

.. code-block:: python

    from lumibot.strategies import Strategy


    class SimpleAgentStrategy(Strategy):
        parameters = {"symbol": "SPY"}

        def initialize(self):
            self.sleeptime = "1D"
            self.agents.create(
                name="research",
                default_model="gpt-4.1-mini",
                system_prompt=(
                    "Analyze the current portfolio and market conditions. "
                    "Trade conservatively. If the evidence is weak, do nothing."
                ),
            )

        def on_trading_iteration(self):
            result = self.agents["research"].run(
                context={"symbol": self.parameters["symbol"]}
            )
            self.log_message(f"[research] {result.summary}", color="yellow")

The agent has access to all built-in tools (positions, portfolio, prices, history, DuckDB, orders, docs) without listing them.

External MCP Server Example
----------------------------

Add an external MCP server by passing a URL. This example connects to Alpha Vantage for news data:

.. code-block:: python

    import os
    from lumibot.components.agents import MCPServer
    from lumibot.strategies import Strategy


    class NewsSentimentStrategy(Strategy):
        def initialize(self):
            self.sleeptime = "1D"
            self.agents.create(
                name="news_research",
                default_model="gpt-4.1-mini",
                system_prompt=(
                    "Search for recent US stock news. Find stocks with strong "
                    "catalysts and buy the best opportunities. Hold up to 4 "
                    "equity positions. Park idle capital in SHV when nothing qualifies."
                ),
                mcp_servers=[
                    MCPServer(
                        name="alpha-vantage",
                        url=f"https://mcp.alphavantage.co/mcp?apikey={os.environ['ALPHAVANTAGE_API_KEY']}",
                        exposed_tools=["NEWS_SENTIMENT"],
                    ),
                ],
            )

        def on_trading_iteration(self):
            result = self.agents["news_research"].run()
            self.log_message(f"[news_research] {result.summary}", color="yellow")

MCP Server with Auth Headers
-----------------------------

Some MCP servers require authentication via HTTP headers. This example uses a Smithery-hosted FRED server with a Bearer token:

.. code-block:: python

    import os
    from lumibot.components.agents import MCPServer
    from lumibot.strategies import Strategy


    class MacroRiskStrategy(Strategy):
        def initialize(self):
            self.sleeptime = "1D"
            self.agents.create(
                name="macro_research",
                default_model="gpt-4.1-mini",
                system_prompt=(
                    "Use economic data to decide whether capital should be in "
                    "TQQQ or a defensive asset like SHV. Check interest rates, "
                    "inflation, and growth conditions. This is a binary allocator."
                ),
                mcp_servers=[
                    MCPServer(
                        name="fred-macro",
                        url="https://server.smithery.ai/@kablewy/fred-mcp-server/mcp",
                        headers={"Authorization": f"Bearer {os.environ['SMITHERY_API_KEY']}"},
                        exposed_tools=["search_series", "get_series_observations"],
                    ),
                ],
            )

        def on_trading_iteration(self):
            result = self.agents["macro_research"].run()
            self.log_message(f"[macro_research] {result.summary}", color="yellow")

Custom Strategy Tools with ``@agent_tool``
-------------------------------------------

If your strategy needs a custom helper that the agent can call, decorate a method with ``@agent_tool``:

.. code-block:: python

    from lumibot.components.agents import agent_tool
    from lumibot.strategies import Strategy


    class CustomToolStrategy(Strategy):

        @agent_tool(
            name="get_watchlist_bias",
            description="Return a structured bias payload for one symbol.",
        )
        def get_watchlist_bias(self, symbol: str) -> dict:
            return {"symbol": symbol, "bias": "neutral"}

        def initialize(self):
            self.sleeptime = "1D"
            self.agents.create(
                name="research",
                default_model="gpt-4.1-mini",
                system_prompt="Analyze watchlist bias before trading.",
                tools=[self.get_watchlist_bias],
            )

        def on_trading_iteration(self):
            result = self.agents["research"].run()
            self.log_message(f"[research] {result.summary}", color="yellow")

When you pass a ``tools=[...]`` list, those tools are added alongside the default built-in tools. You only need to list your custom tools.

Passing Context
---------------

Pass point-in-time context into the agent run. LumiBot automatically injects positions, cash, and datetime, but you can add strategy-specific context:

.. code-block:: python

    result = self.agents["research"].run(
        context={
            "symbol": "SPY",
            "signal_state": self.vars.get("signal_state", "unknown"),
        }
    )

Working with the Result
-----------------------

``run(...)`` returns an ``AgentRunResult`` with these useful fields:

- ``result.summary`` -- the agent's concluding summary
- ``result.text`` -- full text output from the agent
- ``result.cache_hit`` -- whether the result was replayed from cache
- ``result.warning_messages`` -- list of observability warnings
- ``result.tool_calls`` -- list of tool call events
- ``result.tool_results`` -- list of tool result events
- ``(result.payload or {}).get("trace_path")`` -- path to the full JSON trace

.. code-block:: python

    result = self.agents["research"].run()
    self.log_message(f"summary={result.summary}", color="yellow")

    trace_path = (result.payload or {}).get("trace_path")
    if trace_path:
        self.log_message(f"trace={trace_path}", color="blue")

    if result.warning_messages:
        for warning in result.warning_messages:
            self.log_message(f"WARNING: {warning}", color="red")

Running a Backtest
------------------

Use the standard LumiBot backtest pattern. The agent runs on every bar just like it would in live trading:

.. code-block:: python

    if __name__ == "__main__":
        IS_BACKTESTING = True
        if IS_BACKTESTING:
            from datetime import datetime
            NewsSentimentStrategy.backtest(
                datasource_class=None,
                backtesting_start=datetime(2025, 9, 1),
                backtesting_end=datetime(2026, 3, 1),
                benchmark_asset="SPY",
            )

Set ``datasource_class=None`` to use the data source configured in your ``.env`` file via ``BACKTESTING_DATA_SOURCE``.

Best Practices
--------------

- **Create the agent once in ``initialize()``.** Do not recreate it on every iteration.
- **Keep system prompts short.** 2-3 sentences about your strategy intent. LumiBot handles the rest.
- **Do not list built-in tools.** They are included by default.
- **MCP servers are just URLs.** No local scripts, no npm installs.
- **Log the summary.** Always log ``result.summary`` so you can understand agent decisions.
- **Inspect traces when surprised.** The JSON trace is the source of truth for debugging agent behavior.

Where to Go Next
-----------------

- :doc:`agents` -- main guide with competitive positioning and architecture
- :doc:`agents_canonical_demos` -- the three reference demo strategies
- :doc:`agents_observability` -- traces, replay cache, and debugging workflow
