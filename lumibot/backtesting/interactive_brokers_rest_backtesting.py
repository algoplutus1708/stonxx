import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from lumibot.data_sources import PandasData
from lumibot.entities import Asset, Data
import lumibot.tools.ibkr_helper as ibkr_helper
from lumibot.tools.thetadata_queue_client import set_queue_client_id

logger = logging.getLogger(__name__)


class InteractiveBrokersRESTBacktesting(PandasData):
    """Backtesting data source that fetches historical data from IBKR via the Data Downloader.

    IMPORTANT:
    - Uses the Client Portal Gateway (REST) style via the shared Data Downloader.
    - Implements local parquet caching under `LUMIBOT_CACHE_FOLDER/ibkr/...` with optional S3 mirroring.
    - Focuses on 1-minute+ bars (seconds are intentionally out of scope for now).
    """

    MIN_TIMESTEP = "minute"
    ALLOW_DAILY_TIMESTEP = True
    SOURCE = "InteractiveBrokersREST"

    def __init__(
        self,
        datetime_start: datetime,
        datetime_end: datetime,
        pandas_data=None,
        *,
        exchange: Optional[str] = None,
        history_source: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(datetime_start=datetime_start, datetime_end=datetime_end, pandas_data=pandas_data, **kwargs)
        self._timestep = self.MIN_TIMESTEP
        self.exchange = exchange
        self.history_source = history_source

        unique_id = uuid.uuid4().hex[:8]
        strategy_name = kwargs.get("name", "Backtest")
        client_id = f"{strategy_name}_{unique_id}"
        set_queue_client_id(client_id)
        logger.info("[IBKR][QUEUE] Set client_id for queue fairness: %s", client_id)

        # Set data_source to self since this class acts as its own DataSource.
        self.data_source = self
        # Track which (asset, quote, timestep) series have been fully loaded for the backtest window.
        # Without this, PandasData's default behavior can end up seeding only a couple of bars
        # (e.g., `length=2` in strategy code) and then portfolio mark-to-market gets "stuck"
        # forward-filling the last available price for the rest of the run.
        self._fully_loaded_series: set[tuple] = set()

    def _build_dataset_keys(self, asset: Asset, quote: Optional[Asset], ts_unit: str) -> tuple[tuple, tuple]:
        quote_asset = quote if quote is not None else Asset("USD", "forex")
        canonical_key = (asset, quote_asset, ts_unit)
        legacy_key = (asset, quote_asset)
        return canonical_key, legacy_key

    @staticmethod
    def _previous_us_futures_session_open(dt_value: datetime) -> Optional[datetime]:
        """Return the most recent `us_futures` session open at or before `dt_value`.

        Futures backtests frequently start at midnight timestamps (e.g. Monday 00:00 ET), but the
        `us_futures` session opens the prior day at ~18:00 ET and is closed for long stretches
        (weekends/holidays). Prefetching from a naive `dt_value - 1 day` can land in a closed
        interval and trigger unnecessary (and sometimes flaky) downloader fetch attempts.
        """
        try:
            import pandas_market_calendars as mcal
        except Exception:
            return None

        try:
            ref = pd.Timestamp(dt_value)
            if ref.tzinfo is None:
                ref = ref.tz_localize("UTC")
            ref = ref.tz_convert("UTC")

            cal = mcal.get_calendar("us_futures")
            schedule = cal.schedule(
                start_date=ref.date() - timedelta(days=10),
                end_date=ref.date() + timedelta(days=1),
            )
            if schedule is None or schedule.empty:
                return None

            opens = pd.to_datetime(schedule["market_open"], utc=True, errors="coerce").dropna()
            opens = opens.loc[opens <= ref]
            if opens.empty:
                return None
            return opens.max().to_pydatetime()
        except Exception:
            return None

    def get_last_price(self, asset, quote=None, exchange=None):
        """Return the best available last price for mark-to-market during IBKR backtests.

        For IBKR crypto daily backtests, prefetching the full-minute series for the entire backtest
        window is prohibitively slow (and unnecessary). Prefer the daily series for crypto when
        available, which is derived from intraday history and aligned to LumiBot's day cadence.

        For non-crypto, keep the existing minute-first behavior to preserve prior semantics.
        """
        base_asset = asset
        quote_asset = quote
        if isinstance(base_asset, tuple):
            base_asset, quote_asset = base_asset
        quote_asset = quote_asset if quote_asset is not None else Asset("USD", "forex")

        asset_type = str(getattr(base_asset, "asset_type", "") or "").lower()
        now = self.get_datetime()
        # Futures backtests should not look ahead into the current (incomplete) bar. Interpret
        # "last price at dt" as the last completed bar's close by nudging dt slightly earlier.
        #
        # NOTE: Continuous futures stitching is responsible for ensuring the bar immediately
        # preceding a roll boundary is present (so the last-completed-bar semantics remain valid
        # across contract transitions).
        if asset_type in {"future", "cont_future"}:
            try:
                now = now - timedelta(microseconds=1)
            except Exception:
                pass
        if asset_type == "crypto" and now.hour == 0 and now.minute == 0 and now.second == 0 and now.microsecond == 0:
            day_key = (base_asset, quote_asset, "day")
            if day_key not in self._fully_loaded_series:
                try:
                    self._update_pandas_data(
                        base_asset,
                        quote_asset,
                        "day",
                        start_dt=self.datetime_start - timedelta(days=7),
                        end_dt=self.datetime_end,
                        exchange=self.exchange,
                        include_after_hours=True,
                    )
                except Exception:
                    pass
                self._fully_loaded_series.add(day_key)
            day_data = self._data_store.get(day_key)
            if day_data is not None:
                try:
                    return day_data.get_last_price(now)
                except Exception:
                    pass

        minute_key = (base_asset, quote_asset, "minute")
        if minute_key not in self._fully_loaded_series:
            try:
                self._update_pandas_data(
                    base_asset,
                    quote_asset,
                    "minute",
                    start_dt=self.datetime_start,
                    end_dt=self.datetime_end,
                    exchange=self.exchange,
                    include_after_hours=True,
                )
            except Exception:
                pass
            self._fully_loaded_series.add(minute_key)
        data = self._data_store.get(minute_key)
        if data is not None:
            try:
                return data.get_last_price(now)
            except Exception:
                pass
        return super().get_last_price(asset, quote=quote, exchange=exchange)

    def get_quote(self, asset, quote=None, exchange=None, **kwargs):
        """Return the best available quote snapshot for IBKR backtests.

        Performance trade-off:
        - Daily-cadence crypto strategies frequently execute at midnight timestamps.
        - Fetching 1-minute history just to support quote-based fills can be extremely slow.

        For crypto at midnight, prefer the derived daily series (fast, stable) as the quote
        source; otherwise fall back to PandasData's default minute-based quote path.
        """
        from lumibot.entities import Quote

        base_asset = asset
        quote_asset = quote
        if isinstance(base_asset, tuple):
            base_asset, quote_asset = base_asset
        quote_asset = quote_asset if quote_asset is not None else Asset("USD", "forex")

        asset_type = str(getattr(base_asset, "asset_type", "") or "").lower()
        now = self.get_datetime()
        if asset_type == "crypto" and now.hour == 0 and now.minute == 0 and now.second == 0 and now.microsecond == 0:
            day_key = (base_asset, quote_asset, "day")
            if day_key not in self._fully_loaded_series:
                try:
                    self._update_pandas_data(
                        base_asset,
                        quote_asset,
                        "day",
                        start_dt=self.datetime_start - timedelta(days=7),
                        end_dt=self.datetime_end,
                        exchange=self.exchange,
                        include_after_hours=True,
                    )
                except Exception:
                    pass
                self._fully_loaded_series.add(day_key)

            day_data = self._data_store.get(day_key)
            if day_data is not None:
                try:
                    ohlcv_bid_ask_dict = day_data.get_quote(now)
                    return Quote(
                        asset=base_asset,
                        price=ohlcv_bid_ask_dict.get("close"),
                        bid=ohlcv_bid_ask_dict.get("bid"),
                        ask=ohlcv_bid_ask_dict.get("ask"),
                        volume=ohlcv_bid_ask_dict.get("volume"),
                        timestamp=now,
                        bid_size=ohlcv_bid_ask_dict.get("bid_size"),
                        ask_size=ohlcv_bid_ask_dict.get("ask_size"),
                        raw_data=ohlcv_bid_ask_dict,
                    )
                except Exception:
                    pass

        return super().get_quote(base_asset, quote=quote_asset, exchange=exchange)

    def _update_pandas_data(
        self,
        asset: Asset,
        quote: Optional[Asset],
        timestep: str,
        start_dt: datetime,
        end_dt: datetime,
        *,
        exchange: Optional[str],
        include_after_hours: bool,
    ) -> None:
        canonical_key, legacy_key = self._build_dataset_keys(asset, quote, timestep)
        existing = self._data_store.get(canonical_key)
        existing_df = getattr(existing, "df", None) if existing is not None else None

        df = ibkr_helper.get_price_data(
            asset=asset,
            quote=quote,
            timestep=timestep,
            start_dt=start_dt,
            end_dt=end_dt,
            exchange=exchange,
            include_after_hours=include_after_hours,
            source=self.history_source,
        )

        if df is None or df.empty:
            return

        if existing_df is not None and isinstance(existing_df, pd.DataFrame) and not existing_df.empty:
            merged = pd.concat([existing_df, df], axis=0).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]
        else:
            merged = df

        data = Data(asset, merged, timestep=timestep, quote=quote)
        # CRITICAL: Pandas backtesting expects each Data object to have `iter_index`/datalines
        # built so prices advance as the backtest clock advances. Normally this is done via
        # PandasData.load_data() -> Data.repair_times_and_fill(...), but IBKR loads data lazily.
        #
        # IMPORTANT (data gaps vs synthetic bars):
        # IBKR futures/crypto history can contain *real* timestamp gaps (maintenance windows,
        # holiday early closes, weekend gaps). We must not "repair" those gaps by expanding a
        # minute-by-minute index and forward-filling, because that would create synthetic bars
        # and enable fills at timestamps where the market was closed.
        #
        # See: docs/BACKTESTING_SESSION_GAPS_AND_DATA_GAPS.md
        try:
            if isinstance(merged.index, pd.DatetimeIndex) and len(merged.index) > 0:
                data.repair_times_and_fill(merged.index)
        except Exception:
            # Fallback: if repair fails, leave data as-is (callers will treat as missing).
            pass
        self._data_store[canonical_key] = data
        # Only write the legacy key for minute data to avoid collisions with daily bars.
        if timestep == "minute":
            self._data_store[legacy_key] = data

    def _pull_source_symbol_bars(
        self,
        asset,
        length,
        timestep=None,
        timeshift=None,
        quote=None,
        exchange=None,
        include_after_hours=True,
    ):
        asset_separated = asset
        quote_asset = quote
        if isinstance(asset_separated, tuple):
            asset_separated, quote_asset = asset_separated

        if isinstance(asset_separated, str):
            asset_separated = Asset(symbol=asset_separated)
        if timestep is None:
            timestep = self.get_timestep()

        end_dt = self.get_datetime()
        # IBKR crypto/futures trade outside equity calendars; do not add the default 5-day padding.
        start_dt, ts_unit = self.get_start_datetime_and_ts_unit(
            length, timestep, start_dt=end_dt, start_buffer=timedelta(0)
        )
        ts_unit = str(ts_unit or "").strip().lower()
        asset_type = str(getattr(asset_separated, "asset_type", "") or "").lower()
        if asset_type in {"future", "cont_future"} and ts_unit in {"minute", "hour", "day"}:
            # Futures strategies frequently request very small slices (e.g., `length=2`) at the
            # beginning of the backtest window. If we only fetch the tiny requested slice, IBKR's
            # history endpoint can return slightly-stale bars and leave the Data object underfilled,
            # causing strategies to see "no bars available" and skip trading entirely.
            #
            # Fix: on first access, prefetch the full backtest window for the series and reuse it.
            quote_key = quote_asset if quote_asset is not None else Asset("USD", "forex")
            key = (asset_separated, quote_key, ts_unit)
            if key not in self._fully_loaded_series:
                prev_open = self._previous_us_futures_session_open(self.datetime_start)
                if prev_open is not None:
                    prefetch_start = min(start_dt, prev_open)
                else:
                    prefetch_start = min(start_dt, self.datetime_start - timedelta(days=1))
                prefetch_end = self.datetime_end
                self._update_pandas_data(
                    asset_separated,
                    quote_asset,
                    ts_unit,
                    start_dt=prefetch_start,
                    end_dt=prefetch_end,
                    exchange=exchange or self.exchange,
                    include_after_hours=True,
                )
                self._fully_loaded_series.add(key)
        elif asset_type == "crypto" and ts_unit == "day":
            # Prefetch daily series for the full backtest window on first access so we do not
            # hammer the downloader once per simulated day.
            key = (asset_separated, quote_asset if quote_asset is not None else Asset("USD", "forex"), "day")
            if key not in self._fully_loaded_series:
                prefetch_start = min(start_dt, self.datetime_start - timedelta(days=max(7, int(length) + 5)))
                prefetch_end = self.datetime_end
                self._update_pandas_data(
                    asset_separated,
                    quote_asset,
                    "day",
                    start_dt=prefetch_start,
                    end_dt=prefetch_end,
                    exchange=exchange or self.exchange,
                    include_after_hours=True,
                )
                self._fully_loaded_series.add(key)
        else:
            self._update_pandas_data(
                asset_separated,
                quote_asset,
                timestep,
                start_dt=start_dt,
                end_dt=end_dt,
                exchange=exchange or self.exchange,
                include_after_hours=include_after_hours,
            )
        return super()._pull_source_symbol_bars(
            asset_separated, length, timestep, timeshift, quote_asset, exchange, include_after_hours
        )

    def get_historical_prices_between_dates(
        self,
        asset,
        timestep="minute",
        quote=None,
        exchange=None,
        include_after_hours=True,
        start_date=None,
        end_date=None,
    ):
        asset_separated = asset
        quote_asset = quote
        if isinstance(asset_separated, tuple):
            asset_separated, quote_asset = asset_separated

        if isinstance(asset_separated, str):
            asset_separated = Asset(symbol=asset_separated)
        if start_date is None or end_date is None:
            return None

        self._update_pandas_data(
            asset_separated,
            quote_asset,
            timestep,
            start_dt=start_date,
            end_dt=end_date,
            exchange=exchange or self.exchange,
            include_after_hours=include_after_hours,
        )

        response = super()._pull_source_symbol_bars_between_dates(
            asset_separated, timestep, quote_asset, exchange, include_after_hours, start_date, end_date
        )
        if response is None:
            return None
        return self._parse_source_symbol_bars(response, asset_separated, quote=quote_asset)
