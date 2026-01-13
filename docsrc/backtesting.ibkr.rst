Interactive Brokers (REST) Backtesting
======================================

LumiBot supports backtesting with **Interactive Brokers Client Portal (REST)** via the shared **Data Downloader** service.

This backtesting path does **not** use the legacy TWS API.

Quick Start
-----------

1. Ensure you have access to a Data Downloader deployment that supports IBKR (``/ibkr/...`` routes).
2. Configure the downloader connection:

.. code-block:: bash

   export DATADOWNLOADER_BASE_URL="http://localhost:8080"
   export DATADOWNLOADER_API_KEY="..."

3. Select IBKR for backtesting:

.. code-block:: bash

   export BACKTESTING_DATA_SOURCE="ibkr"

Supported Data
--------------

- **Futures**: contract bars via IBKR historical endpoints (1-minute+ bars).
- **Spot crypto**: IBKR crypto bars (availability depends on region and IBKR product support).

Caching
-------

IBKR backtests cache historical bars as Parquet:

- Local: ``LUMIBOT_CACHE_FOLDER/ibkr/...``
- Optional S3 mirroring: configured via the standard ``LUMIBOT_CACHE_*`` variables (see :ref:`environment_variables`).

Multi-provider routing (Theta + IBKR)
-------------------------------------

To use multiple providers in a single backtest (example: ThetaData for options/stocks/indexes and IBKR for futures/crypto), set a JSON mapping in ``BACKTESTING_DATA_SOURCE``:

.. code-block:: bash

   export BACKTESTING_DATA_SOURCE='{"default":"thetadata","stock":"thetadata","option":"thetadata","index":"thetadata","future":"ibkr","crypto":"ibkr"}'

Routing values are case/whitespace/_/- insensitive. For crypto, you may also route to CCXT by using either ``"ccxt"`` (auto-select exchange) or a CCXT exchange id directly (for example: ``"coinbase"`` or ``"kraken"``).

Market Data Subscriptions (IBKR)
--------------------------------

IBKR requires appropriate **market data entitlements** to access market data via the API. IBKR notes that historical bars are part of Level 1 entitlements and that **crypto does not require additional market data subscriptions**:

- https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/

For **CME futures** (ES/MES/NQ/MNQ), note that the cheap **CME S&P Indices** subscription is for index data, not futures contracts. Professional subscriber pricing and package availability can differ, so confirm your exact costs in the IBKR Market Data Subscriptions page and pricing table:

- https://www.interactivebrokers.com/en/pricing/market-data-pricing.php

Authentication / Session Behavior
---------------------------------

The Client Portal Gateway is session-based; if the session becomes unauthenticated, the gateway must be re-authenticated. IBKR documents the expected authentication lifecycle and recommends using ``/iserver/auth/ssodh/init`` to re-authenticate in most scenarios:

- https://www.interactivebrokers.com/campus/trading-lessons/launching-and-authenticating-the-gateway/
