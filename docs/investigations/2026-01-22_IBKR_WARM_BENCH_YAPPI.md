# 2026-01-22_IBKR_WARM_BENCH_YAPPI.md

YAPPI profiling notes for the IBKR warm-run minute-level speed burner (futures + crypto).

**Last Updated:** 2026-01-23  
**Status:** Active  
**Audience:** Developers, AI Agents  

---

## Overview

This investigation captures the **YAPPI** profile for the IBKR warm-run “speed burner” benchmark so future speed work is driven by measurements, not guesses.

**Important**
- YAPPI adds substantial overhead. Use it to rank bottlenecks, but **do not compare** profiled wall times to non-profile benchmark runs.
- The benchmark itself is documented in `docs/investigations/2026-01-22_IBKR_MINUTE_SPEED_BURNER_REPORT.md`.

## Environment

- commit: `41ffb849`
- python: `3.11.8`
- pandas: `2.2.1`
- platform: `macOS-26.1-arm64-arm-64bit`

## Commands

Warm-run benchmark (median-of-3 is recorded separately; no profiler):

```bash
env LUMIBOT_DISABLE_DOTENV=1 python3 scripts/bench_ibkr_speed_burner_warm_cache.py --iterations 2000
env LUMIBOT_DISABLE_DOTENV=1 python3 scripts/bench_ibkr_speed_burner_warm_cache.py --iterations 20000
```

YAPPI capture (do not compare wall times to the above):

```bash
env LUMIBOT_DISABLE_DOTENV=1 python3 scripts/bench_ibkr_speed_burner_warm_cache.py \
  --iterations 2000 \
  --profile-yappi-csv tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_34599dfb_2000_profile_yappi.csv
```

YAPPI analysis helper:

```bash
python3 scripts/analyze_yappi_csv.py \
  tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_34599dfb_2000_profile_yappi.csv
```

## Bucket breakdown (self time / `tsub_s`)

From `scripts/analyze_yappi_csv.py`:

- `pandas_numpy`: ~57%
- `lumibot_other`: ~29%
- `other`: ~12%
- `stdlib_wait`: ~2%
- `progress_logging`: ~1%

Interpretation:
- Warm-run iteration throughput is dominated by **pandas slicing/copies** and per-call object construction overhead in LumiBot’s bars/history pipeline.

## Top hotspots (by self time / `tsub_s`)

Top items from the 2000-iteration profile (self time focuses on “where CPU is really spent”):

1. `lumibot/entities/data.py:519 Data.checker` (data validation wrapper)
2. `pandas/core/generic.py DataFrame._slice`
3. `pandas/core/construction.py sanitize_array`
4. `pandas/core/arrays/datetimelike.py DatetimeArray._validate_scalar`
5. `pandas/core/indexes/base.py Index.__new__`
6. `pandas/core/array_algos/take.py _take_nd_ndarray`
7. `pandas/core/internals/managers.py BlockManager._slice_take_blocks_ax0`
8. `lumibot/entities/data.py:865 Data.get_bars` (inclusive hotspot; slicing + column selection)
9. `inspect.py:_signature_from_function` + `inspect.Signature` + `inspect.Parameter` (introspection overhead inside `Strategy.get_historical_prices`)
10. `lumibot/entities/bars.py:167 Bars.__init__` (derived-column insertion + pandas mutation)

## Actionable next steps (driven by this profile)

1) Remove per-call `inspect.signature()` work in `Strategy.get_historical_prices` by caching per data source function/class.  
2) Make `Bars.__init__` cheaper for pandas-backed backtests by avoiding repeated derived-column insertion work.  
3) Reduce pandas work in `Data.get_bars` by minimizing per-call DataFrame column selection and redundant tail/slice operations.

These changes should be measured after each commit using the canonical benchmark protocol in the speed report.

## Milestones (profile deltas)

### 2026-01-22 — Cache `Strategy.get_historical_prices()` signature check

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_inspectcache_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `pandas_numpy`: ~59%
- `lumibot_other`: ~31%
- `other`: ~8%

Key delta vs baseline:
- `inspect.*` functions (signature/parameter construction) no longer show up as a dominant hotspot, confirming the per-call introspection overhead was removed.

### 2026-01-22 — Faster `Data.get_bars()` warm-run fast-path

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_datagbars_fastpath_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `pandas_numpy`: ~46%
- `lumibot_other`: ~42%
- `other`: ~10%

Key delta:
- pandas share drops substantially, and the dominant hotspots shift toward LumiBot-side overhead:
  - `Bars.__init__`
  - `BacktestingBroker._process_trade_event`
  - `PandasData.find_asset_in_data_store`

