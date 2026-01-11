# Changelog

## 4.4.33 - Unreleased

### Fixed
- SMART_LIMIT (live): avoid scanning full tracked order history in the background loop by using the broker’s active-order fast path, preventing high RSS growth in accounts with large historical order lists.

## 4.4.32 - 2026-01-10

### Added
- Runtime telemetry: lightweight memory/health JSON lines (`LUMIBOT_TELEMETRY ...`) for diagnosing OOMs in long-running live workers.
- Broker API smoke apitests: basic Alpaca and Tradier connectivity + order lifecycle checks (paper/live as available).

### Fixed
- Live (Tradier): treat `submitted/open/new` as equivalent to reduce repeated NEW events under polling; bound live trade-event history to avoid unbounded memory growth in long-running workers.
- Live (Tradier): avoid heavy DataFrame copy chains when cleaning orders; skip ingesting large historical *closed* order lists on the first poll to prevent startup memory spikes in accounts with long histories.

## 4.4.31 - 2026-01-09

Deploy marker: `d5c6b730` ("deploy 4.4.31")

### Added
- SMART_LIMIT: live matrix apitests + runner scripts; expanded unit coverage for edge cases.
- Investigations/docs: production endpoint breakdown notes and an expanded backtesting performance playbook.
- ThetaData: per-asset download progress reporting for option-chain strike scans (exposed via `download_status`).

### Changed
- Acceptance backtests now run in CI (no longer marked `apitest`); baselines were refreshed for LEAPS + MELI; CI caps were raised for long full-year strategies due to runner variability.
- CI policy: use pytest markers (not env vars) for opt-in/slow tests; some slow ThetaData backtest tests were made opt-in, then re-enabled once bounded.
- Backtests under pytest no longer auto-open HTML artifacts (plots/indicators/tearsheets) in a browser.
- Strategy collaboration workflow: clarified “shared version branch” conventions.

### Fixed
- ThetaData: reduced option-chain fanout and improved warm-cache parity (reuse chain cache under constraints; prefetch strikes only for head+tail expirations when unconstrained; bounded intraday chain defaults).
- ThetaData: improved intraday cache coverage and corrected daily option MTM behavior.
- Polygon: reduced split-cache rate limit thrash.
- SMART_LIMIT: hardened behavior for quote/stream failures.
- Backtesting progress: improved per-asset `download_status` for clearer “what is downloading” diagnostics.

### Removed
- ⚠️ Removed ThetaData chain default-horizon env vars (`THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT*`). Chain default horizons are now fixed and covered by tests.
- Removed the short-lived `LUMIBOT_DISABLE_UI` env var (use `SHOW_PLOT/SHOW_INDICATORS/SHOW_TEARSHEET` + pytest non-interactive behavior instead).

## 4.4.30 - 2026-01-06

Version bump marker: `76b31467` ("Docs/tests: normalize artifacts + bump version")

### Added
- Backtesting performance playbook and production/local parity notes.
- `LUMIBOT_DISABLE_DOTENV` to disable recursive `.env` scanning in prod-like runs.

### Fixed
- ThetaData: filtered intraday parquet loads to reduce memory footprint; daily option MTM fixes.

## 4.4.29 - 2026-01-06

Deploy marker: `b8c6a839` ("deploy 4.4.29")

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
