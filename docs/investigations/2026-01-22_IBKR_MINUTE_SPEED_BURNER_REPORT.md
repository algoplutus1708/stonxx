# 2026-01-22_IBKR_MINUTE_SPEED_BURNER_REPORT.md

> Rolling speed report for the IBKR minute-level “speed burner” benchmarks (futures + crypto). This is the paper trail for “10×–100× faster”.

**Last Updated:** 2026-01-22
**Status:** Active
**Audience:** Developers, AI Agents

---

## Overview

This report tracks backtest speed improvements over time using deterministic “speed burner” workloads:

- **Futures speed burner:** 2 symbols (e.g., `MES`, `MNQ`) on 1-minute cadence.
- **Crypto speed burner:** 3 symbols (e.g., `BTC`, `ETH`, `SOL`) on 1-minute cadence.

Each iteration intentionally stresses the hot path:
- `get_last_price()` per asset
- `get_historical_prices(..., 100, "minute")` per asset
- `get_historical_prices(..., 20, "day")` per asset
- frequent order submissions (alternating BUY/SELL market orders)

**Goal:** warm-cache runs must be queue-free and complete in bounded wall time.

---

## Benchmark runner(s)

- Unit-style stubbed runner (no network): `tests/test_ibkr_speed_burner_stubbed.py`
- Local benchmark script (no network): `scripts/bench_ibkr_speed_burner_stubbed.py`
- Local warm-cache runner (cache-only, asserts queue-free): `scripts/bench_ibkr_speed_burner_warm_cache.py`
- Cache warmer (cold run, populates parquet): `scripts/warm_ibkr_speed_burner_data.py`

Future (acceptance / cache-backed):
- Add a prodlike runner in `scripts/` that hits the cache and asserts queue-free behavior.

### Warm-cache prerequisites

The warm-cache runner is intentionally strict:
- it refuses to download data (queue-free invariant)
- it fails fast if the required parquet cache objects are missing

If it fails due to missing cache, warm the cache once (via apitest/downloader or a manual backtest run),
then re-run the warm-cache benchmark. The simplest warm step for this benchmark is:

- `python3 scripts/warm_ibkr_speed_burner_data.py`

Notes:
- Both scripts default `LUMIBOT_CACHE_FOLDER` to `tests/backtest/_ibkr_speed_burner_cache` (gitignored).
- The futures window in this benchmark uses an expired contract month. The warm step requires a
  populated IBKR conid registry (`<cache>/ibkr/conids.json`), which can be sourced from the
  one-time TWS conid backfill.

---

## Results table (fill in as we iterate)

Record wall time and iterations/sec for each milestone. Keep results append-only.

| Date | Change | Futures time (s) | Crypto time (s) | Notes |
|------|--------|------------------|-----------------|-------|
| 2026-01-22 | Source-tree stubbed benchmark (200 iters) | 1.072 | 1.491 | `scripts/bench_ibkr_speed_burner_stubbed.py` |
| 2026-01-22 | Native multi-minute cache keys + slice fast-path | 0.936 | 1.383 | Fix `15min` → `15minute` keying; benchmark runs with `IS_BACKTESTING=true` quiet logs; 11 series loads |
| 2026-01-22 | Warm-cache (cache-only) benchmark | 0.579 | 0.849 | `scripts/bench_ibkr_speed_burner_warm_cache.py` (queue-free; 2 futures + 3 crypto) |
| 2026-01-22 | Remove synthetic bars across gaps | TBD | TBD | Correctness + avoids fake work |
| 2026-01-22 | Prefetch once → slice forever | TBD | TBD | Eliminates refetch/window thrash |
| 2026-01-22 | DataFrame slice fast-path | TBD | TBD | Avoid per-call DataFrame rebuild |

### Long-run sanity (iterations scaling)

Backtests that feel “hours long” typically degrade with iteration count due to hidden O(n) / O(n log n)
work (e.g., event list cleanup, growing order/position lists).

This table uses a longer loop length to catch that early:

| Date | Change | Iterations | Futures time (s) | Crypto time (s) | Notes |
|------|--------|------------|------------------|-----------------|-------|
| 2026-01-22 | Warm-cache (cache-only) benchmark | 2000 | 6.737 | 9.460 | `python3 scripts/bench_ibkr_speed_burner_warm_cache.py --iterations 2000` |

---

## Notes / invariants

- Do not create synthetic bars across gaps. See `docs/BACKTESTING_SESSION_GAPS_AND_DATA_GAPS.md`.
- If the strategy clock lands in a futures session gap, orders may be accepted but must not fill until data resumes.
- Prefer “warm-cache speed” as the primary metric; cold downloads are allowed once but must not repeat.
