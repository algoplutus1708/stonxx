AI Agent Observability
======================

LumiBot's AI agent runtime is only useful if every run is fully inspectable. The observability system records everything the agent did so you can audit reasoning, validate data integrity, and debug surprising behavior.

Default Logs
------------

Every agent run emits a compact summary log line that includes:

- Agent name
- Mode (backtest or live)
- Model used
- Cache hit or miss
- Tool call count
- Warning count
- The agent's summary conclusion
- Path to the trace file

The runtime also emits detailed lines for:

- Individual tool calls and their arguments
- Tool results
- Model text output
- Observability warnings

Trace Files
-----------

Each run writes a structured JSON trace that is the source of truth for debugging. The trace records:

- The full composed prompt surface (base prompt + system prompt + context)
- Every tool call with arguments
- Every tool result
- The agent's summary and reasoning
- Observability warnings
- Cache hit/miss metadata
- DuckDB query metrics
- Current datetime and timezone at the time of the run

From strategy code, the trace path is available on the result object:

.. code-block:: python

    trace_path = (result.payload or {}).get("trace_path")

Replay Cache
------------

In backtests, LumiBot caches every agent run. When a subsequent run hits the same combination of prompt, context, model, tool surface, and simulated timestamp, the cached result is returned without making any LLM or MCP calls.

Warm reruns show:

- ``cache_hit=True`` in the result
- Zero model API calls
- Zero external MCP calls
- Identical outputs to the original run

Replay caching makes agentic backtests:

- **Deterministic** -- same inputs always produce same outputs
- **Fast** -- warm reruns complete in seconds instead of minutes
- **Cost-effective** -- no duplicate LLM or MCP API charges

Per-Run Summary Artifacts
-------------------------

LumiBot writes machine-readable artifacts for agent runs:

- ``agent_run_summaries.jsonl`` -- one JSON line per agent run with summary, warnings, and metadata
- ``agent_traces.zip`` -- packaged trace files for the full backtest

These artifacts support downstream tooling, dashboards, and run history display without reparsing raw logs.

Observability Warnings
----------------------

Warnings are diagnostics, not hard enforcement rules. They flag suspicious conditions so you can investigate:

- **No tools called** -- the agent made a decision without consulting any tools
- **Tool error** -- a tool returned an error
- **Future-dated data** -- a tool result references data published after the simulated backtest time
- **Unsupported order** -- an order was submitted without visible supporting evidence in the trace

Warnings appear in:

- The summary log line
- The structured JSON trace
- ``result.warning_messages`` on the result object

Warnings do not automatically invalidate a run, but they are a strong signal that the run should be reviewed.

Recommended Debugging Workflow
------------------------------

When a run looks wrong:

1. **Read the summary line** in the logs. Check the agent name, cache status, tool count, and warning count.
2. **Inspect tool calls and results** in the logs. Did the agent call the right tools? Did the tools return useful data?
3. **Open the trace JSON.** This is the full record of everything the agent saw and did.
4. **Check cache status.** Was this a fresh run or a replay? If it was a replay, the issue is in the original run, not this one.
5. **Review warnings.** Are there future-dated data warnings? Missing tool usage? Unsupported orders?
6. **Compare the summary to the outcome.** Does the agent's stated reasoning match the actual trade or no-trade decision?

Related Pages
-------------

- :doc:`agents` -- main guide and architecture
- :doc:`agents_quickstart` -- code patterns and API reference
- :doc:`agents_canonical_demos` -- the three reference demo strategies
