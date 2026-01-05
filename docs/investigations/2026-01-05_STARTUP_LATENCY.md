# Backtest Startup Latency (Submit → First Progress) — 2026-01-05
> Measured breakdown of “nothing happens for ~20–30s” in BotSpot backtests and the fix to reduce it.

**Last Updated:** 2026-01-05  
**Status:** Active  
**Audience:** Developers + AI Agents  

---

## What “startup latency” means here

For BotSpot users, the backtest “starts” when the UI receives the first `backtest_progress` row (from BotManager).

BotManager computes `backtest_progress` by tailing `logs/progress.csv` inside the backtest container and uploading the most recent row to DynamoDB.

So the practical metric is:

- **submit time** (API accepted) → **first progress row timestamp**

---

## Measurements (production, warm S3)

All runs below used warm S3 versions (no cold-cache hydration) and were launched via:

- `scripts/run_backtest_prod.py`

### NVDA (2025-01-20 → 2025-02-10)

- Bot ID: `nvda_prod_parity_warm-20250120-20250210-fku3p0ge`
- Submit: `2026-01-05T13:13:35.509300Z`
- First progress row:
  - `timestamp=2026-01-05T13:13:56.919559`
  - `elapsed=0:00:07`
- **Submit → first progress: ~21.4s**

ECS task timing (from `aws ecs describe-tasks`, task `ef1539da...`):
- `createdAt=2026-01-05T13:13:36.843Z`
- `startedAt=2026-01-05T13:13:37.839Z`
- `pullStoppedAt=2026-01-05T13:13:38.298Z`

Bootstrap timing (from `/api/logs` CloudWatch events):
- `Executing user code` at `2026-01-05T13:13:44.289Z`
- **User code → first progress: ~12.6s**

### SPX Copy2 (2025-01-21 → 2025-01-24)

- Bot ID: `spx_copy2_prod_parity_warm-20250121-20250124-5y3rzoih`
- Submit: `2026-01-05T13:14:34.203320Z`
- First progress row:
  - `timestamp=2026-01-05T13:15:05.518920`
  - `elapsed=0:00:17`
- **Submit → first progress: ~31.3s**

ECS task timing (task `b561b2a1...`):
- `createdAt=2026-01-05T13:14:35.418Z`
- `pullStoppedAt=2026-01-05T13:14:36.547Z`

Bootstrap timing:
- `Executing user code` at `2026-01-05T13:14:42.788Z`
- **User code → first progress: ~22.7s**

### SPX Copy3 (2025-01-21 → 2025-01-24)

- Bot ID: `spx_copy3_prod_parity_warm-20250121-20250124-msb86jww`
- Submit: `2026-01-05T13:15:32.516020Z`
- First progress row:
  - `timestamp=2026-01-05T13:16:06.470323`
  - `elapsed=0:00:20`
- **Submit → first progress: ~34.0s**

ECS task timing (task `17103c8a...`):
- `createdAt=2026-01-05T13:15:33.355Z`
- `pullStoppedAt=2026-01-05T13:15:34.881Z`

Bootstrap timing:
- `Executing user code` at `2026-01-05T13:15:40.945Z`
- **User code → first progress: ~25.5s**

---

## Conclusion (root cause bucket)

For these warm-cache runs:

- ECS scheduling + image pull is **not** the dominant factor (task starts in ~1–2s, pull is ~0.05s).
- BotManager bootstrap overhead is ~8–9s (time from submit to “Executing user code”).
- The remaining 12–25s is inside LumiBot before it creates `logs/progress.csv` and/or advances enough to write the first row.

This is why fast backtests “feel slow”: the simulation is running, but **the UI has no progress row yet**.

---

## Fix (LumiBot): write an initial `progress.csv` row immediately

Change:
- In `lumibot/data_sources/data_source_backtesting.py`, when `LOG_BACKTEST_PROGRESS_TO_FILE` is truthy:
  - write an initial `logs/progress.csv` row immediately on datasource initialization
  - keep the existing download heartbeat behavior unchanged

Why it helps:
- BotManager will upload a progress record almost immediately (next 1s poll), cutting time-to-first-progress for short runs.

Follow-ups (optional):
- If we want even earlier progress (before datasource init), we can add a similar “progress bootstrap row” in:
  - strategy executor startup, or
  - BotSpot Node’s injected log patch (runs before importing LumiBot)

