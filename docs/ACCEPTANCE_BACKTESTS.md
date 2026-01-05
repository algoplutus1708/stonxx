# Acceptance Backtests (ThetaData) — Manual Release Gate

This document is the **canonical manual acceptance suite** for LumiBot backtesting (ThetaData) and release validation.

## Update protocol (read this before editing)

- **Append only**: never overwrite history rows; add a new row per run.
- **Every speed row must include machine specs** (even if repetitive) so future comparisons are meaningful.
- **Every row must include the `run_id`** so artifacts remain auditable in `Strategy Library/logs/`.
- Release gate runs must use **production-like flags** (see below).

## CI acceptance gate (source of truth)

- GitHub CI runs the real Strategy Library demos via `tests/backtest/test_acceptance_backtests_ci.py` as part of the
  normal `tests/backtest/` pytest run (these are not a special workflow/job).
- CI assertions are **strict** and driven by `tests/backtest/acceptance_backtests_baselines.json` (generated from
  `Strategy Library/logs/` via `scripts/generate_acceptance_backtests_baselines.py`).
- When updating expected outputs: append rows here *and* update the baseline JSON from the chosen baseline `run_id`s.

## Window semantics (avoid false “drift”)

- LumiBot treats `BACKTESTING_END` as **exclusive**.
- As a result, `*_settings.json` records `backtesting_end` as `(BACKTESTING_END - 1 day) 23:59:00` (local market TZ).

## Guardrails

- **Do not modify demo strategy files** under `Strategy Library/Demos/`. Fix issues in **LumiBot** (or the data-downloader if proven root cause).
- Use the shared downloader endpoint (do not hard-code an IP):
  - `DATADOWNLOADER_BASE_URL=http://data-downloader.lumiwealth.com:8080`
  - `DATADOWNLOADER_API_KEY` must be set (value lives in env/secrets; do not paste into docs).
- Wrap long runs with `/Users/robertgrzesik/bin/safe-timeout …`.

## Release time gate (required)

Each acceptance run must finish within **900s (15 minutes)** with **production-like flags**:

- `BACKTESTING_QUIET_LOGS=false`
- `BACKTESTING_SHOW_PROGRESS_BAR=true`
- `SHOW_PLOT=True`, `SHOW_INDICATORS=True`, `SHOW_TEARSHEET=True`

Notes:
- For debugging only, you may temporarily disable artifact generation to isolate compute vs plotting.
- The release gate is always the production-like run above.

## Recommended command template

Run from `Strategy Library/` so artifacts land in `Strategy Library/logs/`:

```bash
cd "/Users/robertgrzesik/Documents/Development/Strategy Library"
/Users/robertgrzesik/bin/safe-timeout 900s env \
  PYTHONPATH="/Users/robertgrzesik/Documents/Development/lumivest_bot_server/strategies/lumibot" \
  IS_BACKTESTING=True BACKTESTING_DATA_SOURCE=thetadata \
  DATADOWNLOADER_BASE_URL="http://data-downloader.lumiwealth.com:8080" \
  SHOW_PLOT=True SHOW_INDICATORS=True SHOW_TEARSHEET=True \
  BACKTESTING_QUIET_LOGS=false BACKTESTING_SHOW_PROGRESS_BAR=true \
  BACKTESTING_START=YYYY-MM-DD BACKTESTING_END=YYYY-MM-DD \
  python3 "Demos/<strategy>.py"
```

## Machine specs (required on every speed row)

Example format (repeat this on every speed row):

- `macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8`

## Canonical suite (currently 7 demos)

This suite will grow over time (more strategies, data sources, and/or windows). When adding a new case:
- add a new section below (including `#### Expected Results`)
- add/update the matching entry in `tests/backtest/acceptance_backtests_baselines.json`
- keep `docs/ACCEPTANCE_BACKTESTS.md` and the baseline JSON referencing the same `run_id`

Each strategy section includes:
- What to run (file + windows)
- What to validate (sanity checks)
- Anchor + history rows (metrics + wall time + machine specs)

### 1) AAPL Deep Dip Calls (GOOG; file name says AAPL)

- File: `Demos/AAPL Deep Dip Calls (Copy 4).py`
- CI window (`BACKTESTING_START/END`): `2020-01-01 → 2025-12-01`
- Validate:
  - trades occur in multiple “dip eras” (2020/2022/2025)
  - no obvious split-cliff behavior (GOOG mid-2022)
  - artifacts are produced (`*_trades.csv/html`, `*_stats.csv`, `*_tearsheet.html`, `*_settings.json`)

