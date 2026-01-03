# Acceptance Smoke Tests (ThetaData, warm-cache gate)

This repo contains a small set of **fast ThetaData smokes** that serve as a release gate.

These are intentionally **not** the full Strategy Library acceptance suite (manual, long-window).
The CI smokes are designed to be:
- **warm-cache gate**: they should be fully served from the dev S3 cache
- **prod-like config**: downloader creds are configured (as in production), but the tests must fail
  if they actually try to use the downloader queue (cache miss / fallback)

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
  LUMIBOT_CACHE_MODE=s3_readwrite \\
  LUMIBOT_CACHE_S3_BUCKET="..." \\
  LUMIBOT_CACHE_S3_PREFIX="..." \\
  LUMIBOT_CACHE_S3_REGION="..." \\
  LUMIBOT_CACHE_S3_VERSION="..." \\
  LUMIBOT_CACHE_S3_ACCESS_KEY_ID="..." \\
  LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY="..." \\
  DATADOWNLOADER_BASE_URL="http://data-downloader.lumiwealth.com:8080" \\
  DATADOWNLOADER_API_KEY="..." \\
  python3 -m pytest -q -m acceptance_smoke tests/backtest/test_theta_strategies_integration.py
```

Tip: if you already have these set in `Strategy Library/Demos/.env`, you can run:
`LUMIBOT_DEMOS_ENV="/Users/robertgrzesik/Documents/Development/Strategy Library/Demos/.env"`.
If you prefer, you can use `LUMIBOT_CACHE_MODE=s3_readonly` in CI; the smokes are expected to not
write when the cache is warm.

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
