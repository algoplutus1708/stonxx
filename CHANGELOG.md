# Changelog

## 4.4.29 - 2026-01-06

### Fixed
- Prevent production backtests from OOM-like hard exits (`ERROR_CODE_CRASH`) when refreshing multi-year intraday ThetaData caches by avoiding deep copies during cache load/write and trimming non-option intraday frames in-memory.

## 4.4.28 - 2026-01-05

### Added
- Production backtest runner script (`scripts/run_backtest_prod.py`) plus investigation docs for NVDA/SPX accuracy, parity, and startup latency.

### Fixed
- ThetaData missing-day detection for intraday caches across UTC midnights (prevents “every other trading day missing” forward-fill storms).
- Backtesting: improved intraday fills and cache end handling; deterministic drift ordering for rebalances.

## 4.4.27 - 2026-01-05

### Fixed
- Reduced peak memory usage for ThetaData backtests and tear sheet generation to avoid OOM crashes in production.

## 4.4.26 - 2026-01-05

### Changed
- ThetaData: cache snapshot quotes per session and fetch full-session option quote snapshots to reduce downloader fanout.

### Fixed
- Clamp future backtest end dates instead of failing.

## 4.4.25 - 2026-01-04

Deploy marker: `b7f83088` ("Deploy 4.4.25")

### Added
- Public documentation page for environment variables (`docsrc/environment_variables.rst`) plus engineering notes (`docs/ENV_VARS.md`).
- Backtest audit telemetry can be preserved in a separate `*_trade_events.csv` artifact (see `LUMIBOT_BACKTEST_AUDIT`).
- Investigation docs for ThetaData corporate actions and performance.

### Changed
- ThetaData option chain defaults are now bounded to reduce cold-cache request fanout (configurable via `THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT*`).

### Fixed
- OptionsHelper delta-to-strike selection fast path to prevent per-strike quote storms (SPX Copy2/Copy3 slowness).
- Prevent backtest tear sheet generation from crashing on degenerate/flat returns (NVDA end-of-run failures).
- Reduce ThetaData corporate action request thrash via memoization/negative caching.
- Normalize ThetaData intraday bars for corporate actions in backtests so option strikes and underlying prices stay in the same split-adjusted space (NVDA split issues).
- Improve ThetaData snapshot quote selection near the session open to avoid missing NBBO due to end-of-minute timestamps.

## 4.3.6 - 2024-11-16

- Fixed ThetaData EOD corrections by fetching a real 09:30–09:31 minute window for each trading day, preventing zero-length requests and the resulting terminal hangs.
- Logged the active downloader base URL whenever remote mode is enabled to make it obvious in backtest logs which data path is being used.
- Added regression tests covering the custom session window override plus the fallback path when Theta rejects an invalid minute range.
