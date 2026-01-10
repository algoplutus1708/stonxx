import logging
from datetime import datetime
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
        start_datetime, ts_unit = self.get_start_datetime_and_ts_unit(length, ts, start_dt=end_dt)

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

