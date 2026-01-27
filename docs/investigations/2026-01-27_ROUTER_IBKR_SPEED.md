# Router IBKR Speed Investigation (Futures + Crypto) — 2026-01-27

Goal: make **IBKR through the router** (production routing JSON) **≥20× faster first**, then **50–100×** (warm-cache), without sacrificing correctness.

Primary symptom: router IBKR futures backtests were taking **hours for ~1 week** because the router path was calling the downloader `ibkr/iserver/marketdata/history` in a hot loop (often ~1 request per simulated bar).

This doc is a **speed ledger** + **methodology**. Every perf change must:
- record benchmark results here (before/after),
- include YAPPI evidence,
- and add/adjust tests so the improvement sticks.

## 0) Alignment / invariants

**Production routing JSON (canonical)**
```json
{"default":"thetadata","crypto":"ibkr","future":"ibkr","cont_future":"ibkr"}
```

Notes:
- Router aliases `"futures"` → `"future"` but does **not** imply `"cont_future"`.
- Success metric is not “feels faster”: we require **history submits ~O(1)** (single digits) for warm-cache runs.

**Hard perf targets (warm-cache)**
- 1 day: ≤ 10s end-to-end
- 1 week: ≤ 60s end-to-end
- `ibkr/iserver/marketdata/history` submits: **single digits per run** (per symbol/timeframe), not proportional to bars

## 1) Standard benchmark suite

We iterate on **1-day windows** (fast feedback) and validate milestones on **1-week windows**.

Benchmarks:
1) GC client strategy
2) NQ client strategy

Profiling:
- Always run a non-profile baseline and then a YAPPI run.
- YAPPI time ≠ wall time (overhead), use it only for hotspot ranking.

## 2) Standard commands (prod-like runner)

We use `scripts/run_backtest_prodlike.py` for “production-like” runs (downloader + S3 caching).

Recommended investigation flags:
- use the production routing JSON
- set a dedicated cache folder under `~/Documents/Development/`
- **IMPORTANT (local-only):** pass `--use-dotenv-s3-keys` on this machine so S3 cache read/write works.
  - Without it, S3 ops can silently fail (and runs will look “warm” but keep queueing).
- use S3 cache **read-only** during investigations to avoid mutating shared caches:
  - `env LUMIBOT_CACHE_MODE=readonly ...`

Example:
```bash
/Users/robertgrzesik/bin/safe-timeout 900s env LUMIBOT_CACHE_MODE=readonly \
  python3 scripts/run_backtest_prodlike.py \
    --main "/Users/robertgrzesik/Documents/Development/backtest_strategies/nq_double_ema_test/main.py" \
    --start 2026-01-20 --end 2026-01-27 \
    --data-source '{"default":"thetadata","crypto":"ibkr","future":"ibkr","cont_future":"ibkr"}' \
    --use-dotenv-s3-keys \
    --cache-folder "/Users/robertgrzesik/Documents/Development/backtest_cache/router_speed" \
    --profile yappi \
    --label nq_router_week1_yappi
```

YAPPI analysis helper:
- `scripts/analyze_yappi_csv.py`

## 3) Speed ledger

### Columns
- `ts` (local wall clock)
- `git` (short SHA)
- `bench` (gc/nq)
- `mode` (router-json/router-default)
- `window` (1d/1w)
- `elapsed_s`
- `queue_submits`
- `history_submits` (subset)
- `top_paths` (top 3–5)
- `yappi_csv`
- `change`

### Baseline runs (pre-fix evidence; Jan 26, 2026)

These runs are preserved to show the “before” state: downloader-in-hot-loop behavior.

| ts | git | bench | mode | window | elapsed_s | queue_submits | history_submits | top_paths | yappi_csv | change |
|---|---|---|---|---:|---:|---:|---:|---|---|---|
| 2026-01-26 | (unknown) | gc | router-default | 1d | 1129 | 378 | 233 | `ibkr/iserver/marketdata/history` dominant | `.../20260126_180122_gc_ema_day1_yappi/..._profile_yappi.csv` | baseline (slow; queue wait dominates) |
| 2026-01-26 | (unknown) | nq | router-default + S3 keys | 1d | timeout@1800s | 378 | 378 | all history | `.../20260126_201209_nq_2el_day1_s3warm_yappi/..._profile_yappi.csv` | baseline (timed out; ~1 history/minute) |

### Phase 1 results (router IBKR prefetch enabled; local changes on top of `version/4.4.39`)

These runs use:
- routing: `{"default":"thetadata","crypto":"ibkr","future":"ibkr","cont_future":"ibkr"}`
- local cache: `/Users/robertgrzesik/Documents/Development/backtest_cache/router_speed`
- S3 cache: dev bucket/prefix, **read-only** (`LUMIBOT_CACHE_MODE=readonly`) during measurement

