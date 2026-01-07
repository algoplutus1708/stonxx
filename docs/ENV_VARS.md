# Environment Variables (Engineering Notes)

This page documents environment variables used by LumiBot, with an emphasis on **backtesting** and **ThetaData / downloader / caching** behavior.

**Public docs (source of truth):** the Sphinx page at `docsrc/environment_variables.rst` must be updated whenever env var behavior changes.

## Rules

- **Never commit secrets.** Document variable *names*, accepted values, and semantics—never real API keys, tokens, passwords, or AWS secrets.
- **Env var changes require docs changes.** If you add/change an env var, update:
  - `docsrc/environment_variables.rst` (public docs), and
  - this file (engineering notes) when it helps contributors.

## Backtesting selection + dates

### `IS_BACKTESTING`
- Purpose: Signals backtesting mode for certain code paths.
- Values: `True` / `False` (string).

### `BACKTESTING_START` / `BACKTESTING_END`
- Purpose: Default date range used by `Strategy.run_backtest()` / `Strategy.backtest()` when dates are not passed in code.
- Format: `YYYY-MM-DD`

### `BACKTESTING_DATA_SOURCE`
- Purpose: Selects the backtesting datasource **even if code passes an explicit `datasource_class`**.
- Values (case-insensitive):
  - `thetadata`, `yahoo`, `polygon`, `alpaca`, `ccxt`, `databento`
  - `none` to disable env override and rely on code.
- Where: `lumibot/strategies/_strategy.py` datasource selection logic.

## Backtest output + UX flags

### `SHOW_PLOT`, `SHOW_INDICATORS`, `SHOW_TEARSHEET`
- Purpose: Enables/disables artifact generation.
- Values: `True` / `False` (string).

### `BACKTESTING_QUIET_LOGS`
- Purpose: Reduce log noise during backtests.
- Values: `true` / `false` (string).

### `BACKTESTING_SHOW_PROGRESS_BAR`
- Purpose: Enable progress bar updates.
- Values: `true` / `false` (string).

## Backtest progress file (BotSpot/BotManager UI)

### `LOG_BACKTEST_PROGRESS_TO_FILE`
- Purpose: When truthy, write `logs/progress.csv` during backtests so BotManager/BotSpot can show live progress.
- Values: truthy enables (`1`, `true`, `yes`); unset/`0` disables.
- Notes:
  - On startup, LumiBot writes an initial `progress.csv` row immediately to reduce “time-to-first-progress” latency for short backtests.
  - In BotManager, a background thread watches `/app/logs/*progress.csv` and uploads the most recent row to DynamoDB.
- Where: `lumibot/data_sources/data_source_backtesting.py`

### `BACKTESTING_PROGRESS_HEARTBEAT`
- Purpose: Enable periodic `progress.csv` updates while a ThetaData download is active (prevents the UI appearing stuck when simulation datetime is not advancing).
- Values: `true` / `false` (string).
- Default: enabled (`true`).
- Where: `lumibot/data_sources/data_source_backtesting.py`

### `BACKTESTING_PROGRESS_HEARTBEAT_SECONDS`
- Purpose: Heartbeat interval (seconds) for writing `progress.csv` while downloading.
- Values: float seconds (string).
- Default: `2.0`
- Where: `lumibot/data_sources/data_source_backtesting.py`

## Trade audit telemetry (NVDA/SPX accuracy audits)

### `LUMIBOT_BACKTEST_AUDIT`
- Purpose: Emit **per-fill audit telemetry** into the trades/event CSV as `audit.*` columns.
- Values: `1` enables (anything truthy); unset/`0` disables.
- Output:
  - `*_trade_events.csv` (full trade-event export) contains additional `audit.*` columns.
  - Includes quote/bid/ask snapshots (asset + underlying for options), bar OHLC, SMART_LIMIT inputs, and multileg linkage.
- Where:
  - Audit collection: `lumibot/backtesting/backtesting_broker.py`
  - Audit column emission: `lumibot/brokers/broker.py`
  - Trade-event file routing: `lumibot/strategies/_strategy.py` (exports `*_trade_events.csv`; the plotter writes a simplified `*_trades.csv` for UI/quick review).

## Profiling (parity + performance investigations)

