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

    def get_last_price(self, asset, quote=None, exchange=None):
        """Prefer minute bars for IBKR mark-to-market even if daily bars are also cached.

        IBKR backtests can end up caching BOTH minute and daily bars (e.g., for analysis/tearsheet).
        The PandasData legacy key `(asset, quote)` collides across timesteps; if daily overwrites it,
        portfolio valuation can get "stuck" on a single daily close. Avoid that by explicitly
        resolving the minute canonical key first.
        """
        base_asset = asset
        quote_asset = quote
        if isinstance(base_asset, tuple):
            base_asset, quote_asset = base_asset
        quote_asset = quote_asset if quote_asset is not None else Asset("USD", "forex")

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
                return data.get_last_price(self.get_datetime())
            except Exception:
                pass
        return super().get_last_price(asset, quote=quote, exchange=exchange)

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
        # Use the merged index as the iteration index (it should already be 1-minute bars).
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
        start_dt, _ = self.get_start_datetime_and_ts_unit(length, timestep, start_dt=end_dt, start_buffer=timedelta(0))
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
