# Acceptance Backtests (ThetaData) — Manual Release Gate

This document defines the **manual end-to-end acceptance suite** used to validate:

- correctness (no lookahead, broker-like fills/marks, realistic option handling)
- stability (no silent stalls / infinite loops)
- performance (each run must finish under the release gate)

These runs execute the real demo strategies from **Strategy Library** so artifacts land in the same place humans
inspect (`Strategy Library/logs/`).

## Guardrails

- **Do not modify demo strategy files** under `Strategy Library/Demos/` as part of acceptance work.
  Fix issues in **LumiBot** (or the data-downloader if proven root cause).
- Use the shared downloader endpoint (do not hard-code an IP):
  - `DATADOWNLOADER_BASE_URL=http://data-downloader.lumiwealth.com:8080`
- Wrap runs with `/Users/robertgrzesik/bin/safe-timeout …` to enforce the release time gate.

## Release time gate (required)

Each acceptance run must finish within **900s (15 minutes)** with **production-like flags**:

- `BACKTESTING_QUIET_LOGS=false`
- `BACKTESTING_SHOW_PROGRESS_BAR=true`
- `SHOW_PLOT=True`, `SHOW_INDICATORS=True`, `SHOW_TEARSHEET=True`

Notes:
- For debugging only, you may temporarily disable artifact generation to isolate compute vs plotting.
- The release gate is always the production-like run above.

## Canonical suite (7 demos)

Run each demo with the specified window and validate the listed checks.

1) **AAPL Deep Dip Calls (GOOG; file name says AAPL)**
- File: `Demos/AAPL Deep Dip Calls (Copy 4).py`
- Window: `2020-01-01 → 2025-12-01`
- Validate:
  - trades occur in multiple “dip eras” (2020/2022/2025)
  - no obvious split-cliff behavior (GOOG mid-2022)
  - artifacts are produced (`*_trades.csv/html`, `*_stats.csv`, `*_tearsheet.html`, `*_settings.json`)

2) **Alpha Picks LEAPS (Call Debit Spread)**
- File: `Demos/Leaps Buy Hold (Alpha Picks).py`
- Short window: `2025-10-01 → 2025-10-15`
- Full-year window: `2025-01-01 → 2025-12-01`
- Validate:
  - short window trades include both legs for `UBER`, `CLS`, and `MFC`
  - full-year run produces artifacts (symbols may vary; log skip reasons)
  - artifacts produced

3) **TQQQ SMA200 (ThetaData vs Yahoo sanity)**
- File: `Demos/TQQQ 200-Day MA.py`
- Window: `2013-01-01 → 2025-12-01`
- Validate:
  - ThetaData result is directionally similar to Yahoo (no obvious inflation/deflation)
  - Run once with `BACKTESTING_DATA_SOURCE=thetadata` and once with `BACKTESTING_DATA_SOURCE=yahoo`

4) **Backdoor Butterfly 0DTE (index + index options)**
- File: `Demos/Backdoor Butterfly 0 DTE (Copy).py`
- Window: `2025-01-01 → 2025-12-01`
- Validate:
  - no crashes due to index placeholder tails / missing history
  - artifacts produced

5) **MELI Deep Drawdown Calls**
- File: `Demos/Meli Deep Drawdown Calls.py`
- Window: `2013-01-01 → 2025-12-18`
- Validate:
  - entry trades occur (drawdown-triggered buys)
  - no “sawtooth” portfolio valuation caused by missing option marks (forward-fill behavior remains stable)

6) **Backdoor Butterfly with SmartLimit**
- File: `Demos/Backdoor Butterfly 0 DTE (Copy) - with SMART LIMITS.py`
- Window: `2025-01-01 → 2025-12-01`
- Validate:
  - completes without stalling
  - artifacts produced

7) **SPX Short Straddle Intraday (production stall repro)**
- File: `Demos/SPX Short Straddle Intraday (Copy).py`
- Window: `2025-01-06 → 2025-12-26` (or the current canonical repro window)
- Validate:
  - no “silent hang” (logs continue via heartbeats while waiting)
  - run completes or continues progressing (no permanent `download_status.active=true` without logs)
  - Note: this run is highly cache-sensitive; the first run may be slower. The release gate is
    satisfied once the steady-state runtime (warm cache) is under 15 minutes.

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

## Optional: Profiling artifact (opt-in)

To capture a profiler output for production-vs-local speed parity investigations, add:

- `BACKTESTING_PROFILE=yappi`

When enabled, LumiBot writes a `*_profile_yappi.csv` artifact next to the other backtest outputs.
