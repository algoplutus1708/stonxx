from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytz
import pytest

from lumibot.backtesting.thetadata_backtesting_pandas import ThetaDataBacktestingPandas
from lumibot.entities import Asset
from lumibot.tools import thetadata_helper


def test_intraday_cache_end_validation_does_not_reuse_stale_prior_day_data(monkeypatch):
    """Regression: minute caches must not treat prior-day coverage as valid for a new trading day.

    The ThetaData backtesting engine uses a cache-coverage heuristic to decide whether to refetch
    intraday datasets. A prior implementation compared only *dates* and allowed a multi-day tolerance,
    which meant a dataset that ended at the prior day's close could be reused for several subsequent
    days. That caused `get_last_price()` to return the prior-day close for intraday timestamps and
    broke determinism (SPX Copy2/Copy3 cold-cache runs selected different strikes/trades vs warm runs).

    This test asserts that when the existing cache ends on 2025-01-21 but the simulation time is
    2025-01-22, `_update_pandas_data()` attempts a refetch (and thus calls `thetadata_helper.get_price_data`).
    """

    tz = pytz.timezone("America/New_York")
    dt = tz.localize(datetime(2025, 1, 22, 10, 15))

    source = ThetaDataBacktestingPandas(
        datetime_start=tz.localize(datetime(2025, 1, 21, 9, 30)),
        datetime_end=tz.localize(datetime(2025, 1, 28, 16, 0)),
        username="test",
        password="test",
        tzinfo=tz,
    )

    monkeypatch.setattr(source, "get_datetime", lambda: dt)

    asset = Asset("SPXW", asset_type=Asset.AssetType.INDEX)
    quote_asset = Asset("USD", asset_type="forex")
    canonical_key = (asset, quote_asset, "minute")

    # Existing cached data: ends at prior-day close (2025-01-21 16:00 ET).
    existing_end = tz.localize(datetime(2025, 1, 21, 16, 0))
    idx = pd.date_range(existing_end - timedelta(minutes=4), existing_end, freq="min", tz=tz)
    df = pd.DataFrame({"close": [6049.25, 6049.26, 6049.27, 6049.28, 6049.29]}, index=idx)
    source.pandas_data[canonical_key] = SimpleNamespace(df=df, timestep="minute")
    source._dataset_metadata[canonical_key] = {
        "timestep": "minute",
        "start": idx[0].to_pydatetime(),
        "end": idx[-1].to_pydatetime(),
        "rows": len(df),
        "has_quotes": False,
        "has_ohlc": True,
        "prefetch_complete": True,
    }

    def _fetch_called(*_args, **_kwargs):
        raise RuntimeError("fetch_called")

    monkeypatch.setattr(thetadata_helper, "get_price_data", _fetch_called)

    with pytest.raises(RuntimeError, match="fetch_called"):
        source._update_pandas_data(asset, quote_asset, 5, "minute", dt, require_quote_data=False, require_ohlc_data=True)

