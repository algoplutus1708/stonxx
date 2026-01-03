# Acceptance Smoke Tests (ThetaData, S3-only)

This repo contains a small set of **fast ThetaData smokes** that serve as a release gate.

These are intentionally **not** the full Strategy Library acceptance suite (manual, long-window).
The CI smokes are designed to be:
- **S3-only** (read from the dev cache bucket)
- **read-only** (never write to S3 in CI)
- **strict** (fail fast on cache miss; no fallback to downloader/ThetaData)

They exist to catch obvious regressions in:
- S3 cache hydration path (parquet downloads + schema expectations)
- Index options chains + minute quotes (minimal cached fixtures)
- “no silent fallback” behavior (a miss should fail the job)

## What runs

- `tests/backtest/test_theta_strategies_integration.py` (marked `acceptance_smoke`)

These tests **fail in CI** if required S3 secrets are missing, and **skip locally** if you
haven’t configured the S3 cache env vars.

## How to run locally

```bash
cd "/Users/robertgrzesik/Documents/Development/lumivest_bot_server/strategies/lumibot"

/Users/robertgrzesik/bin/safe-timeout 1800s env \\
  LUMIBOT_CACHE_BACKEND=s3 \\
  LUMIBOT_CACHE_MODE=s3_readonly \\
  LUMIBOT_CACHE_STRICT=true \\
  LUMIBOT_CACHE_S3_BUCKET="..." \\
  LUMIBOT_CACHE_S3_PREFIX="..." \\
  LUMIBOT_CACHE_S3_REGION="..." \\
  LUMIBOT_CACHE_S3_VERSION="..." \\
  LUMIBOT_CACHE_S3_ACCESS_KEY_ID="..." \\
  LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY="..." \\
  python3 -m pytest -q -m acceptance_smoke tests/backtest/test_theta_strategies_integration.py
```

Tip: if you already have these set in `Strategy Library/Demos/.env`, you can run:
`LUMIBOT_DEMOS_ENV="/Users/robertgrzesik/Documents/Development/Strategy Library/Demos/.env"`.
If your local `.env` uses `LUMIBOT_CACHE_MODE=readwrite`, override it to `s3_readonly` for smokes.

## CI

These smokes run as a required step inside the main CI workflow:
- `.github/workflows/cicd.yaml`

They require these GitHub secrets:
- `LUMIBOT_CACHE_S3_BUCKET`
- `LUMIBOT_CACHE_S3_PREFIX`
- `LUMIBOT_CACHE_S3_REGION`
- `LUMIBOT_CACHE_S3_VERSION`
- `LUMIBOT_CACHE_S3_ACCESS_KEY_ID`
- `LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY`