### `BACKTESTING_PROFILE`
- Purpose: Enable profiling during backtests to attribute time (S3 IO vs compute vs artifacts).
- Values:
  - `yappi` (supported)
- Output: produces a `*_profile_yappi.csv` artifact alongside other backtest artifacts.
- Related tooling: `scripts/analyze_yappi_csv.py`

## Remote downloader (ThetaData via shared service)

### `DATADOWNLOADER_BASE_URL`
- Purpose: Points LumiBot at the remote downloader service.
- Example: `http://data-downloader.lumiwealth.com:8080`

### `DATADOWNLOADER_API_KEY` / `DATADOWNLOADER_API_KEY_HEADER`
- Purpose: Authentication for the downloader service.
- Values: **do not document actual values**; they must be supplied by the runtime environment.

### `DATADOWNLOADER_SKIP_LOCAL_START`
- Purpose: Prevents any local downloader/ThetaTerminal bootstrap logic from running (backtests must use the remote downloader in production workflows).

## ThetaData option chain building (performance)

These env vars are used by the ThetaData chain cache/builder in `lumibot/tools/thetadata_helper.py`.

### `THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT`
- Purpose: Bounds the default option-chain expiration window for equity underlyings to reduce strike-list fanout in cold caches/backtests.
- Values: integer days.
- Default: `730` (2 years).
- Notes: set to `0` to disable the default bound (fetch all expirations).

### `THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT_INDEX`
- Purpose: Same as `THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT`, but for index-like underlyings (SPX/NDX/VIX/etc) with dense expiration schedules.
- Values: integer days.
- Default: `180`.
- Notes: set to `0` to disable the default bound.

### `THETADATA_CHAIN_RECENT_FILE_TOLERANCE_DAYS`
- Purpose: Local chain cache file reuse window (equities) when no chain hints are in effect.
- Values: integer days.
- Default: `7`.

### `THETADATA_CHAIN_STRIKES_TIMEOUT`
- Purpose: Downloader wait timeout per strike-list request when building chains.
- Values: seconds (float).
- Default: `300`.

### `THETADATA_CHAIN_STRIKES_BATCH_SIZE`
- Purpose: Number of in-flight strike-list requests when building chains.
- Values: integer.
- Default: `0` (use queue client concurrency).

## ThetaData corporate action normalization (accuracy)

### `THETADATA_APPLY_CORPORATE_ACTIONS_INTRADAY`
- Purpose: Apply split/dividend adjustments to **intraday** frames (minute/second/hour) in backtests so:
  - intraday stock OHLC/quotes match **daily** split-adjusted prices, and
  - option-chain strike normalization (which uses split-adjusted daily reference prices) stays consistent.
- Values: truthy enables (`1`, `true`, `yes`); falsy disables (`0`, `false`).
- Default:
  - enabled when `IS_BACKTESTING` is truthy
  - disabled otherwise
- Pitfall: disabling can break options strike selection around splits (example: NVDA 2024-06-10 10:1 split).
- Where: `lumibot/tools/thetadata_helper.py` (`get_price_data`)

## Remote cache (S3)

### `LUMIBOT_CACHE_BACKEND` / `LUMIBOT_CACHE_MODE`
- Purpose: Enable remote cache mirroring.
- Common values:
  - `LUMIBOT_CACHE_BACKEND=s3`
  - `LUMIBOT_CACHE_MODE=readwrite` (or `readonly`)

### `LUMIBOT_CACHE_FOLDER`
- Purpose: Override the local cache folder (useful to simulate a fresh ECS task).
- Notes: This is read at import/startup time; changing it mid-run will not relocate already-created paths.

### `LUMIBOT_CACHE_S3_BUCKET`, `LUMIBOT_CACHE_S3_PREFIX`, `LUMIBOT_CACHE_S3_REGION`
- Purpose: S3 target configuration.

### `LUMIBOT_CACHE_S3_VERSION`
- Purpose: Namespace/version the remote cache without deleting anything.
- Practical use: set a unique version to simulate a “cold S3” run safely.

### `LUMIBOT_CACHE_S3_ACCESS_KEY_ID`, `LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY`, `LUMIBOT_CACHE_S3_SESSION_TOKEN`
- Purpose: Credentials for S3 access when not using an instance/task role.
- Values: **never commit**.

For cache key layout and validation workflow, see `docs/remote_cache.md`.
