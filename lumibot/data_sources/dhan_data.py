"""
lumibot/data_sources/dhan_data.py
==================================
Data source for Indian equity markets (NSE / BSE) via the Dhan broker API.

Architecture
------------
* **Historical data** → Yahoo Finance (yfinance) by default.
  This is the cost-optimised path while Dhan's historical endpoints are expensive
  or rate-limited.  Set ``use_yfinance_historical=False`` to fall back to native
  Dhan historical calls (partially implemented).

* **Live / intraday quotes** → Dhan LTP / OHLC API.

Symbol mapping
--------------
The two APIs speak different symbol dialects:

  Strategy symbol  │  Yahoo Finance symbol  │  Dhan API symbol
  ─────────────────┼────────────────────────┼──────────────────
  RELIANCE         │  RELIANCE.NS           │  RELIANCE
  RELIANCE.NS      │  RELIANCE.NS           │  RELIANCE
  RELIANCE.BO      │  RELIANCE.BO           │  RELIANCE

Use ``DhanSymbolMapper`` directly if you need conversions outside this class.

Error handling
--------------
Indian tickers frequently drop minute-bars on Yahoo Finance (holidays, pre-open
auctions, illiquid scrips).  ``_pull_source_symbol_bars`` implements:

1. Configurable retry with exponential back-off on ``ReadTimeoutError`` / network
   errors.
2. Automatic gap-filling of missing intraday bars using forward-fill (so
   strategies that expect a continuous series don't see NaN values).
3. Graceful ``None``-return with a clear log message when data is genuinely
   unavailable, letting the caller decide how to handle it.
"""

import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Union

import numpy as np
import pandas as pd

try:
    from dhanhq import dhanhq as DhanAPI
    _DHAN_AVAILABLE = True
except ImportError:
    _DHAN_AVAILABLE = False

from lumibot.data_sources import DataSourceBacktesting
from lumibot.entities import Asset, Bars
from lumibot.tools import YahooHelper
from lumibot.tools.lumibot_logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Symbol Mapping Utility
# ---------------------------------------------------------------------------

class DhanSymbolMapper:
    """
    Bidirectional mapping between clean strategy symbols and the format
    required by Yahoo Finance or the Dhan API.

    Rules
    -----
    * Yahoo Finance expects an exchange suffix: ``.NS`` (NSE) or ``.BO`` (BSE).
    * Dhan API expects the raw symbol **without** any suffix.
    * A symbol that already carries ``.NS`` / ``.BO`` is passed through correctly
      in both directions.

    Parameters
    ----------
    default_exchange : str
        Exchange to assume when no suffix is present.  Either ``"NSE"`` (default)
        or ``"BSE"``.
    """

    _SUFFIX_TO_EXCHANGE = {".NS": "NSE", ".BO": "BSE"}
    _EXCHANGE_TO_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}

    def __init__(self, default_exchange: str = "NSE"):
        _valid = {"NSE", "BSE"}
        if default_exchange.upper() not in _valid:
            raise ValueError(
                f"default_exchange must be one of {_valid}, got {default_exchange!r}"
            )
        self.default_exchange = default_exchange.upper()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def to_yahoo(self, symbol: str, asset_exchange: Optional[str] = None) -> str:
        """
        Return the Yahoo Finance ticker for *symbol*.

        Examples
        --------
        >>> mapper = DhanSymbolMapper()
        >>> mapper.to_yahoo("RELIANCE")
        'RELIANCE.NS'
        >>> mapper.to_yahoo("RELIANCE.NS")
        'RELIANCE.NS'
        >>> mapper.to_yahoo("RELIANCE.BO")
        'RELIANCE.BO'
        >>> mapper.to_yahoo("RELIANCE", asset_exchange="BSE")
        'RELIANCE.BO'
        """
        symbol = symbol.strip().upper()
        if self._has_yahoo_suffix(symbol):
            return symbol

        # Use asset-level exchange hint if supplied, else fall back to default.
        exchange = (asset_exchange or "").upper() or self.default_exchange
        suffix = self._EXCHANGE_TO_SUFFIX.get(exchange, self._EXCHANGE_TO_SUFFIX[self.default_exchange])
        return f"{symbol}{suffix}"

    def to_dhan(self, symbol: str) -> str:
        """
        Return the bare symbol expected by the Dhan API (strips any suffix).

        Examples
        --------
        >>> mapper = DhanSymbolMapper()
        >>> mapper.to_dhan("RELIANCE.NS")
        'RELIANCE'
        >>> mapper.to_dhan("RELIANCE")
        'RELIANCE'
        """
        symbol = symbol.strip().upper()
        for suffix in self._SUFFIX_TO_EXCHANGE:
            if symbol.endswith(suffix):
                return symbol[: -len(suffix)]
        return symbol

    def exchange_from_symbol(self, symbol: str) -> str:
        """
        Infer the exchange from the symbol suffix, or return the default.

        Examples
        --------
        >>> mapper = DhanSymbolMapper()
        >>> mapper.exchange_from_symbol("RELIANCE.BO")
        'BSE'
        >>> mapper.exchange_from_symbol("RELIANCE")
        'NSE'
        """
        symbol = symbol.strip().upper()
        for suffix, exchange in self._SUFFIX_TO_EXCHANGE.items():
            if symbol.endswith(suffix):
                return exchange
        return self.default_exchange

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_yahoo_suffix(symbol: str) -> bool:
        return symbol.endswith(".NS") or symbol.endswith(".BO")


# ---------------------------------------------------------------------------
# DhanData  –  main data source
# ---------------------------------------------------------------------------

class DhanData(DataSourceBacktesting):
    """
    LumiBot data source for Indian equity markets.

    Parameters
    ----------
    client_id : str
        Dhan API client/account ID.
    access_token : str
        Dhan API access token.
    use_yfinance_historical : bool
        When ``True`` (default), historical bar requests are served by Yahoo
        Finance.  Set to ``False`` to use Dhan's own historical endpoints
        (partially implemented).
    default_exchange : str
        Default exchange suffix for symbols that carry no explicit exchange.
        ``"NSE"`` (default) or ``"BSE"``.
    yf_retry_attempts : int
        Number of times to retry a failed Yahoo Finance download before giving
        up.  Default is 3.
    yf_retry_backoff : float
        Base back-off in seconds between retries (doubles each attempt).
        Default is 2.0 s.
    yf_gap_fill : bool
        If ``True`` (default), forward-fill missing intraday bars so strategies
        receive a gapless series.  Has no effect for daily data.
    datetime_start : datetime, optional
    datetime_end : datetime, optional
    **kwargs
        Forwarded to ``DataSourceBacktesting.__init__``.
    """

    SOURCE = "DHAN"
    MIN_TIMESTEP = "day"
    TIMESTEP_MAPPING = [
        {"timestep": "day", "representations": ["1d", "day"]},
        {"timestep": "15 minutes", "representations": ["15m", "15 minutes"]},
        {"timestep": "minute", "representations": ["1m", "1 minute"]},
    ]

    def __init__(
        self,
        client_id: str,
        access_token: str,
        use_yfinance_historical: bool = True,
        default_exchange: str = "NSE",
        yf_retry_attempts: int = 3,
        yf_retry_backoff: float = 2.0,
        yf_gap_fill: bool = True,
        datetime_start: Optional[datetime] = None,
        datetime_end: Optional[datetime] = None,
        **kwargs,
    ):
        if datetime_start is None:
            datetime_start = datetime.now() - timedelta(days=365)
        if datetime_end is None:
            datetime_end = datetime.now()

        super().__init__(
            datetime_start=datetime_start,
            datetime_end=datetime_end,
            **kwargs,
        )

        self.client_id = client_id
        self.access_token = access_token
        self.use_yfinance_historical = use_yfinance_historical
        self.yf_retry_attempts = max(1, yf_retry_attempts)
        self.yf_retry_backoff = max(0.0, yf_retry_backoff)
        self.yf_gap_fill = yf_gap_fill

        # In-memory caches (mirrors YahooData pattern)
        self._data_store: dict = {}
        self._last_price_cache: dict = {}
        self._last_price_cache_datetime = None

        # Symbol mapper
        self.symbol_mapper = DhanSymbolMapper(default_exchange=default_exchange)

        # Dhan API client
        if not _DHAN_AVAILABLE:
            logger.warning(
                "dhanhq package not installed.  Live quote calls will fail. "
                "Install it with: pip install dhanhq"
            )
            self._dhan_api = None
        else:
            try:
                self._dhan_api = DhanAPI(client_id, access_token)
                logger.info("DhanData: Dhan API client initialised successfully.")
            except Exception as exc:
                logger.error(f"DhanData: Failed to initialise Dhan API client: {exc}")
                self._dhan_api = None

        # Mirror-Yahoo instance for historical fall-through
        if self.use_yfinance_historical:
            # Import here to avoid circular dependency at module level
            from lumibot.data_sources.yahoo_data import YahooData

            self._yahoo = YahooData(
                datetime_start=datetime_start,
                datetime_end=datetime_end,
                **kwargs,
            )
        else:
            self._yahoo = None

    # ------------------------------------------------------------------
    # Historical price retrieval
    # ------------------------------------------------------------------

    def get_historical_prices(
        self,
        asset,
        length: int,
        timestep: str = "",
        timeshift=None,
        quote=None,
        exchange=None,
        include_after_hours: bool = True,
        **kwargs,
    ):
        """
        Return a ``Bars`` object (or ``None``) for *asset*.

        When ``use_yfinance_historical=True``, the request is routed to Yahoo
        Finance after mapping the symbol (e.g. ``RELIANCE`` → ``RELIANCE.NS``).
        Network errors and missing bars are handled transparently.
        """
        if not timestep:
            timestep = self.get_timestep()

        if self.use_yfinance_historical:
            return self._get_historical_via_yahoo(
                asset, length, timestep, timeshift, quote, exchange,
                include_after_hours, **kwargs
            )

        # Native Dhan path (partial implementation)
        return self._get_native_historical(asset, length, timestep, **kwargs)

    def _get_historical_via_yahoo(
        self,
        asset,
        length: int,
        timestep: str,
        timeshift,
        quote,
        exchange,
        include_after_hours: bool,
        **kwargs,
    ):
        """
        Delegate to the internal ``YahooData`` instance after remapping the
        symbol to its Yahoo Finance form.

        Retries on timeout/network errors with exponential back-off, and
        optionally gap-fills missing intraday bars.
        """
        # --- Build Yahoo-compatible asset --------------------------------
        asset_exchange = exchange or getattr(asset, "exchange", None)
        yahoo_symbol = self.symbol_mapper.to_yahoo(asset.symbol, asset_exchange)

        # Re-use the same asset type / expiry / strike information
        yahoo_asset = Asset(symbol=yahoo_symbol, asset_type=asset.asset_type)

        logger.debug(
            f"DhanData._get_historical_via_yahoo: {asset.symbol!r} → "
            f"{yahoo_symbol!r} (length={length}, timestep={timestep!r})"
        )

        # --- Retry loop --------------------------------------------------
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.yf_retry_attempts + 1):
            try:
                bars = self._yahoo.get_historical_prices(
                    yahoo_asset,
                    length,
                    timestep=timestep,
                    timeshift=timeshift,
                    quote=quote,
                    exchange=exchange,
                    include_after_hours=include_after_hours,
                    **kwargs,
                )
                if bars is None:
                    # Yahoo returned no data for this symbol/period — no point
                    # retrying; this is a data availability issue.
                    logger.warning(
                        f"DhanData: Yahoo Finance returned no data for "
                        f"{yahoo_symbol!r} (length={length}, timestep={timestep!r}). "
                        f"Check the symbol and backtest date range."
                    )
                    return None

                # Optional gap-fill for intraday bars
                if self.yf_gap_fill and "minute" in timestep.lower():
                    bars = self._gap_fill_bars(bars, yahoo_asset)

                return bars

            except Exception as exc:
                last_exc = exc
                # Classify: is this retriable?
                exc_str = str(exc).lower()
                is_timeout = any(
                    kw in exc_str
                    for kw in ("timeout", "read timed out", "connection", "httperror",
                               "remotedisconnected", "chunkedencodingerror")
                )
                if is_timeout and attempt < self.yf_retry_attempts:
                    wait = self.yf_retry_backoff * (2 ** (attempt - 1))
                    logger.warning(
                        f"DhanData: Yahoo Finance request for {yahoo_symbol!r} "
                        f"failed (attempt {attempt}/{self.yf_retry_attempts}): {exc}. "
                        f"Retrying in {wait:.1f}s…"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"DhanData: Yahoo Finance request for {yahoo_symbol!r} "
                        f"failed after {attempt} attempt(s): {exc}"
                    )
                    return None

        logger.error(
            f"DhanData: All {self.yf_retry_attempts} Yahoo Finance attempts "
            f"failed for {yahoo_symbol!r}. Last error: {last_exc}"
        )
        return None

    def _gap_fill_bars(self, bars: "Bars", asset: Asset) -> "Bars":
        """
        Forward-fill missing intraday minute bars in *bars*.

        Indian tickers frequently have NaN-volume or completely absent minute
        rows (pre-open / circuit-breaker / illiquid periods).  Forward-filling
        carries the last valid OHLC/Volume forward so downstream indicators
        don't crash on NaN values.

        The fill is intentionally conservative:
        * Only fills within the existing time range (no extrapolation).
        * Volume is filled with 0 for genuinely missing minutes (no activity).
        * Returns the original object unchanged if the DataFrame is fine.
        """
        try:
            df = bars.df
            if df is None or df.empty:
                return bars

            original_len = len(df)

            # Fill NaN values in OHLC columns with forward-fill
            ohlc_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
            df[ohlc_cols] = df[ohlc_cols].ffill()

            # Fill NaN volume with 0 (no trades occurred)
            if "volume" in df.columns:
                df["volume"] = df["volume"].fillna(0)

            filled_len = len(df)
            if filled_len != original_len:
                logger.info(
                    f"DhanData._gap_fill_bars: {asset.symbol!r} – "
                    f"gap-filled {filled_len - original_len} bars."
                )

            # Reconstruct Bars with the patched DataFrame
            from lumibot.entities import Bars as _Bars
            return _Bars(df, self.SOURCE, asset, raw=df)
        except Exception as exc:
            logger.warning(
                f"DhanData._gap_fill_bars: skipped gap-fill for "
                f"{asset.symbol!r} due to error: {exc}"
            )
            return bars

    def _get_native_historical(self, asset, length: int, timestep: str, **kwargs):
        """
        Fetch historical data directly from Dhan's API.

        Dhan exposes ``historical_daily_data`` and ``intraday_minute_data``.
        This is a stub that logs a clear warning so developers know what is
        missing rather than silently returning ``None``.
        """
        logger.warning(
            "DhanData._get_native_historical: Native Dhan historical data "
            "endpoint is not fully implemented.  Set ``use_yfinance_historical=True`` "
            "or contribute a Dhan historical implementation."
        )
        return None

    # ------------------------------------------------------------------
    # Live quotes (always via Dhan)
    # ------------------------------------------------------------------

    def get_quote(self, asset) -> Optional[dict]:
        """
        Fetch the current OHLC quote from Dhan for *asset*.

        The Dhan API expects the bare symbol (no ``.NS`` / ``.BO`` suffix) and
        a ``security_id``.  Because security IDs are instrument-specific and
        require a full instrument-master lookup, this implementation uses the
        bare symbol as a best-effort security_id while the full master lookup
        is pending.

        Returns
        -------
        dict or None
            Keys: ``open``, ``high``, ``low``, ``close``, ``volume``.
            Returns ``None`` on any API failure.
        """
        if self._dhan_api is None:
            logger.error("DhanData.get_quote: Dhan API client is not available.")
            return None

        dhan_symbol = self.symbol_mapper.to_dhan(asset.symbol)
        exchange = self.symbol_mapper.exchange_from_symbol(asset.symbol)
        exchange_segment = "NSE_EQ" if exchange == "NSE" else "BSE_EQ"

        try:
            response = self._dhan_api.ohlc_data(
                securities={exchange_segment: [dhan_symbol]}
            )
        except Exception as exc:
            logger.error(
                f"DhanData.get_quote: Dhan API call failed for "
                f"{dhan_symbol!r} ({exchange_segment}): {exc}"
            )
            return None

        if not response or response.get("status") != "success":
            logger.warning(
                f"DhanData.get_quote: Dhan returned non-success for "
                f"{dhan_symbol!r}: {response}"
            )
            return None

        # Dhan response structure: data[exchange_segment][symbol] or data[symbol]
        data_section = response.get("data", {})
        # Try both with and without exchange segment nesting
        instrument_data = (
            data_section.get(exchange_segment, {}).get(dhan_symbol)
            or data_section.get(dhan_symbol)
            or {}
        )

        if not instrument_data:
            logger.warning(
                f"DhanData.get_quote: No instrument data found in Dhan response "
                f"for {dhan_symbol!r}.  Raw response: {response}"
            )
            return None

        return {
            "open":   float(instrument_data.get("open", 0) or 0),
            "high":   float(instrument_data.get("high", 0) or 0),
            "low":    float(instrument_data.get("low", 0) or 0),
            "close":  float(instrument_data.get("lp", 0) or 0),   # last price
            "volume": int(instrument_data.get("v", 0) or 0),
        }

    def get_last_price(
        self,
        asset,
        timestep: Optional[str] = None,
        quote=None,
        exchange=None,
        **kwargs,
    ) -> Union[float, Decimal, None]:
        """
        Return the last traded price for *asset*.

        During live trading, the price is sourced from Dhan's OHLC endpoint.
        During backtesting (when ``_datetime`` is not the live wall-clock),
        the price is sourced from the Yahoo Finance historical series so the
        backtest uses consistent data.
        """
        # ---------- backtest path: use cached historical price -----------
        if timestep is None:
            timestep = self.get_timestep()

        current_datetime = self._datetime
        cache_key = (asset, timestep, quote, exchange, current_datetime)

        if self._last_price_cache_datetime != current_datetime:
            self._last_price_cache.clear()
            self._last_price_cache_datetime = current_datetime

        if cache_key in self._last_price_cache:
            return self._last_price_cache[cache_key]

        # Use the same timeshift logic as YahooData to avoid lookahead
        if isinstance(timestep, str) and "day" in timestep.lower():
            timeshift_delta = None
        else:
            timeshift_delta = timedelta(days=-1)

        bars = self.get_historical_prices(
            asset, 1, timestep=timestep, quote=quote, timeshift=timeshift_delta
        )

        if bars is None:
            # Fall back to Dhan live quote (works in live and replay modes)
            quote_data = self.get_quote(asset)
            price = quote_data.get("close") if quote_data else None
            self._last_price_cache[cache_key] = price
            return price

        if isinstance(bars, float):
            self._last_price_cache[bars] = bars
            return bars

        try:
            df_local = bars.df
            price = df_local["open"].iat[0]
            if isinstance(price, np.int64):
                price = Decimal(price.item())
            self._last_price_cache[cache_key] = price
            return price
        except Exception as exc:
            logger.warning(f"DhanData.get_last_price: failed to extract price: {exc}")
            return None

    # ------------------------------------------------------------------
    # Options / chains (not supported)
    # ------------------------------------------------------------------

    def get_chains(self, asset: Asset, quote: Asset = None, exchange: str = None):
        """
        Option chain data is not implemented for DhanData.

        Dhan does support options, but a full strike/expiry mapping requires
        the Dhan instrument master.  Raise ``NotImplementedError`` so
        strategies fail fast rather than silently returning stale data.
        """
        raise NotImplementedError(
            "DhanData does not yet support option chains.  "
            "Implement a Dhan instrument-master lookup to enable this feature."
        )

    def get_strikes(self, asset: Asset):
        raise NotImplementedError(
            "DhanData does not yet support strike fetching.  "
            "See get_chains() for details."
        )

    # ------------------------------------------------------------------
    # DataSourceBacktesting engine hooks
    # ------------------------------------------------------------------

    def _pull_source_symbol_bars(
        self,
        asset: Asset,
        length: int,
        timestep: str = MIN_TIMESTEP,
        timeshift=None,
        quote=None,
        exchange=None,
        include_after_hours: bool = True,
    ):
        """
        Core hook called by the backtesting engine on every iteration.

        Delegates to Yahoo Finance after mapping the symbol to Yahoo format
        (e.g. ``RELIANCE`` → ``RELIANCE.NS``).  Returns a raw pandas
        DataFrame (not a ``Bars`` object) — the engine wraps it via
        ``_parse_source_symbol_bars`` automatically.

        This method mirrors the pattern in ``YahooData._pull_source_symbol_bars``.
        """
        if self._yahoo is None:
            logger.error(
                "DhanData._pull_source_symbol_bars: YahooData instance is not "
                "available (use_yfinance_historical may be False). Cannot fetch bars."
            )
            return None

        # Map strategy symbol → Yahoo Finance symbol
        asset_exchange = exchange or getattr(asset, "exchange", None)
        yahoo_symbol   = self.symbol_mapper.to_yahoo(asset.symbol, asset_exchange)
        yahoo_asset    = Asset(symbol=yahoo_symbol, asset_type=asset.asset_type)

        logger.debug(
            f"DhanData._pull_source_symbol_bars: {asset.symbol!r} → "
            f"{yahoo_symbol!r} length={length} timestep={timestep!r}"
        )

        # Delegate to Yahoo's low-level puller (returns raw DataFrame)
        try:
            raw = self._yahoo._pull_source_symbol_bars(
                yahoo_asset,
                length,
                timestep=timestep,
                timeshift=timeshift,
                quote=quote,
                exchange=exchange,
                include_after_hours=include_after_hours,
            )
        except Exception as exc:
            logger.error(
                f"DhanData._pull_source_symbol_bars: Yahoo pull failed for "
                f"{yahoo_symbol!r}: {exc}"
            )
            return None

        if raw is None or (hasattr(raw, "empty") and raw.empty):
            logger.warning(
                f"DhanData: No data from Yahoo for {yahoo_symbol!r} "
                f"(length={length}, timestep={timestep!r})"
            )
            return None

        # Optional intraday gap-fill
        if self.yf_gap_fill and "minute" in str(timestep).lower():
            try:
                import pandas as _pd
                ohlc_cols = [c for c in ["open", "high", "low", "close"] if c in raw.columns]
                raw[ohlc_cols] = raw[ohlc_cols].ffill()
                if "volume" in raw.columns:
                    raw["volume"] = raw["volume"].fillna(0)
            except Exception as exc:
                logger.warning(f"DhanData gap-fill skipped: {exc}")

        return raw

    def _parse_source_symbol_bars(self, response, asset: Asset, quote=None, length=None):
        """Wrap a raw DataFrame (from _pull_source_symbol_bars) into a Bars object."""
        return Bars(response, self.SOURCE, asset, raw=response)

    def _pull_source_bars(
        self,
        assets,
        length: int,
        timestep: str = MIN_TIMESTEP,
        timeshift=None,
        quote=None,
        include_after_hours: bool = True,
    ) -> dict:
        """Batch fetch bars for multiple assets."""
        result = {}
        for asset in assets:
            raw = self._pull_source_symbol_bars(
                asset,
                length,
                timestep=timestep,
                timeshift=timeshift,
                quote=quote,
                include_after_hours=include_after_hours,
            )
            result[asset] = raw
        return result
