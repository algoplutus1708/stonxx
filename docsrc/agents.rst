AI Trading Agents and Agentic Backtesting
==========================================

LumiBot is the only production framework that lets an AI agent reason, call external tools, and execute trades **on every bar during a backtest** -- then run the exact same strategy code live. The agent loop uses the `Model Context Protocol (MCP) <https://modelcontextprotocol.io/>`_ so your strategy can call any of 20,000+ external MCP servers for news, macro data, filings, or custom analytics. A built-in replay cache makes warm reruns deterministic and fast. Whether you want to backtest an AI trading agent, build an agentic backtesting framework, or connect LLM-driven trading bots to live brokers, LumiBot handles it in one unified codebase.

.. toctree::
   :maxdepth: 1

   agents_quickstart
   agents_canonical_demos
   agents_observability

Why This Is Different
---------------------

Most tools that combine LLMs and trading fall into one of three categories:

1. **LLM outside the loop.** Platforms like QuantConnect let you call an LLM externally, but the model is not part of the backtest simulation. It cannot reason over point-in-time data on each bar.
2. **Agent frameworks with no backtesting.** CrewAI, AutoGen, and LangGraph build multi-agent workflows, but none of them can simulate a trading backtest where the agent makes decisions bar by bar against historical data.
3. **Hobby scripts with no infrastructure.** Open-source experiments wire GPT to a broker, but they lack MCP support, replay caching, DuckDB time-series queries, and the observability needed for production.

LumiBot is different because it combines all of these in one framework:

- **LLM in the loop on every bar.** The AI agent runs inside ``on_trading_iteration()``, receives point-in-time market state, calls tools, reasons, and submits orders -- all within the backtest simulation.
- **20,000+ external MCP servers.** Connect to any MCP-compatible server with a URL. No local installs, no npm, no custom adapters.
- **Replay caching for deterministic backtests.** Identical prompt + context + tools + timestamp = cached result. Warm reruns complete in seconds with zero model calls.
- **Any LLM provider.** Use OpenAI, Anthropic, Google Gemini, or any provider supported by the underlying model router.
- **Same code for backtest and live.** No separate "backtest mode" strategy. Write once, backtest it, deploy it.

Quick Start
-----------

Here is a complete AI trading agent strategy that uses an external MCP server to search for news and make trading decisions:

