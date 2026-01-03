# Acceptance Smoke Tests (ThetaData)

This repo contains a small set of **short-window, end-to-end ThetaData backtests** that serve as a
release smoke gate.

These are intentionally **not** the full Strategy Library acceptance suite (those are manual and
long-window). The smokes exist to catch obvious regressions in:
- ThetaData downloader connectivity + queue behavior
- Index options + minute quotes
- Daily cadence data plumbing
- Strategy runner/backtest engine stability

## What runs

- `tests/backtest/test_theta_strategies_integration.py` (marked `acceptance_smoke`)

These tests are written to **skip** cleanly when required secrets are not present.

## How to run locally

```bash
cd "/Users/robertgrzesik/Documents/Development/lumivest_bot_server/strategies/lumibot"

/Users/robertgrzesik/bin/safe-timeout 1800s env \\
  BACKTESTING_DATA_SOURCE=ThetaData \\
  DATADOWNLOADER_BASE_URL="http://data-downloader.lumiwealth.com:8080" \\
  DATADOWNLOADER_API_KEY="***" \\
  python3 -m pytest -q -m acceptance_smoke tests/backtest/test_theta_strategies_integration.py
```

## CI (trusted only)

To run these in GitHub Actions you must provide:
- `DATADOWNLOADER_API_KEY` (secret)
- `DATADOWNLOADER_BASE_URL` (env, usually `http://data-downloader.lumiwealth.com:8080`)

Recommended pattern:
- run on `workflow_dispatch` (manual “release gate”)
- optionally add a scheduled nightly run

Keep the smoke windows short (days/weeks), and avoid full-year runs in PR CI.
