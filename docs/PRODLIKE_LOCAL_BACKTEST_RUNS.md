# Prod-Like Local Backtests (NVDA / SPX / Repros)

This doc standardizes how we run **production-faithful** backtests locally without:
- accidentally loading unrelated `.env` files (LumiBot can scan recursively), or
- mixing artifacts across runs, or
- running long, unbounded commands.

## Rules

- **Always use a timeout guard**: wrap runs with `/Users/robertgrzesik/bin/safe-timeout …`.
- **Never run from `Strategy Library/` directly** (it often contains nested `.env` files).
- Prefer **short windows** (days/weeks/months) for diagnosis; only run full windows once request volume looks sane.
- Do not delete shared caches. Use `LUMIBOT_CACHE_S3_VERSION=...` to isolate “cold namespace” simulations.

## Canonical runner

Use `scripts/run_backtest_prodlike.py`.

Key behavior:
- Runs the strategy in a **clean per-run workdir** under `~/Documents/Development/backtest_runs/…`.
- Writes artifacts to `workdir/logs/` (`*_tearsheet.html`, `*_trades.csv`, `*_logs.csv`, `*_settings.json`).
- Loads downloader + S3 config from `botspot_node/.env-local` **without printing secrets**.
- Optionally copies artifacts into another folder (e.g., `Strategy Library/logs`) via `--copy-artifacts-to`.

## NVDA example (short-window diagnostic)

```bash
RUNID="$(date +%Y%m%d_%H%M%S)"
CACHE_DIR="/Users/robertgrzesik/Documents/Development/tmp/lumibot_cache_nvda_${RUNID}"
mkdir -p "$CACHE_DIR"

/Users/robertgrzesik/bin/safe-timeout 600s \
  python3 scripts/run_backtest_prodlike.py \
    --label nvda_diag \
    --cache-folder "$CACHE_DIR" \
    --main "/Users/robertgrzesik/Documents/Development/Strategy Library/tmp/backtest_code/334e2c98-7134-4f38-860c-b6b11879a51b/main.py" \
    --start 2024-01-02 \
    --end 2024-03-30 \
    --copy-artifacts-to "/Users/robertgrzesik/Documents/Development/Strategy Library/logs"
```

## SPX example (cold namespace inspection)

```bash
RUNID="$(date +%Y%m%d_%H%M%S)"
CACHE_DIR="/Users/robertgrzesik/Documents/Development/tmp/lumibot_cache_spx_${RUNID}"
mkdir -p "$CACHE_DIR"

/Users/robertgrzesik/bin/safe-timeout 900s \
  python3 scripts/run_backtest_prodlike.py \
    --label spx_copy2_cold_inspect \
    --cache-folder "$CACHE_DIR" \
    --cache-version "spx_cold_${RUNID}" \
    --main "/Users/robertgrzesik/Documents/Development/Strategy Library/tmp/backtest_code/c7c6bbd9-41f7-48c9-8754-3231e354f83b/main.py" \
    --start 2025-01-07 \
    --end 2025-02-07 \
    --copy-artifacts-to "/Users/robertgrzesik/Documents/Development/Strategy Library/logs"
```

Warm proof:
- keep the same `--cache-version`
- change only `--cache-folder` to a new empty folder
- expect near-zero “Submitted to queue” lines

