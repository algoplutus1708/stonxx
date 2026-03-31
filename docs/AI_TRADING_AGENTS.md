# AI Trading Agents: Backtest AI Agents with Real External Tools

> LumiBot is the only production framework that backtests AI trading agents with real external MCP tools, replay caching, and the same code for backtest and live.

**Last Updated:** 2026-03-30
**Status:** Active
**Audience:** Both

---

## Overview

LumiBot has a first-class AI agent runtime inside the `Strategy` lifecycle. An AI agent reasons, calls tools (including any of 20,000+ external MCP servers), and makes trading decisions **on every bar during a backtest**. The same strategy code runs live with zero changes. A built-in replay cache makes warm backtest reruns deterministic and fast.

If you are looking for an agentic backtesting framework, an LLM trading bot backtest solution, or a way to backtest AI-driven trading strategies with external data, LumiBot is the only production-ready option that puts the AI agent inside the simulation loop.

Related docs:

- `docs/AI_TRADING_AGENT_COMPONENT_GUIDE.md` -- internal component guide
- `docs/AI_TRADING_AGENT_CANONICAL_DEMOS.md` -- canonical demo strategies
- Public docs: `https://lumibot.lumiwealth.com/agents.html`

---

## Why LumiBot Is Different

Most tools that combine LLMs and trading fall into one of three categories:

1. **LLM outside the loop.** Platforms like QuantConnect let you call an LLM externally, but the model is not part of the backtest simulation. It cannot reason over point-in-time data on each bar.
2. **Agent frameworks with no backtesting.** CrewAI, AutoGen, and LangGraph build multi-agent workflows, but none of them simulate a trading backtest where the agent makes decisions bar by bar.
3. **Hobby scripts with no infrastructure.** Open-source experiments wire GPT to a broker but lack MCP support, replay caching, DuckDB, and production observability.

LumiBot combines:

- **LLM in the loop on every bar** -- the agent runs inside `on_trading_iteration()`, receives point-in-time state, calls tools, reasons, and submits orders
- **20,000+ external MCP servers** -- connect any MCP-compatible server with a URL
- **Replay caching** -- identical inputs = cached result, warm reruns in seconds
- **Any LLM provider** -- OpenAI, Anthropic, Google Gemini, and more
- **Same code for backtest and live** -- write once, backtest it, deploy it

---

## Quick Start

```python
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
```

No local MCP server scripts. No npm installs. No explicit built-in tool lists. Just a URL, a 2-3 sentence system prompt, and a standard LumiBot strategy.

---

## External MCP Servers

An external MCP server is just a URL. Any server that speaks the Model Context Protocol over HTTP works.

### Alpha Vantage (news, fundamentals, 130+ tools)

```python
MCPServer(
    name="alpha-vantage",
    url=f"https://mcp.alphavantage.co/mcp?apikey={os.environ['ALPHAVANTAGE_API_KEY']}",
    exposed_tools=["NEWS_SENTIMENT"],
)
```

### Smithery-hosted FRED (800,000+ economic series)

```python
MCPServer(
    name="fred-macro",
    url="https://server.smithery.ai/@kablewy/fred-mcp-server/mcp",
    headers={"Authorization": f"Bearer {os.environ['SMITHERY_API_KEY']}"},
    exposed_tools=["search_series", "get_series_observations"],
)
```

Any MCP server with a URL works. There are over 20,000 available today.

---

## Built-in Tools

All built-in tools are included by default. No need to list them.

- **Account:** `account.positions`, `account.portfolio`
- **Market:** `market.last_price`, `market.load_history_table`
- **DuckDB:** `duckdb.query`
- **Orders:** `orders.submit`, `orders.cancel`, `orders.modify`, `orders.open_orders`
- **Docs:** `docs.search`

---

## System Prompts

LumiBot handles common instructions in its base prompt (backtesting safety, investor policy, position sizing, DuckDB guidance). Your system prompt should be 2-3 sentences about your strategy:

```python
system_prompt=(
    "Use economic data to decide whether capital should be in TQQQ "
    "or a defensive asset like SHV. Check interest rates, inflation, "
    "and growth conditions. This is a binary allocator."
)
```

---

## Replay Cache

In backtesting, identical prompt + context + tools + timestamp = cached result. Warm reruns make zero LLM calls and zero MCP calls. This gives you deterministic backtests and cost control.

---

## Observability

Every run produces:

- A compact summary log line (agent name, model, cache status, warnings, summary)
- A structured JSON trace (full prompt, tool calls, results, warnings)
- Machine-readable artifacts (`agent_run_summaries.jsonl`, `agent_traces.zip`)

---

## Canonical Demos

Three demo strategies validate the full runtime:

1. **News Sentiment Strategy** -- Alpha Vantage MCP, news-driven stock selection
2. **Macro Risk Strategy** -- Smithery FRED MCP, macro regime allocation
3. **M2 Liquidity Strategy** -- Smithery FRED MCP, money supply allocation

Each demo produces benchmarked tearsheets, full traces, and validates replay caching.

---

## Architecture

Key code locations:

- Agent manager: `lumibot/components/agents/manager.py`
- Runtime wrapper: `lumibot/components/agents/runtime.py`
- DuckDB integration: `lumibot/components/agents/duckdb_tools.py`
- Schemas: `lumibot/components/agents/schemas.py`
- Strategy integration: `lumibot/strategies/_strategy.py`
