# AI Trading Agent Canonical Demos

> Three reference strategies that validate the AI agent runtime end to end.

**Last Updated:** 2026-03-30
**Status:** Active
**Audience:** Both

---

## The Three Demos

1. **News Sentiment Strategy** -- event-driven stock selection using Alpha Vantage news MCP
2. **Macro Risk Strategy** -- macro regime allocation using Smithery FRED MCP
3. **M2 Liquidity Strategy** -- liquidity-driven allocation using Smithery FRED MCP

---

## Why These Demos Exist

They validate:

- External MCP server connectivity (URL-based, no local scripts)
- Built-in tool usage (positions, portfolio, prices, DuckDB, orders)
- Replay cache behavior (deterministic warm reruns)
- Observability (traces, summaries, warnings)
- Benchmarked tearsheets against SPY

---

## News Sentiment Strategy

Event-driven stock selection using news data from Alpha Vantage MCP.

**MCP server:** `https://mcp.alphavantage.co/mcp?apikey=YOUR_KEY`

Validates:
- External news MCP integration via URL
- Agent-driven stock discovery from news flow
- Portfolio rotation and no-trade decisions
- Trace readability for real external data

---

## Macro Risk Strategy

Concentrated macro allocation using economic data from Smithery-hosted FRED MCP.

**MCP server:** `https://server.smithery.ai/@kablewy/fred-mcp-server/mcp`

Validates:
- MCP server with Bearer token authentication
- Agent discovery of macro indicators
- Binary allocation between TQQQ and SHV
- De-risking during adverse macro regimes
- Benchmarked evaluation against SPY

---

## M2 Liquidity Strategy

Longer-horizon liquidity regime allocation using Smithery-hosted FRED MCP.

**MCP server:** `https://server.smithery.ai/@kablewy/fred-mcp-server/mcp`

Validates:
- AI reasoning over money supply and liquidity data
- Defensive parking behavior
- Long-run replay behavior (2015-2026)
- Dividend handling and tearsheet generation

---

## What to Inspect for Every Demo

- Summary log lines
- Trace JSON files
- Trades chart and `trades.csv`
- `trade_events.csv`
- Tearsheet with benchmark comparison
- Replay cache status (warm reruns should show zero model calls)
