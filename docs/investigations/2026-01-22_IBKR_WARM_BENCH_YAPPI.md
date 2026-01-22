# 2026-01-22_IBKR_WARM_BENCH_YAPPI.md

YAPPI profiling notes for the IBKR warm-run minute-level speed burner (futures + crypto).

**Last Updated:** 2026-01-22  
**Status:** Active  
**Audience:** Developers, AI Agents  

---

## Overview

This investigation captures the **YAPPI** profile for the IBKR warm-run “speed burner” benchmark so future speed work is driven by measurements, not guesses.

**Important**
- YAPPI adds substantial overhead. Use it to rank bottlenecks, but **do not compare** profiled wall times to non-profile benchmark runs.
- The benchmark itself is documented in `docs/investigations/2026-01-22_IBKR_MINUTE_SPEED_BURNER_REPORT.md`.

## Environment

- commit: `34599dfb`
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

