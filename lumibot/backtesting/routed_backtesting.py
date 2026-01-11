import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd

from lumibot.backtesting.thetadata_backtesting_pandas import ThetaDataBacktestingPandas
from lumibot.entities import Asset, Data
from lumibot.tools import ibkr_helper

logger = logging.getLogger(__name__)


class RoutedBacktestingPandas(ThetaDataBacktestingPandas):
    """Backtesting data source that routes requests to multiple providers by asset type.

    Current supported providers:
    - ThetaData (default): stocks, options, indexes
    - IBKR Client Portal (REST) via the shared Data Downloader: futures + spot crypto

    Routing is configured via `config["backtesting_data_routing"]` (a dict mapping asset_type -> provider).
    """

    _CONFIG_KEY = "backtesting_data_routing"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._routing = self._normalize_routing(self._extract_routing_config(getattr(self, "_config", None)))
        # Track which IBKR series have been fully prefetched for the backtest window.
        # This prevents slow "one request per simulated day" behavior for daily-cadence crypto strategies.
        self._ibkr_fully_loaded_series: set[tuple] = set()

    @staticmethod
    def _extract_routing_config(config: Any) -> Optional[Dict[str, str]]:
        if config is None:
            return None
        if isinstance(config, dict):
            raw = config.get(RoutedBacktestingPandas._CONFIG_KEY)
            return raw if isinstance(raw, dict) else None
        raw = getattr(config, RoutedBacktestingPandas._CONFIG_KEY, None)
        return raw if isinstance(raw, dict) else None

    @staticmethod
    def _normalize_routing(routing: Optional[Dict[str, str]]) -> Dict[str, str]:
        if not routing:
            return {
                "default": "thetadata",
                "future": "ibkr",
                "cont_future": "ibkr",
                "crypto": "ibkr",
            }

        normalized: Dict[str, str] = {}
        for key, value in routing.items():
            if key is None:
                continue
            asset_type = str(key).strip().lower()
            provider = str(value).strip().lower() if value is not None else ""
            if provider in {"theta", "thetadata"}:
                provider = "thetadata"
            elif provider in {"ibkr", "interactivebrokersrest", "interactive_brokers_rest"}:
                provider = "ibkr"
            normalized[asset_type] = provider

        normalized.setdefault("default", "thetadata")
        return normalized

    def _provider_for_asset(self, asset: Asset) -> str:
        asset_type = str(getattr(asset, "asset_type", "") or "").lower()
        provider = self._routing.get(asset_type) or self._routing.get("default") or "thetadata"
        return provider

    def _update_pandas_data(
        self,
        asset,
        quote,
        length,
        timestep,
        start_dt=None,
        require_quote_data: bool = False,
        require_ohlc_data: bool = True,
        snapshot_only: bool = False,
    ):
        asset_separated = asset
        quote_asset = quote if quote is not None else Asset("USD", "forex")
        if isinstance(asset_separated, tuple):
            asset_separated, quote_asset = asset_separated

        provider = self._provider_for_asset(asset_separated)
        if provider != "ibkr":
            return super()._update_pandas_data(
                asset,
                quote,
                length,
                timestep,
                start_dt=start_dt,
                require_quote_data=require_quote_data,
                require_ohlc_data=require_ohlc_data,
                snapshot_only=snapshot_only,
            )

        if snapshot_only:
            return None

        end_dt = start_dt if isinstance(start_dt, datetime) else self.get_datetime()
        ts = timestep or self.get_timestep()
        # IBKR crypto/futures trade outside equity calendars; do not add the default 5-day padding.
        start_datetime, ts_unit = self.get_start_datetime_and_ts_unit(length, ts, start_dt=end_dt, start_buffer=timedelta(0))
        if ts_unit == "day":
            # Mirror ThetaDataBacktestingPandas: mark that day data exists so day-mode callers
            # (e.g., get_last_price) can align away from minute bars when appropriate.
            try:
                self._effective_day_mode = True
            except Exception:
                pass

        canonical_key, legacy_key = self._build_dataset_keys(asset_separated, quote_asset, ts_unit)
        existing = self._data_store.get(canonical_key)
        existing_df = getattr(existing, "df", None) if existing is not None else None

        if existing_df is not None and isinstance(existing_df, pd.DataFrame) and not existing_df.empty:
            try:
                existing_start = existing_df.index.min()
                existing_end = existing_df.index.max()
                if existing_start is not None and existing_end is not None:
                    if start_datetime >= existing_start and end_dt <= existing_end:
                        return None
            except Exception:
                pass

        asset_type = str(getattr(asset_separated, "asset_type", "") or "").lower()
        # Crypto daily backtests frequently request a rolling lookback (e.g. 200D SMA) at every
        # simulated day, which can otherwise translate into one IBKR request per day.
        #
        # Prefetch the full backtest window once per symbol and then serve subsequent requests
        # via slicing from the in-memory DataFrame (and parquet cache under the hood).
        if asset_type == "crypto" and ts_unit == "day" and canonical_key not in self._ibkr_fully_loaded_series:
            try:
                lookback_days = max(7, int(length) + 5)
            except Exception:
                lookback_days = 7
            prefetch_start = min(start_datetime, self.datetime_start - timedelta(days=lookback_days))
            prefetch_end = self.datetime_end

            df_prefetch = ibkr_helper.get_price_data(
                asset=asset_separated,
                quote=quote_asset,
                timestep=ts_unit,
                start_dt=prefetch_start,
                end_dt=prefetch_end,
                exchange=None,
                include_after_hours=True,
            )
            if df_prefetch is None or df_prefetch.empty:
                return None
            df = df_prefetch
            self._ibkr_fully_loaded_series.add(canonical_key)
        else:
            df = ibkr_helper.get_price_data(
                asset=asset_separated,
                quote=quote_asset,
                timestep=ts_unit,
                start_dt=start_datetime,
                end_dt=end_dt,
                exchange=None,
                include_after_hours=True,
            )
            if df is None or df.empty:
                return None

        if existing_df is not None and isinstance(existing_df, pd.DataFrame) and not existing_df.empty:
            merged = pd.concat([existing_df, df], axis=0).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]
        else:
            merged = df

        data = Data(asset_separated, merged, timestep=ts_unit, quote=quote_asset)
        self._data_store[canonical_key] = data
        if legacy_key not in self._data_store:
            self._data_store[legacy_key] = data

    def get_last_price(self, asset, timestep="minute", quote=None, exchange=None, **kwargs):
        """Align IBKR crypto daily backtests away from minute bars for performance.

        ThetaDataBacktestingPandas already aligns get_last_price() to day bars when the data source
        is running in daily cadence. For the routed IBKR path, we infer "safe to align" using the
        same guardrail: only when we have not observed intraday cadence.
        """
        try:
            dt = self.get_datetime()
            self._update_cadence_from_dt(dt)
        except Exception:
            pass

        try:
            provider = self._provider_for_asset(asset if not isinstance(asset, tuple) else asset[0])
        except Exception:
            provider = "thetadata"

        if provider == "ibkr" and timestep == "minute":
            # If this run hasn't shown intraday cadence, prefer day-level marks for crypto to avoid
            # expensive minute-by-minute backfill during daily strategies.
            if not bool(getattr(self, "_observed_intraday_cadence", False)) and bool(
                getattr(self, "_effective_day_mode", False)
            ):
                timestep = "day"

        return super().get_last_price(asset, timestep=timestep, quote=quote, exchange=exchange, **kwargs)