| ts | git | bench | mode | window | elapsed_s | queue_submits | history_submits | top_paths | yappi_csv | change |
|---|---|---|---|---:|---:|---:|---:|---|---|---|
| 2026-01-27 | a8f17429+local | nq | router-json | 1d (2026-01-20→21) | 26.6 | 1 | 0 | `ibkr/iserver/secdef/search` | (none) | warm-cache: effectively queue-free |
| 2026-01-27 | a8f17429+local | nq | router-json | 1w (2026-01-20→27) | 51.0 | 2 | 2 | `ibkr/iserver/marketdata/history` | (none) | bounded history fetches only (no per-bar thrash) |
| 2026-01-27 | a8f17429+local | nq | router-json | 1w (2026-01-20→27) | 25.5 | 0 | 0 | (none) | `/Users/robertgrzesik/Documents/Development/backtest_runs/20260127_001202_nq_router_20260120_week1_yappi/logs/NQDoubleEMATestStrategy_2026-01-27_00-12_VFcBmM_profile_yappi.csv` | YAPPI: ~0 network IO; dominated by pandas/numpy |
| 2026-01-27 | a8f17429+local | gc | router-json | 1d (2026-01-20→21) | 14.7 | 1 | 0 | `ibkr/iserver/secdef/search` | (none) | warm-cache: bounded |
| 2026-01-27 | a8f17429+local | gc | router-json | 1w (2026-01-20→27) | 163.0 | 5 | 5 | `ibkr/iserver/marketdata/history` | (none) | cold-ish: initial history fetches dominate |
| 2026-01-27 | a8f17429+local | gc | router-json | 1w (2026-01-20→27) | 12.6 | 0 | 0 | (none) | `/Users/robertgrzesik/Documents/Development/backtest_runs/20260127_001638_gc_router_20260120_week1_yappi/logs/GoldFuturesEMACrossover_2026-01-27_00-16_o66T9X_profile_yappi.csv` | warm-cache: dominated by pandas/numpy |

### Phase 2 results (4.4.40 WIP: end-date semantics + routed benchmark + native multi-minute IBKR bars)

Changes included in this phase:
- Keep `BACKTESTING_END=YYYY-MM-DD` semantics **exclusive** (end at midnight), but clamp the backtest
  loop so we do not "await market close" after we've advanced past the configured end bound.
- Router tearsheet benchmark prefers the router datasource (ThetaData) over Yahoo (daily bars).
- Router IBKR adapter preserves multi-minute series keys (`60m` → `60minute`) and fetches native IBKR bars for those timesteps.
- IBKR “stale end” negative-cache: if IBKR returns bars that don’t advance coverage, record a missing-window marker so we don’t re-fetch history in a loop.

| ts | git | bench | mode | window | elapsed_s | queue_submits | history_submits | top_paths | yappi_csv | change |
|---|---|---|---|---:|---:|---:|---:|---|---|---|
| 2026-01-27 | dad74668+local | nq | router-json | 2w (2025-01-06→20) | 225.7 | 15 | 14 | `ibkr/iserver/marketdata/history`, `ibkr/iserver/contract/*/info` | (none) | cold run (bounded history; no per-bar thrash) |
| 2026-01-27 | dad74668+local | nq | router-json | 2w (2025-01-06→20) | 134.8 | 0 | 0 | (none) | (none) | warm run (queue-free; dominated by pandas/strategy work + artifacts) |
| 2026-01-27 | dad74668+local | gc | router-json | 2w (2025-01-06→20) | 43.8 | 3 | 2 | `ibkr/iserver/marketdata/history`, `ibkr/iserver/contract/*/info` | (none) | cold run (native multi-minute bars; bounded history) |
| 2026-01-27 | dad74668+local | gc | router-json | 2w (2025-01-06→20) | 34.9 | 0 | 0 | (none) | (none) | warm run (queue-free) |
| 2026-01-27 | dad74668+local | nq | router-json | 1d (2025-01-06→07) | 58.3 | 0 | 0 | (none) | `/Users/robertgrzesik/Documents/Development/backtest_runs/20260127_072227_nq_1d_yappi/logs/NQDoubleEMATestStrategy_2026-01-27_07-22_TFHU7i_profile_yappi.csv` | YAPPI: dominated by pandas/numpy; network ~0 |

## 4) Root cause + fix summary

**Root cause (router path, before fix):**
- `_IbkrRoutingAdapter` fetched IBKR history per-window (often per simulated bar), instead of prefetching the full backtest window once.

**Fix (Phase 1):**
- Router IBKR adapter now prefetches `(start - warmup) → backtest_end` once per series key for:
  - futures / cont_future (minute/hour/day)
  - crypto (minute/hour/day special cases)
- Subsequent calls slice from the in-memory DataFrame.

See implementation: `lumibot/backtesting/routed_backtesting.py` (router IBKR adapter).

## 5) Tests / regression gates

Deterministic unit tests prevent regression back to “fetch in the hot loop”:
- `tests/backtest/test_routed_backtesting_ibkr_prefetch.py`
  - futures/cont_future minute: prefetch once + slice
  - futures/cont_future multi-minute: `60m` must call IBKR with `60minute` and prefetch once
  - crypto minute: prefetch once + slice
  - router benchmark must not call Yahoo: `tests/backtest/test_routed_backtesting_benchmark_prefers_router.py`