.. code-block:: python

    import os
    from lumibot.components.agents import MCPServer
    from lumibot.strategies import Strategy

    class NewsSentimentStrategy(Strategy):
        def initialize(self):
            self.sleeptime = "1D"
            self.agents.create(
                name="research",
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
            result = self.agents["research"].run()
            self.log_message(f"[research] {result.summary}", color="yellow")

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

That is the entire strategy file. No local MCP server scripts, no npm installs, no explicit built-in tool lists. LumiBot includes all built-in tools by default and connects to the Alpha Vantage MCP server over HTTP using just a URL.

External MCP Servers
--------------------

An external MCP server is just a URL. Any server that speaks the Model Context Protocol over HTTP or Streamable HTTP works with LumiBot. There are over 20,000 MCP servers available today covering news, economic data, filings, social sentiment, and more.

**Example 1: Alpha Vantage (news, fundamentals, 130+ tools)**

.. code-block:: python

    MCPServer(
        name="alpha-vantage",
        url=f"https://mcp.alphavantage.co/mcp?apikey={os.environ['ALPHAVANTAGE_API_KEY']}",
        exposed_tools=["NEWS_SENTIMENT"],
    )

The API key is embedded in the URL. No headers needed.

**Example 2: Smithery-hosted FRED (800,000+ economic series)**

.. code-block:: python

    MCPServer(
        name="fred-macro",
        url="https://server.smithery.ai/@kablewy/fred-mcp-server/mcp",
        headers={"Authorization": f"Bearer {os.environ['SMITHERY_API_KEY']}"},
        exposed_tools=["search_series", "get_series_observations"],
    )

This server requires a Bearer token passed via the ``headers`` parameter. Smithery hosts thousands of MCP servers -- any of them work with this same pattern.

**Any MCP server works.** If it has a URL and speaks MCP over HTTP, you can connect it to a LumiBot strategy. The ``exposed_tools`` list tells LumiBot which tools to make available to the agent.

Built-in Tools
--------------

LumiBot includes a full set of built-in trading tools that are available to every agent **by default**. You do not need to list them explicitly.

The built-in tools cover everything a trading agent needs:

- **Account:** ``account.positions``, ``account.portfolio`` -- current holdings and portfolio state
- **Market data:** ``market.last_price``, ``market.load_history_table`` -- real-time quotes and historical bars
- **DuckDB:** ``duckdb.query`` -- SQL queries over time-series data loaded into DuckDB tables
- **Orders:** ``orders.submit``, ``orders.cancel``, ``orders.modify``, ``orders.open_orders`` -- full order management
- **Documentation:** ``docs.search`` -- search LumiBot's own API docs for guidance

These tools give the agent access to positions, prices, history, and order execution without any setup. If you want to add external data on top of these, add MCP servers.

System Prompts
--------------

LumiBot handles all the common instructions internally through its base prompt. The base prompt tells the agent:

- Whether the run is a backtest or live trading
- The current datetime and timezone
- Current positions, cash, and portfolio values
- Rules about look-ahead bias and backtesting safety
- Default investor policy (conviction over activity, no overtrading)
- Position sizing, order execution, and limit order preferences
- DuckDB conventions and tool usage guidance

**Your system prompt should be 2-3 sentences about your strategy.** LumiBot handles the rest.

.. code-block:: python

    system_prompt=(
        "Use economic data to decide whether capital should be in TQQQ "
        "or a defensive asset like SHV. Check interest rates, inflation, "
        "and growth conditions. This is a binary allocator."
    )

Do not repeat instructions about position sizing, time safety, or tool usage. LumiBot already covers those in the base prompt.

DuckDB and Time-Series Data
----------------------------

When the agent needs to analyze historical price data, LumiBot loads it into DuckDB tables automatically. The agent can then query these tables with SQL instead of reading raw bar data in the prompt.

This is handled by the base prompt and the built-in ``market.load_history_table`` and ``duckdb.query`` tools. The agent loads a price history table by symbol and timeframe, then queries it with standard SQL for moving averages, volatility, or any other analysis. You do not need to configure DuckDB -- it is part of the default agent runtime.

Replay Cache
------------

In backtesting mode, LumiBot caches every agent run. When a subsequent backtest hits the same combination of prompt, context, model, tools, and simulated timestamp, the cached result is returned instantly without calling the LLM or any MCP server.

This means:

- **Deterministic backtests.** The same inputs always produce the same outputs.
- **Fast warm reruns.** A cached backtest that took 30 minutes on the first run can complete in seconds.
- **Cost control.** No duplicate LLM API calls or external MCP calls on repeated runs.

The replay cache is automatic. No configuration needed.

Observability
-------------

Every agent run produces a structured trace that records:

- The full prompt surface (base prompt + system prompt + context)
- Every tool call and tool result
- Any observability warnings (e.g., future-dated data in a backtest)
- The agent's summary and reasoning
- Cache hit/miss status
- DuckDB query metrics

A compact summary log line is emitted for every run. For deeper debugging, inspect the full JSON trace file. See :doc:`agents_observability` for the complete debugging workflow.

Acceptance Tests
----------------

LumiBot ships three canonical demo strategies that serve as end-to-end acceptance tests for the AI agent runtime:

1. **News Sentiment Strategy** -- Uses Alpha Vantage MCP to discover and trade on US stock news catalysts.
2. **Macro Risk Strategy** -- Uses Smithery-hosted FRED MCP to allocate between TQQQ and SHV based on macro conditions.
3. **M2 Liquidity Strategy** -- Uses Smithery-hosted FRED MCP to allocate based on money supply and liquidity trends.

Each demo validates external MCP tool usage, replay caching, trace quality, and benchmarked tearsheet output. See :doc:`agents_canonical_demos` for details on each strategy.
