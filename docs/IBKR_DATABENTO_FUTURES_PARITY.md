# IBKR Futures Parity vs Stored “DataBento Baseline” Artifacts

Goal: make IBKR REST futures backtesting **fast** and **correct**, and validate it against the most recent “known-good” futures backtest artifacts that were generated using the old DataBento backtesting path (no live DataBento key required).

## What “parity” means here

We measure parity at three levels:

1) **Price-line parity (baseline `*_indicators.csv`)**
- Compare the canonical plotted line (usually the underlying symbol price) against the IBKR re-run.
- Tick tolerance is per-root (MES tick = 0.25, ES tick = 0.25, etc.).

2) **Execution parity**
- Same fill count, side sequence, and fill prices (tick-tolerant).

3) **Portfolio parity**
- `*_stats.csv` equity curve matches closely if (1) and (2) match.
- Warm cache performance is acceptable (no repeated downloader hammering).

## Canonical parity mode: OHLC-only (Trades)

The baseline artifacts were generated using OHLC-style backtests, so for IBKR parity we use:
- IBKR `history_source="Trades"` (OHLC bars)
- and avoid quote-based fills for parity runs.

This is a *parity harness choice*; it is not intended to reduce realism for all IBKR backtests.

## Continuous futures semantics

For parity we want **LumiBot synthetic continuous futures** semantics (same as Tradovate/ProjectX).

IBKR REST cont-futures backtests therefore resolve a roll schedule using:
- `lumibot/tools/futures_roll.py`

and fetch the underlying explicit contracts.

## How to run the artifact-baseline parity suite (local)

Requires env vars (via `botspot_node/.env-local`):
- `DATADOWNLOADER_BASE_URL`, `DATADOWNLOADER_API_KEY`
- `LUMIBOT_CACHE_*` (S3 mirroring)

Run:
- `python3 scripts/run_ibkr_futures_parity_artifact_baselines.py --cache-version v2`

Outputs:
- `tests/backtest/_parity_runs/ibkr_vs_artifact_baselines_<timestamp>/...`
- `summary.md` and `summary.json`

Notes:
- Default run is **CME-only** (to match the current paid entitlements). Use `--include-non-cme` to attempt COMEX/NYMEX, etc.

## Pytest parity apitest (smoke)

There is an opt-in apitest that runs a short parity check:
- `tests/backtest/test_ibkr_databento_futures_parity_apitest.py`

## Known sources of mismatch

- Continuous futures: if a window spans a roll boundary, the stitched series must match the roll schedule.
- Maintenance gaps / weekends: futures have a daily maintenance gap and weekend close; caching must not repeatedly refetch those closed windows.
- Holiday early closes: CME equity futures can close early (e.g., Labor Day 13:00 ET), producing large bar timestamp gaps that can affect “next bar open” execution semantics.
- Tearsheet generation: short/degenerate windows can trip QuantStats KDE. LumiBot retries with KDE disabled.

## Current status (dev cache v2)

Artifact baselines selected by the user:
- `MESFlipStrategy_2025-11-25_23-19_dJE7Kl_*` (CME, ~5 days)
- `MESMomentumSMA9_2025-10-15_12-52_88xWTg_*` (CME, ~29 days)
- `GoldFlipMinuteStrategy_2025-11-12_01-58_ObSl6b_*` (COMEX, ~25 days; slow / non-CME)

Results snapshot:
- MESFlipStrategy: trade parity PASS (fills match exactly); indicators max diff = 0.25; equity curve diff is small float noise.
- MESMomentumSMA9: still FAIL (strict) due to CME early-close gap behavior interacting with ATR-based bracket stops (one-tick/14 ATR drift causing stop-price mismatch, cascading trade-sequence divergence). A 4.4.36 fix removed the worst symptom (“use 18:00 open while timestamp is 13:00”) and is locked in via a stubbed unit test; remaining mismatch is documented here:
  - `docs/investigations/2026-01-19_IBKR_FUTURES_MESMOMENTUM_SESSION_GAP_FIX_4.4.36.md`

Operational note:
- If the remote downloader is unstable (queue submit timeouts), full parity harness re-runs can stall before populating the per-run cache folder. In that case, re-run once the downloader is stable or using already-warmed caches.
