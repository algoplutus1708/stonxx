# 2026-01-05 — SPX Copy3 Accuracy Audit (manager_bot_id=6be31002-44ec-4ae7-857a-db5e01323e7c)

## Scope

- Strategy code (read-only repro): `/Users/robertgrzesik/Documents/Development/Strategy Library/tmp/backtest_code/6be31002-44ec-4ae7-857a-db5e01323e7c/main.py`
- Engine: LumiBot (local + production-faithful flags)
- Data provider: ThetaData via remote downloader
- Cache backend: S3 (`LUMIBOT_CACHE_BACKEND=s3`)

## Goals

- Performance:
  - Cold S3 namespace run finishes (no hours/days).
  - Warm S3 proof run shows near-zero downloader submits.
- Accuracy:
  - Full “MELI-style” audit table for every trade with maximum telemetry.

## Run Log (fill in as executed)

### Cold namespace inspection (short window)

- LumiBot git ref:
- Date window:
- Workdir:
- Local cache folder:
- S3 cache version:
- Wall time:
- Queue submits (`Submitted to queue`):
- Notes on request patterns (chains/quotes/ohlc/snapshot/strike scans):

### Warm S3 proof (same window)

- Workdir:
- Local cache folder:
- S3 cache version (same as cold):
- Wall time:
- Queue submits:
- Notes:

## Accuracy Audit Deliverables

- Audit artifact(s) (CSV recommended):
  - `docs/investigations/data/2026-01-05_spx_copy3_trade_audit.csv` (TBD)
- Summary in this markdown:
  - Total trades:
  - Any mismatches found:
  - Data quality flags observed:

