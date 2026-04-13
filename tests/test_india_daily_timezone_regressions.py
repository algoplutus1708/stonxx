from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytz

from lumibot.data_sources.dhan_data import DhanData
from lumibot.data_sources.yahoo_data import YahooData
from lumibot.entities import Asset


def _make_yahoo_daily_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1_000, 1_100, 1_200],
            "Dividends": [0.0, 0.0, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0],
        },
        index=index,
    )


def test_dhan_data_syncs_yahoo_delegate_to_live_ist(monkeypatch):
    ist = pytz.timezone("Asia/Kolkata")
    captured: dict[str, object] = {}

    def fake_get_historical_prices(self, asset, length, timestep="", **kwargs):
        captured["tzinfo"] = self.tzinfo
        captured["current_dt"] = self._datetime
        captured["datetime_start"] = self.datetime_start
        return SimpleNamespace(df=pd.DataFrame())

    monkeypatch.setattr(YahooData, "get_historical_prices", fake_get_historical_prices)

    data = DhanData(
        client_id="paper-id",
        access_token="paper-token",
        use_yfinance_historical=True,
    )

    data.get_historical_prices(Asset("RELIANCE", asset_type=Asset.AssetType.STOCK), 5, "day")

    assert getattr(captured["tzinfo"], "zone", None) == "Asia/Kolkata"
    assert getattr(captured["current_dt"].tzinfo, "zone", None) == "Asia/Kolkata"
    assert getattr(captured["datetime_start"].tzinfo, "zone", None) == "Asia/Kolkata"

    now_ist = pd.Timestamp.now(tz=ist).to_pydatetime()
    assert abs((captured["current_dt"] - now_ist).total_seconds()) < 10


def test_yahoo_daily_history_excludes_current_india_bar_before_close(monkeypatch):
    ist = pytz.timezone("Asia/Kolkata")
    index = pd.DatetimeIndex(
        [
            ist.localize(datetime(2026, 4, 10, 0, 0)),
            ist.localize(datetime(2026, 4, 13, 0, 0)),
            ist.localize(datetime(2026, 4, 14, 0, 0)),
        ],
        name="datetime",
    )

    monkeypatch.setattr(
        "lumibot.data_sources.yahoo_data.YahooHelper.get_symbol_data",
        lambda *args, **kwargs: _make_yahoo_daily_frame(index),
    )

    yahoo = YahooData(
        datetime_start=ist.localize(datetime(2026, 4, 1)),
        datetime_end=ist.localize(datetime(2026, 4, 30)),
        tzinfo=ist,
    )
    yahoo._datetime = ist.localize(datetime(2026, 4, 14, 13, 56))

    result = yahoo._pull_source_symbol_bars(
        Asset("RELIANCE.NS", asset_type=Asset.AssetType.STOCK),
        length=3,
        timestep="day",
    )

    assert list(result.index.date) == [datetime(2026, 4, 10).date(), datetime(2026, 4, 13).date()]


def test_yahoo_daily_history_includes_current_india_bar_after_close(monkeypatch):
    ist = pytz.timezone("Asia/Kolkata")
    index = pd.DatetimeIndex(
        [
            ist.localize(datetime(2026, 4, 10, 0, 0)),
            ist.localize(datetime(2026, 4, 13, 0, 0)),
            ist.localize(datetime(2026, 4, 14, 0, 0)),
        ],
        name="datetime",
    )

    monkeypatch.setattr(
        "lumibot.data_sources.yahoo_data.YahooHelper.get_symbol_data",
        lambda *args, **kwargs: _make_yahoo_daily_frame(index),
    )

    yahoo = YahooData(
        datetime_start=ist.localize(datetime(2026, 4, 1)),
        datetime_end=ist.localize(datetime(2026, 4, 30)),
        tzinfo=ist,
    )
    yahoo._datetime = ist.localize(datetime(2026, 4, 14, 15, 45))

    result = yahoo._pull_source_symbol_bars(
        Asset("RELIANCE.NS", asset_type=Asset.AssetType.STOCK),
        length=3,
        timestep="day",
    )

    assert list(result.index.date) == [
        datetime(2026, 4, 10).date(),
        datetime(2026, 4, 13).date(),
        datetime(2026, 4, 14).date(),
    ]
