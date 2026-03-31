# AI Trading Agent Component Guide

> Internal companion to the public `docsrc/agents_quickstart.rst` page. Describes how the AI agent component works inside a LumiBot strategy, focused on BotSpot strategy generation.

**Last Updated:** 2026-03-30
**Status:** Active
**Audience:** Internal (BotSpot Agent, contributors)

---

## Purpose

LumiBot's AI runtime is a strategy component. It is not a separate orchestration product and it does not bypass the normal strategy lifecycle.

The core usage pattern is:

1. Create the agent in `initialize()`
2. Built-in tools are included by default (no explicit listing needed)
3. Add external MCP servers via URL if the strategy needs external data
4. Run the agent from the lifecycle method that needs it
5. Inspect `result.summary`, warnings, traces, and cache behavior

---

## Public API Surface

Primary imports:

- `MCPServer` -- for adding external MCP servers
- `agent_tool` -- for adding custom strategy-level tools
- `self.agents.create(...)` -- create an agent in `initialize()`
- `self.agents["name"].run(...)` -- run the agent from a lifecycle method

Result surface:

- `result.summary` -- the agent's concluding summary
- `result.text` -- full text output
- `result.cache_hit` -- whether result came from replay cache
- `result.warning_messages` -- list of observability warnings
- `result.tool_calls` -- list of tool call events
- `result.tool_results` -- list of tool result events
- `(result.payload or {}).get("trace_path")` -- path to JSON trace

---

## Design Rules

- The strategy owns timing, scheduling, and execution
- The agent is a component inside the strategy, not a separate platform
- Built-in tools (positions, portfolio, prices, history, DuckDB, orders, docs) are included by default
- External data comes from MCP servers connected via URL
- System prompts should be 2-3 sentences; LumiBot's base prompt handles everything else
- The strategy should pass point-in-time context explicitly in backtests
- The runtime supports arbitrary MCP servers without restriction

---

## MCP Server Patterns

External MCP servers are URLs. No local scripts, no npm installs.

**Alpha Vantage (API key in URL):**

```python
MCPServer(
    name="alpha-vantage",
    url=f"https://mcp.alphavantage.co/mcp?apikey={os.environ['ALPHAVANTAGE_API_KEY']}",
    exposed_tools=["NEWS_SENTIMENT"],
)
```

**Smithery FRED (Bearer token in headers):**

```python
MCPServer(
    name="fred-macro",
    url="https://server.smithery.ai/@kablewy/fred-mcp-server/mcp",
    headers={"Authorization": f"Bearer {os.environ['SMITHERY_API_KEY']}"},
    exposed_tools=["search_series", "get_series_observations"],
)
```

---

## Teaching This in BotSpot Agent

BotSpot Agent should teach this API through:

- **Shared components:** Show the `MCPServer(url=..., exposed_tools=[...])` pattern. Note that built-in tools are default.
- **Shared examples:** URL-based MCP examples only. Short system prompts.
- **Shared reminders:** External MCP servers are URLs. Built-in tools are included automatically. System prompts are 2-3 sentences.

Key points for generated strategies:

- No `LUMIBOT_ROOT` path variables
- No `sys.executable` or script paths
- No explicit `BuiltinTools.xxx()` listing (they are default)
- `datasource_class=None` reads from `.env` config
- Flat `if __name__ == "__main__"` with `IS_BACKTESTING`
