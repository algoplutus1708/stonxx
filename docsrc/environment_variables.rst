.. _environment_variables:

Environment Variables
=====================

LumiBot supports configuring many behaviors via environment variables. This page documents the variables most commonly used for **backtesting**, **ThetaData**, and **remote caching**.

.. important::

   **Never commit secrets** (API keys, passwords, AWS secret keys) into any repo or docs. Document variable names and semantics only.

Backtesting configuration
------------------------

IS_BACKTESTING
^^^^^^^^^^^^^^

- Purpose: Signals backtesting mode for certain code paths.
- Values: ``True`` / ``False`` (string).

BACKTESTING_START / BACKTESTING_END
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Default date range used when dates are not passed in code.
- Format: ``YYYY-MM-DD``

BACKTESTING_DATA_SOURCE
^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Select the backtesting datasource **even if your code passes a `datasource_class`**.
- Values (case-insensitive):
  - ``thetadata``, ``yahoo``, ``polygon``, ``alpaca``, ``ccxt``, ``databento``
  - ``none`` to disable the env override and rely on code.

Backtest artifacts + UX flags
-----------------------------

SHOW_PLOT / SHOW_INDICATORS / SHOW_TEARSHEET
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Enable/disable artifact generation.
- Values: ``True`` / ``False`` (string).

BACKTESTING_QUIET_LOGS
^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Reduce log noise during backtests.
- Values: ``true`` / ``false`` (string).

BACKTESTING_SHOW_PROGRESS_BAR
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Enable progress bar updates.
- Values: ``true`` / ``false`` (string).

Trade audit telemetry (accuracy investigations)
-----------------------------------------------

LUMIBOT_BACKTEST_AUDIT
^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Emit **per-fill audit telemetry** into the trade-event CSV as ``audit.*`` columns.
- Values: ``1`` enables (any truthy value); unset/``0`` disables.
- Output:
  - Writes a full trade-event export ``*_trade_events.csv`` with ``audit.*`` columns (for example, quote bid/ask snapshots, bar OHLC, SMART_LIMIT inputs, and multileg linkage).
- Notes:
  - This increases CSV width and can add overhead; keep it enabled only when you need a full audit trail.

Profiling (performance + parity investigations)
------------------------------------------------

BACKTESTING_PROFILE
^^^^^^^^^^^^^^^^^^^

- Purpose: Enable profiling during backtests to attribute runtime (S3 IO vs compute vs artifacts).
- Values:
  - ``yappi`` (supported)
- Output:
  - Produces a ``*_profile_yappi.csv`` artifact alongside other backtest artifacts.

ThetaData via remote downloader
-------------------------------

DATADOWNLOADER_BASE_URL
^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Points LumiBot at a remote downloader service that can fetch ThetaData on demand.
- Example: ``http://data-downloader.lumiwealth.com:8080``

DATADOWNLOADER_API_KEY / DATADOWNLOADER_API_KEY_HEADER
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Authentication for the downloader service.
- Values: provided by your runtime environment (**do not hardcode**).

DATADOWNLOADER_SKIP_LOCAL_START
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Prevent any local downloader/ThetaTerminal bootstrap logic from running (production backtests must use the remote downloader).
- Values: ``1`` / ``true`` enable; unset/``0`` disable.

ThetaData option-chain building (performance)
--------------------------------------------

THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Bounds the default option-chain expiration window for equity underlyings to reduce strike-list fanout in cold caches/backtests.
- Values: integer days.
- Default: ``730`` (2 years).
- Notes: set to ``0`` to disable the default bound (fetch all expirations).

THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT_INDEX
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Same as ``THETADATA_CHAIN_DEFAULT_MAX_DAYS_OUT``, but for index-like underlyings (SPX/NDX/VIX/etc) with dense expiration schedules.
- Values: integer days.
- Default: ``180``.
- Notes: set to ``0`` to disable the default bound.

THETADATA_CHAIN_RECENT_FILE_TOLERANCE_DAYS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Local chain cache file reuse window (equities) when no chain hints are in effect.
- Values: integer days.
- Default: ``7``.

THETADATA_CHAIN_STRIKES_TIMEOUT
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Downloader wait timeout per strike-list request when building chains.
- Values: seconds (float).
- Default: ``300``.

THETADATA_CHAIN_STRIKES_BATCH_SIZE
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Number of in-flight strike-list requests when building chains.
- Values: integer.
- Default: ``0`` (use queue client concurrency).

ThetaData corporate action normalization (accuracy)
--------------------------------------------------

THETADATA_APPLY_CORPORATE_ACTIONS_INTRADAY
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Apply split/dividend adjustments to **intraday** frames (minute/second/hour) in backtests so intraday prices match daily split-adjusted prices and option-chain strike normalization stays consistent.
- Values: ``1`` / ``true`` enable; ``0`` / ``false`` disable.
- Default:
  - enabled when ``IS_BACKTESTING`` is truthy
  - disabled otherwise
- Notes:
  - Disabling can break options strike selection around splits (example: NVDA 10-for-1 split on 2024-06-10).

Remote cache (S3)
-----------------

LUMIBOT_CACHE_BACKEND / LUMIBOT_CACHE_MODE
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Enable remote cache mirroring (for example, mirroring parquet cache files to S3).
- Common values:
  - ``LUMIBOT_CACHE_BACKEND=s3``
  - ``LUMIBOT_CACHE_MODE=readwrite`` (or ``readonly``)

LUMIBOT_CACHE_FOLDER
^^^^^^^^^^^^^^^^^^^^

- Purpose: Override the local cache folder (useful to simulate a fresh container/task).

LUMIBOT_CACHE_S3_BUCKET / LUMIBOT_CACHE_S3_PREFIX / LUMIBOT_CACHE_S3_REGION
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: S3 target configuration.

LUMIBOT_CACHE_S3_VERSION
^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Namespace/version the remote cache without deleting anything.
- Practical use: set a unique version to simulate a “cold S3” run safely.

LUMIBOT_CACHE_S3_ACCESS_KEY_ID / LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY / LUMIBOT_CACHE_S3_SESSION_TOKEN
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- Purpose: Credentials for S3 access when not using an instance/task role.
- Values: provided by your runtime environment (**do not hardcode**).

For cache key layout and validation workflow, see :doc:`Backtesting <backtesting>` and the engineering notes in ``docs/remote_cache.md``.