### 2026-01-23 — Precompute derived `return` once + skip per-slice Bars inserts

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_returns_precompute_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~58%
- `pandas_numpy`: ~28%
- `other`: ~9%
- `stdlib_wait`: ~4%
- `progress_logging`: ~1%

Key delta:
- `Bars.__init__` and pandas `__setitem__/BlockManager.insert` no longer show up as dominant hotspots because
  `return` is precomputed once per dataset (in `Data.repair_times_and_fill`) and `Bars` skips derived-column work
  when those columns are already present.
- Remaining inclusive hotspots are now mostly LumiBot-side broker/order pipeline and data-source lookup:
  - `BacktestingBroker._submit_order` / `process_pending_orders`
  - `InteractiveBrokersRESTBacktesting.get_quote`
  - `PandasData.find_asset_in_data_store`

### 2026-01-23 — Cache `_data_store` key lookups (`PandasData.find_asset_in_data_store`)

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_findasset_cache_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~56%
- `pandas_numpy`: ~30%

Key delta:
- `PandasData.find_asset_in_data_store` drops from a top inclusive hotspot to ~0.06s total for ~50k calls in the
  benchmark (cache hits), confirming the cache removed repeated candidate-list construction and dict probes.

### 2026-01-23 — Skip submit-time audit work when disabled

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_audit_lazy_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~58%
- `pandas_numpy`: ~29%

Key delta:
- `_audit_submit_fields()` no longer runs when audits are disabled (default), removing a large amount of quote work
  from the order submission hot path.

### 2026-01-23 — Lazy order events (allocation reduction)

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_1e7ab862_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~59%
- `pandas_numpy`: ~32%

Key delta:
- `Order.__init__` no longer allocates multiple `threading.Event()` objects per order (lazy allocation). This removes
  large numbers of internal `threading.Condition` allocations and reduces per-order overhead in high-churn backtests.

### 2026-01-23 — Skip OrderClass enum conversion for non-parent (small hot-path cut)

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_f257fce7_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~57%
- `pandas_numpy`: ~31%
- `other`: ~7%
- `stdlib_wait`: ~4%
- `progress_logging`: ~1%

Key delta:
- Profile confirms we are now dominated by **LumiBot order + event pipeline** and **pandas datetime scalar validation**
  rather than the earlier bars-construction hotspots.
- Next likely wins are:
  - reduce order-status equivalence checks (`Order.is_equivalent_status`) and enum comparisons (`OrderClass.__eq__`)
  - eliminate repeated `Index.__contains__` probes in tight loops
  - reduce per-iteration logger overhead (`StrategyLoggerAdapter.isEnabledFor`) and repeated `os.environ` lookups

### 2026-01-23 — Cache quiet-logs mode (remove per-call env lookups)

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_quietlogs_cache_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~59%
- `pandas_numpy`: ~32%
- `stdlib_wait`: ~4%
- `other`: ~3%
- `progress_logging`: ~1%

Key delta:
- `StrategyLoggerAdapter.isEnabledFor` and `os.environ` lookups no longer appear as dominant hotspots; quiet-logs mode
  is now cached during logger setup.

### 2026-01-23 — Speed up `get_iter_count()` (cursor + NumPy search)

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_itercount_cursor_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~68%
- `pandas_numpy`: ~22%
- `stdlib_wait`: ~5%
- `other`: ~4%
- `progress_logging`: ~1%

Key delta:
- `DatetimeArray._validate_scalar` / `_unbox_scalar` and `DatetimeIndex.searchsorted` are no longer dominant.
  `check_data()` now uses the optimized `get_iter_count()` (dict hit → monotonic cursor → NumPy searchsorted),
  which avoids pandas datetime scalar validation on the common “dt not an exact bar timestamp” path.

### 2026-01-23 — Avoid `.iloc` indexer overhead in `Data.get_bars()` (commit `51f8b575`)

Capture:
- `tests/backtest/_ibkr_speed_burner_cache/_profiles/ibkr_warmcache_df_slice_fastpath_2000_profile_yappi.csv`

Bucket summary (self time / `tsub_s`):
- `lumibot_other`: ~70%
- `pandas_numpy`: ~20%

Key delta:
- `_iLocIndexer.*` no longer appears as a dominant inclusive hotspot; `Data.get_bars()` now slices via
  `DataFrame._slice()` which avoids the `.iloc` indexer stack for integer row bounds.
- Warm-cache benchmark median improves (see `docs/investigations/2026-01-22_IBKR_MINUTE_SPEED_BURNER_REPORT.md`).
