Canonical AI Agent Demos
========================

LumiBot includes three canonical AI agent demo strategies that serve as both reference implementations and end-to-end acceptance tests for agentic backtesting. Each demo uses a real external MCP server, the full built-in tool set, replay caching, and benchmarked tearsheet output.

These are complete, runnable strategies -- not snippets. They demonstrate how to backtest an AI trading agent with real external data sources, and they validate that LumiBot's AI-driven trading strategy backtest pipeline works end to end.

The Three Demos
---------------

- **News Sentiment Strategy** -- event-driven stock selection using news data
- **Macro Risk Strategy** -- macro regime allocation using economic indicators
- **M2 Liquidity Strategy** -- liquidity-driven allocation using money supply data

News Sentiment Strategy
-----------------------

This strategy uses the Alpha Vantage MCP server to search for recent US stock news and trade on strong catalysts.

**MCP server:** Alpha Vantage (``https://mcp.alphavantage.co/mcp``)

**What it demonstrates:**

- External MCP server connected via a single URL
- Agent-driven stock discovery from news flow
- Portfolio rotation between opportunities and a defensive parking asset (SHV)
- No-trade decisions when conviction is weak
- Replay caching of deterministic backtest runs
- Trace inspection for tool calls, results, and warnings

**What it is useful for:**

- Event-driven AI trading strategies
- Research agents that compare current holdings to new ideas
- Validating that the agent reacts to real point-in-time news, not hallucinated data

Macro Risk Strategy
-------------------

This strategy uses the Smithery-hosted FRED MCP server to read economic data and allocate between TQQQ (risk-on) and SHV (risk-off).

**MCP server:** Smithery FRED (``https://server.smithery.ai/@kablewy/fred-mcp-server/mcp``)

**What it demonstrates:**

- MCP server with Bearer token authentication via headers
- Agent discovery of relevant macro indicators (interest rates, inflation, growth)
- Binary allocation between a leveraged risk asset and a defensive asset
- De-risking during adverse macro regimes (e.g., 2022 inflation/rate hiking)
- Built-in DuckDB time-series analysis alongside external data
- Benchmarked evaluation against SPY

**What it is useful for:**

- Macro regime AI trading strategies
- Concentrated AI strategies where concentration is intentional
- Validating entry and exit behavior across changing economic conditions

M2 Liquidity Strategy
----------------------

This strategy uses the same Smithery-hosted FRED MCP server to read money supply and liquidity data and allocate between TQQQ and SHV.

**MCP server:** Smithery FRED (``https://server.smithery.ai/@kablewy/fred-mcp-server/mcp``)

**What it demonstrates:**

- AI reasoning over macro and liquidity inputs
- Concentration in a single risk asset when the liquidity thesis is strong
- Defensive parking when the agent determines liquidity is contracting
- Long-horizon backtest (2015-2026) with dividend handling
- Benchmarked tearsheets and trade artifacts

**What it is useful for:**

- Long-horizon AI-guided allocation logic
- Validating defensive-asset behavior over multiple market cycles
- Checking cashflow accounting and observability in real artifacts

How to Use These Demos
----------------------

Use the demos for:

- Prompt design patterns (short system prompts, let LumiBot handle the rest)
- Strategy lifecycle placement (agent created in ``initialize()``, run in ``on_trading_iteration()``)
- External MCP server wiring (URL-based, no local scripts)
- Observability and debugging (traces, summaries, warnings)
- Replay cache validation (warm reruns with zero model calls)
- Tearsheet interpretation (benchmarked against SPY)

Do not copy them blindly. Instead:

- Keep the shape that matches your use case
- Point the MCP server URL at whatever data source you need
- Write a 2-3 sentence system prompt about your strategy
- Inspect the trace when the behavior surprises you

What to Inspect After a Run
----------------------------

For each demo, review:

- The tearsheet and benchmark comparison
- The trades chart
- ``trades.csv`` and ``trade_events.csv``
- The agent trace JSON
- The per-run summary log lines

These artifacts answer:

- Why did the agent trade (or not trade)?
- What tools did it call?
- What evidence did it use?
- Did the run replay from cache?
- Were there any observability warnings?

Related Pages
-------------

- :doc:`agents` -- main guide and architecture
- :doc:`agents_quickstart` -- code patterns and API reference
- :doc:`agents_observability` -- traces, replay cache, and debugging
