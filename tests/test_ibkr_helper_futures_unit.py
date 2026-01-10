from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lumibot.entities import Asset


def test_ibkr_helper_future_requires_expiration(monkeypatch, tmp_path):
    import lumibot.tools.ibkr_helper as ibkr_helper

    monkeypatch.setattr(ibkr_helper, "LUMIBOT_CACHE_FOLDER", tmp_path.as_posix())

    def fake_queue_request(url: str, querystring, headers=None, timeout=None):
        raise AssertionError(f"Should not attempt remote calls for invalid futures asset: {url}")

    monkeypatch.setattr(ibkr_helper, "queue_request", fake_queue_request)

    asset = Asset(symbol="MES", asset_type="future")
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="futures require an explicit expiration"):
        ibkr_helper.get_price_data(asset=asset, quote=None, timestep="minute", start_dt=start, end_dt=end)