#### Expected Results (ThetaData / S3 v44)

- Correct Total Return = 863.00%
- Correct CAGR = 48.65%
- Correct Max DD = -34.30%
- Observed `backtest_time_seconds` (macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8) = 30.6s
- CI cap (seconds) <= 300
- Baseline `run_id` = `AAPLDeepDipCalls_2026-01-04_19-52_w1yl8v`

| run_id | lumibot | window | wall_time_s | total_return | cagr | max_dd | flags | machine |
|---|---:|---|---:|---:|---:|---:|---|---|
| `AAPLDeepDipCalls_2025-12-25_19-08_WHRsPm` | (unknown) | 2020-01-01 → 2025-11-30 | (n/a) | 865% | 48.72% | -33.08% | (unknown) | (unknown) |
| `AAPLDeepDipCalls_2026-01-02_10-25_3KsjXy` | 4.4.21 | 2020-01-01 → 2025-11-30 | 237.5 | 870% | 48.86% | -34.09% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `AAPLDeepDipCalls_2026-01-04_06-02_3HO2Ds` | 4.4.24 | 2020-01-01 → 2025-11-30 | 26.9 | 862% | 48.63% | -34.09% | historical (superseded; pre daily-bar end-row fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `AAPLDeepDipCalls_2026-01-04_11-14_lIPHBU` | 4.4.24 | 2020-01-01 → 2025-11-30 | 77.8 | 853% | 48.36% | -34.3% | historical (superseded; baseline updated under v44 cache semantics) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `AAPLDeepDipCalls_2026-01-04_19-52_w1yl8v` | 4.4.24 | 2020-01-01 → 2025-11-30 | 30.6 | 863% | 48.65% | -34.3% | prod-like (baseline; v44; queue-free) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |

### 2) Alpha Picks LEAPS (Call Debit Spread)

- File: `Demos/Leaps Buy Hold (Alpha Picks).py`
- CI window (`BACKTESTING_START/END`): `2025-10-01 → 2025-10-15` (must trade `UBER, CLS, MFC`)
- Historical / optional longer window (not in CI): `2025-01-01 → 2025-12-01`
- Validate:
  - short window trades include both legs for `UBER`, `CLS`, and `MFC`
  - full-year run (when used manually) produces artifacts (symbols may vary; log skip reasons)

#### Expected Results (ThetaData / S3 v44)

- Correct Total Return = 1.00%
- Correct CAGR = 18.00%
- Correct Max DD = -1.43%
- Observed `backtest_time_seconds` (macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8) = 33.3s
- CI cap (seconds) <= 120
- Baseline `run_id` = `LeapsCallDebitSpread_2026-01-04_22-07_IhWXKY`

| run_id | lumibot | window | wall_time_s | total_return | cagr | max_dd | flags | machine |
|---|---:|---|---:|---:|---:|---:|---|---|
| `LeapsCallDebitSpread_2025-12-25_19-14_lLFnSk` | (unknown) | 2025-10-01 → 2025-10-15 | (n/a) | 1% | 17.87% | -1.42% | (unknown) | (unknown) |
| `LeapsCallDebitSpread_2026-01-02_10-07_OZi6We` | 4.4.21 | 2025-10-01 → 2025-10-14 | 44.5 | 0% | 14.46% | -1.42% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `LeapsCallDebitSpread_2026-01-02_10-48_4UtvLT` | 4.4.21 | 2025-01-01 → 2025-11-30 | 285.5 | -3% | -3.03% | -19.33% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `LeapsCallDebitSpread_2026-01-04_05-13_ZpmFin` | 4.4.24 | 2025-10-01 → 2025-10-14 | 10.8 | 2% | 58.04% | -1.14% | historical (superseded; pre daily-bar end-row fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `LeapsCallDebitSpread_2026-01-04_11-20_vXE88y` | 4.4.24 | 2025-10-01 → 2025-10-14 | 5.4 | 0% | 11.81% | -1.16% | historical (superseded; baseline updated under v44 cache semantics) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `LeapsCallDebitSpread_2026-01-04_22-07_IhWXKY` | 4.4.25 | 2025-10-01 → 2025-10-14 | 33.3 | 1% | 18.0% | -1.43% | prod-like (baseline; v44; queue-free) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `LeapsCallDebitSpread_2026-01-04_05-53_OtxpYi` | 4.4.24 | 2025-01-01 → 2025-11-30 | 10.7 | -74% | -77.61% | -84.04% | historical (superseded; pre daily-bar end-row fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `LeapsCallDebitSpread_2026-01-04_11-22_rnMuYq` | 4.4.24 | 2025-01-01 → 2025-11-30 | 7.6 | -4% | -4.34% | -18.39% | prod-like (baseline) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |

### 3) TQQQ SMA200 (ThetaData vs Yahoo sanity)

- File: `Demos/TQQQ 200-Day MA.py`
- CI window (`BACKTESTING_START/END`): `2013-01-01 → 2025-12-01`
- Validate:
  - ThetaData result is stable and deterministic for this window
  - Yahoo is used only as an occasional manual parity sanity check (not run in CI)

#### Expected Results (ThetaData / S3 v44)

- Correct Total Return = 8,585.00%
- Correct CAGR = 42.16%
- Correct Max DD = -48.40%
- Observed `backtest_time_seconds` (macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8) = 13.8s
- CI cap (seconds) <= 180
- Baseline `run_id` = `TqqqSma200Strategy_2026-01-04_11-10_Wa65DX`

Yahoo one-time baseline (manual note; do not run in CI):
- `run_id` = `TqqqSma200Strategy_2026-01-04_04-40_2sdaIJ`
- Total Return = 8,272.00%; CAGR = 40.94%; Max DD = -48.82%; `backtest_time_seconds` = 11.3s

| run_id | lumibot | data_source | window | wall_time_s | total_return | cagr | max_dd | flags | machine |
|---|---:|---|---|---:|---:|---:|---:|---|---|
| `TqqqSma200Strategy_2025-12-25_19-22_UoZ2yn` | (unknown) | (unknown) | 2013-01-01 → 2025-11-30 | (n/a) | 8,272% | 40.94% | -48.82% | (unknown) | (unknown) |
| `TqqqSma200Strategy_2025-12-25_19-20_cQkd1T` | (unknown) | (unknown) | 2013-01-01 → 2025-11-30 | (n/a) | 8,585% | 42.17% | -48.40% | (unknown) | (unknown) |
| `TqqqSma200Strategy_2026-01-02_10-24_Uus6vb` | 4.4.21 | thetadata | 2013-01-01 → 2025-11-30 | 33.8 | 8,585% | 42.17% | -48.40% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `TqqqSma200Strategy_2026-01-02_10-25_fOI4Ek` | 4.4.21 | yahoo | 2013-01-01 → 2025-11-30 | 8.2 | 8,272% | 40.94% | -48.82% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `TqqqSma200Strategy_2026-01-04_04-39_xX9si4` | 4.4.24 | thetadata | 2013-01-01 → 2025-11-30 | 12.1 | 8,774% | 42.4% | -48.4% | historical (superseded; pre daily-bar end-row fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `TqqqSma200Strategy_2026-01-04_11-10_Wa65DX` | 4.4.24 | thetadata | 2013-01-01 → 2025-11-30 | 16.3 | 8,585% | 42.16% | -48.4% | prod-like (baseline) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `TqqqSma200Strategy_2026-01-04_04-40_2sdaIJ` | 4.4.24 | yahoo | 2013-01-01 → 2025-11-30 | 11.3 | 8,272% | 40.94% | -48.82% | prod-like (baseline) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |

### 4) Backdoor Butterfly 0DTE (regular fills; index + index options)

- File: `Demos/Backdoor Butterfly 0 DTE (Copy).py`
- Validate:
  - no crashes due to index placeholder tails / missing history
  - artifacts produced

CI uses the full-year window; the shorter window is retained only as historical speed context:
- CI window (`BACKTESTING_START/END`): `2025-01-01 → 2025-12-01`
- Historical / speed baseline (not in CI): `2025-01-01 → 2025-11-30`

#### Expected Results (ThetaData / S3 v44)

- Correct Total Return = -21.00%
- Correct CAGR = -23.12%
- Correct Max DD = -26.42%
- Observed `backtest_time_seconds` (macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8) = 235.2s
- CI cap (seconds) <= 600
- Baseline `run_id` = `BackdoorButterfly0DTE_2026-01-04_17-14_Dg5NJR`

| run_id | lumibot | window | wall_time_s | total_return | cagr | max_dd | flags | machine |
|---|---:|---|---:|---:|---:|---:|---|---|
| `BackdoorButterfly0DTE_2025-12-25_18-29_KAD4Qk` | (unknown) | 2025-01-01 → 2025-11-30 | (n/a) | -26% | -28.55% | -32.51% | (unknown) | (unknown) |
| `BackdoorButterfly0DTE_2025-12-31_15-43_TWzKau` | 4.4.20 | 2025-01-01 → 2025-11-30 | 79.8 | -22% | -24.00% | -30.13% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-02_10-29_HPNuUM` | 4.4.21 | 2025-01-01 → 2025-11-30 | 267.8 | -19% | -20.79% | -25.94% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-02_18-52_XdYcWQ` | 4.4.21 | 2025-01-01 → 2025-11-29 | 121.6 | -21% | -23.12% | -26.42% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-04_06-26_S1FSC2` | 4.4.24 | 2025-01-01 → 2025-11-30 | 120.5 | -20% | -22.1% | -25.48% | historical (superseded; pre daily-bar end-row fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-04_11-40_1VPPZ9` | 4.4.24 | 2025-01-01 → 2025-11-30 | 119.4 | -21% | -23.15% | -26.45% | historical (superseded; multileg parent NEW_ORDER dispatch nondeterminism) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-04_06-24_KaizMH` | 4.4.24 | 2025-01-01 → 2025-11-29 | 116.4 | -21% | -23.37% | -26.62% | historical (superseded; pre daily-bar end-row fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-04_11-27_KD9Qi0` | 4.4.24 | 2025-01-01 → 2025-11-29 | 118.0 | -21% | -23.11% | -26.41% | historical (superseded; minor rounding drift) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-04_11-33_sBKYi2` | 4.4.24 | 2025-01-01 → 2025-11-29 | 118.1 | -21% | -23.12% | -26.42% | historical (pre deterministic multileg parent dispatch) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTE_2026-01-04_17-14_Dg5NJR` | 4.4.24 | 2025-01-01 → 2025-11-30 | 235.2 | -21% | -23.12% | -26.42% | expected baseline (deterministic multileg parent dispatch; fresh-cache / CI-like) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |

### 5) MELI Deep Drawdown Calls

- File: `Demos/Meli Deep Drawdown Calls.py`
- CI window (`BACKTESTING_START/END`): `2013-01-01 → 2025-12-18`
- Validate:
  - entry trades occur (drawdown-triggered buys)
  - no “sawtooth” PV caused by missing option marks (forward-fill behavior remains stable)

This strategy was previously **under investigation** for baseline mismatch; CI uses the row marked `expected baseline`.

#### Expected Results (ThetaData / S3 v44)

- Correct Total Return = 104.00%
- Correct CAGR = 6.16%
- Correct Max DD = -98.17%
- Observed `backtest_time_seconds` (macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8) = 111.3s
- CI cap (seconds) <= 300
- Baseline `run_id` = `MeliDeepDrawdownCalls_2026-01-05_02-18_dKzthV`

| run_id | lumibot | window | wall_time_s | total_return | cagr | max_dd | status | machine |
|---|---:|---|---:|---:|---:|---:|---|---|
| `MeliDeepDrawdownCalls_2025-12-25_20-38_33bGtY` | (unknown) | 2013-01-01 → 2025-12-17 | (n/a) | 131% | 7.26% | -97.78% | expected (historical anchor) | (unknown) |
| `MeliDeepDrawdownCalls_2026-01-02_10-09_7yisFp` | 4.4.21 | 2013-01-01 → 2025-12-17 | 856.3 | -91% | -18.22% | -99.73% | under investigation | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `MeliDeepDrawdownCalls_2026-01-02_19-24_kZELl5` | 4.4.21 | 2013-01-01 → 2025-12-17 | 350.4 | 14% | 1.08% | -98.26% | under investigation (daily snapshot NBBO override) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `MeliDeepDrawdownCalls_2026-01-04_09-39_hyg1f1` | 4.4.24 | 2013-01-01 → 2025-12-17 | 18.1 | 82% | 5.12% | -98.2% | historical (superseded; pre daily-bar end-row fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `MeliDeepDrawdownCalls_2026-01-04_11-05_y7Ap6O` | 4.4.24 | 2013-01-01 → 2025-12-17 | 41.1 | -89% | -16.83% | -98.96% | historical (superseded; stale snapshot placeholder refetch caused missing option marks) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `MeliDeepDrawdownCalls_2026-01-05_02-18_dKzthV` | 4.4.25 | 2013-01-01 → 2025-12-17 | 111.3 | 104% | 6.16% | -98.17% | expected baseline (queue-free; post snapshot placeholder fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |

See: `docs/investigations/ACCURACY_AUDIT_2026-01-02.md` for the divergence notes and first-diff audit plan.

### 6) Backdoor Butterfly with SmartLimit

- File: `Demos/Backdoor Butterfly 0 DTE (Copy) - with SMART LIMITS.py`
- CI window (`BACKTESTING_START/END`): `2025-01-01 → 2025-12-01`
- Validate:
  - completes without stalling
  - artifacts produced
  - SmartLimit fills behave like “mid + slippage” (net multi-leg), not bid/ask worst-case

#### Expected Results (ThetaData / S3 v44)

- Correct Total Return = -6.00%
- Correct CAGR = -6.43%
- Correct Max DD = -13.41%
- Observed `backtest_time_seconds` (macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8) = 273.1s
- CI cap (seconds) <= 600
- Baseline `run_id` = `BackdoorButterfly0DTESmartLimit_2026-01-04_20-26_qtvxlf`

| run_id | lumibot | window | wall_time_s | total_return | cagr | max_dd | flags | machine |
|---|---:|---|---:|---:|---:|---:|---|---|
| `BackdoorButterfly0DTESmartLimit_2026-01-02_10-34_UTFoHq` | 4.4.21 | 2025-01-01 → 2025-11-30 | 283.0 | -3% | -2.96% | -13.58% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTESmartLimit_2026-01-02_19-49_QXkWuB` | 4.4.21 | 2025-01-01 → 2025-11-29 | 107.1 | -6% | -6.2% | -13.39% | prod-like | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTESmartLimit_2026-01-04_06-29_NduXK0` | 4.4.24 | 2025-01-01 → 2025-11-30 | 120.4 | -6% | -6.42% | -14.88% | historical (superseded; baseline updated under v44 cache semantics) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `BackdoorButterfly0DTESmartLimit_2026-01-04_20-26_qtvxlf` | 4.4.24 | 2025-01-01 → 2025-11-30 | 273.1 | -6% | -6.43% | -13.41% | prod-like (baseline; v44; queue-free) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |

### 7) SPX Short Straddle Intraday (production stall repro)

- File: `Demos/SPX Short Straddle Intraday (Copy).py`
- Validate:
  - no “silent hang” (logs continue via heartbeats while waiting)
  - run continues progressing; no permanent `download_status.active=true` without logs

CI uses the stall repro / prod parity window; the shorter window is retained only as historical speed context:
- CI window (`BACKTESTING_START/END`): `2025-01-06 → 2025-12-26`
- Historical / speed baseline (not in CI): `2025-01-01 → 2025-12-01`

#### Expected Results (ThetaData / S3 v44)

- Correct Total Return = -17.00%
- Correct CAGR = -17.50%
- Correct Max DD = -33.51%
- Observed `backtest_time_seconds` (macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8) = 76.1s
- CI cap (seconds) <= 600
- Baseline `run_id` = `SPXShortStraddle_2026-01-04_06-41_B1jF98`

| run_id | lumibot | window | wall_time_s | total_return | cagr | max_dd | notes | machine |
|---|---:|---|---:|---:|---:|---:|---|---|
| `SPXShortStraddle_2025-12-31_17-16_Ff79Hy` | 4.4.20 | 2025-01-01 → 2025-11-30 | 104.8 | -17% | -18.99% | -28.34% | speed baseline (historical) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `SPXShortStraddle_2026-01-02_10-39_XtAwjW` | 4.4.21 | 2025-01-06 → 2025-12-25 | 516.8 | -17% | -17.81% | -33.51% | stall repro window | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `SPXShortStraddle_2026-01-02_18-51_1JvQro` | 4.4.21 | 2025-01-06 → 2025-12-24 | 63.8 | -17% | -17.5% | -33.51% | stall repro window (perf fix) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `SPXShortStraddle_2026-01-04_06-37_sHgfVQ` | 4.4.24 | 2025-01-01 → 2025-11-30 | 70.7 | -21% | -22.96% | -30.87% | speed baseline (baseline) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |
| `SPXShortStraddle_2026-01-04_06-41_B1jF98` | 4.4.24 | 2025-01-06 → 2025-12-25 | 76.1 | -17% | -17.5% | -33.51% | stall repro window (baseline) | macOS=26.1; CPU=Apple M3 Max; RAM=48GB; Python=3.11.8 |

## Optional: Profiling artifact (opt-in)

To capture a profiler output for production-vs-local speed parity investigations, add:

- `BACKTESTING_PROFILE=yappi`

When enabled, LumiBot writes a `*_profile_yappi.csv` artifact next to the other backtest outputs.
