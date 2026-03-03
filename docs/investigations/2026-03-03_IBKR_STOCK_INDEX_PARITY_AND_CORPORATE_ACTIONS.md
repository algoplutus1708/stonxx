# Title: IBKR Stock/Index Parity and Corporate Actions Fixes
One-line description: Root cause and fixes for IBKR-vs-Theta stock parity drift, delayed first fills, and missing corporate-action enrichment.
Last Updated: 2026-03-03
Status: In Progress
Audience: Engineering (Backtesting / Data Routing)

## Overview
This note captures three concrete findings from production-readiness parity runs and the corresponding code fixes:

1. Routed IBKR daily stock/index prefetch was under-warming long lookbacks.
2. Yahoo corporate-actions helper had a typo that made IBKR equity action enrichment a no-op.
3. SPX stress harness default window was too short for meaningful mixed-provider validation.

## Findings
1. Under-warmed routed IBKR daily stock/index windows
- File: `lumibot/backtesting/routed_backtesting.py`
- Previous behavior capped daily prefetch near backtest start (`length + 5` calendar days).
- Impact: long lookback strategies (e.g., SMA200) could start weeks/months late versus expected behavior.
- Repro: 2021-01-01 to 2022-12-31 TQQQ SMA200 mixed run first fill lagged to 2021-03-09.

2. Corporate-action helper typo
- File: `lumibot/tools/yahoo_helper.py`
- `get_symbol_actions()` called `get_symbol__data` (typo); `get_symbols_actions()` called `get_symbols__data`.
- Impact: IBKR equity enrichment (`dividend`, `stock_splits`) silently failed.
- Side effect: split/dividend handling could degrade in stock backtests routed to IBKR.

3. Stress scenario too short by default
- File: `scripts/ibkr_theta_prod_readiness.py`
- SPX stress default was a one-week window (`2025-01-06` to `2025-01-10`).
- Impact: insufficient stress coverage for index-options mixed routing validation.

## Fixes Applied
1. Routed IBKR daily prefetch now uses the computed lookback start (`start_datetime`) for stock/index day bars.
2. Yahoo actions helper typos fixed for single-symbol and multi-symbol actions methods.
3. Prod-readiness harness defaults SPX stress to 3 months (`2025-01-01` to `2025-03-31`) and increases stress timeout.
4. Added `--perf-mode` to `scripts/run_backtest_prodlike.py` to disable plot/indicator/progress overhead for runtime benchmarking.

## Validation
1. Unit tests
- `tests/backtest/test_yahoo_helper_actions.py`
- `tests/backtest/test_ibkr_equity_actions.py`
- `tests/test_routed_backtesting_ibkr_daily_prefetch.py`

2. Routed backtesting regression suite
- `tests/test_routed_backtesting_unit.py`
- `tests/test_routed_backtesting_registry_unit.py`
- `tests/test_routed_backtesting_routing_validation.py`
- `tests/test_backtesting_pandas_daily_routing.py`

3. Targeted parity reruns
- Focus window (`2021-01-01` -> `2022-12-31`):
  - Theta first fill: `2021-01-04`
  - Mixed first fill after fix: `2021-01-04` (previously `2021-03-09`)
- Full window (`2013-01-01` -> `2026-01-31`):
  - Mixed first fill moved to `2013-01-03` (from `2013-03-11`) after warmup fix.
  - Theta first fill remains `2013-03-21` due provider-history coverage limits in current environment.

## Open Items
1. Complete 3-month SPX stress mixed-vs-theta parity artifacts (theta run currently long-running).
2. Publish side-by-side trade-level parity report (fill counts, timestamp drift, price drift, equity drift) for that 3-month stress window.
