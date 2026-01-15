import logging
import os
from datetime import date, datetime
from types import SimpleNamespace

# Tests must not depend on local `.env` scanning (can load secrets and slow imports).
os.environ.setdefault("LUMIBOT_DISABLE_DOTENV", "1")

from lumibot.backtesting.thetadata_backtesting_pandas import ThetaDataBacktestingPandas
from lumibot.entities import Asset
from lumibot.strategies._strategy import _Strategy


def test_thetadata_daily_option_mtm_uses_intraday_snapshot_quote() -> None:
    """Regression: day-cadence option MTM must not depend on ThetaData EOD option history.

    ThetaData can return 472/no-data for option EOD history even when intraday NBBO quote history exists.
    If LumiBot requests day-level option quotes in daily cadence, strategies can fail to value/exit options,
    producing flat equity curves and incorrect tearsheets. We always probe a minimal intraday quote snapshot
    for ThetaData option mark-to-market.
    """

    class DummyBroker:
        datetime = datetime(2025, 1, 2, 9, 30)

    class DummyStrategy:
        is_backtesting = True
        broker = DummyBroker()
        logger = logging.getLogger("lumibot.test")
        _quote_asset = Asset("USD", asset_type="forex")

        def _get_sleeptime_seconds(self):
            # Daily cadence -> previous bug passed timestep_hint="day" into option quote lookup.
            return 24 * 3600

    dummy_strategy = DummyStrategy()

    option_asset = Asset(
        symbol="MELI",
        asset_type="option",
        expiration=date(2015, 1, 16),
        strike=120.0,
        right="call",
    )

    # Instantiate without running __init__ (which would attempt to manage ThetaTerminal processes).
    source = object.__new__(ThetaDataBacktestingPandas)

    called = {}

    def fake_get_quote(asset, quote=None, exchange=None, timestep="minute", **kwargs):
        calls = called.setdefault("calls", [])
        calls.append({"timestep": timestep, "snapshot_only": bool(kwargs.get("snapshot_only", False))})

        # First probe: daily cadence uses day/EOD quote path.
        if timestep == "day":
            return SimpleNamespace(bid=None, ask=None, price=None)

        # Fallback: intraday snapshot must be used when day/EOD is missing.
        assert timestep == "minute"
        assert bool(kwargs.get("snapshot_only", False)) is True
        return SimpleNamespace(bid=1.0, ask=3.0, price=None)

    source.get_quote = fake_get_quote

    price = _Strategy._get_price_from_source(dummy_strategy, source, option_asset)
    assert price == 2.0

    assert called["calls"] == [
        {"timestep": "day", "snapshot_only": False},
        {"timestep": "minute", "snapshot_only": True},
    ]
