BotSpot MCP Integration
=======================

BotSpot exposes a public MCP server for strategy generation, backtesting, deployment monitoring, and artifact analysis.

Canonical endpoints
-------------------

- Production MCP root: ``https://mcp.botspot.trade``
- Production MCP path: ``https://mcp.botspot.trade/mcp``
- Production API: ``https://api.botspot.trade``

Authentication
--------------

Two authentication methods are supported:

1. OAuth 2.1 (recommended for hosted clients like Claude Desktop/Web and ChatGPT connectors)
2. API keys (recommended for CLI and IDE clients such as Claude Code, Cursor, and Codex)

API keys are created in BotSpot account settings and used as:

.. code-block:: text

   Authorization: Bearer botspot_YOUR_API_KEY

Client quickstarts
------------------

Claude Code
^^^^^^^^^^^

.. code-block:: bash

   claude mcp add --transport http botspot https://mcp.botspot.trade/mcp \
     -H "Authorization: Bearer botspot_YOUR_API_KEY"

Cursor
^^^^^^

.. code-block:: json

   {
     "mcpServers": {
       "botspot": {
         "url": "https://mcp.botspot.trade/mcp",
         "headers": {
           "Authorization": "Bearer botspot_YOUR_API_KEY"
         }
       }
     }
   }

Codex
^^^^^

.. code-block:: toml

   [mcp_servers.botspot]
   type = "sse"
   url = "https://mcp.botspot.trade/mcp"

   [mcp_servers.botspot.headers]
   Authorization = "Bearer botspot_YOUR_API_KEY"

Claude Desktop
^^^^^^^^^^^^^^

Use the MCP URL without a header and complete OAuth in the browser prompt:

.. code-block:: text

   https://mcp.botspot.trade/mcp

What this enables
-----------------

- Generate and refine strategies
- Launch and monitor backtests
- Query backtest artifacts using SQL
- Fetch visuals (strategy infographic/diagram and chart-ready backtest series)
- Inspect account usage and billing links

More resources
--------------

- BotSpot developer page: `https://botspot.trade/developers <https://botspot.trade/developers>`_
- BotSpot MCP guide: `https://github.com/Lumiwealth/botspot_node/blob/production/docs/mcp/mcp-server-guide.md <https://github.com/Lumiwealth/botspot_node/blob/production/docs/mcp/mcp-server-guide.md>`_
