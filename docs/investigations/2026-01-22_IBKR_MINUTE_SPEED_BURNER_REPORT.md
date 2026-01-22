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

Future (acceptance / cache-backed):
- Add a prodlike runner in `scripts/` that hits the cache and asserts queue-free behavior.

---

## Results table (fill in as we iterate)

Record wall time and iterations/sec for each milestone. Keep results append-only.

| Date | Change | Futures time (s) | Crypto time (s) | Notes |
|------|--------|------------------|-----------------|-------|
| 2026-01-22 | Source-tree stubbed benchmark (200 iters) | 1.072 | 1.491 | `scripts/bench_ibkr_speed_burner_stubbed.py` |
| 2026-01-22 | Remove synthetic bars across gaps | TBD | TBD | Correctness + avoids fake work |
| 2026-01-22 | Prefetch once → slice forever | TBD | TBD | Eliminates refetch/window thrash |
| 2026-01-22 | DataFrame slice fast-path | TBD | TBD | Avoid per-call DataFrame rebuild |

---

## Notes / invariants

- Do not create synthetic bars across gaps. See `docs/BACKTESTING_SESSION_GAPS_AND_DATA_GAPS.md`.
- If the strategy clock lands in a futures session gap, orders may be accepted but must not fill until data resumes.
- Prefer “warm-cache speed” as the primary metric; cold downloads are allowed once but must not repeat.
