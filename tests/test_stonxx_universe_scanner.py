from types import SimpleNamespace

import numpy as np
import pandas as pd

from lumibot.example_strategies.stonxx_india_bot import stonxx


def _make_history(start_price: float, step: float, periods: int = 200, start: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods, tz="Asia/Kolkata")
    close = start_price + (np.arange(periods) * step)
    frame = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000 + (np.arange(periods) * 1_000),
        },
        index=dates,
    )
    frame.index.name = "datetime"
    return frame


def _build_scanner_strategy():
    strategy = stonxx.__new__(stonxx)
    strategy.log_message = lambda *args, **kwargs: None
    return strategy


def test_refresh_active_universe_filters_and_ranks_survivors():
    strategy = _build_scanner_strategy()
    strategy.parameters = {
        "master_universe": ["AAA", "BBB", "CCC"],
        "dynamic_universe_size": 2,
    }
    strategy.universe = ["LEGACY"]

    histories = {
        "AAA": SimpleNamespace(df=_make_history(100.0, 1.0)),
        "BBB": SimpleNamespace(df=_make_history(100.0, 0.2)),
        "CCC": SimpleNamespace(df=_make_history(300.0, -0.5)),
    }
    strategy.get_historical_prices_for_assets = lambda *args, **kwargs: histories

    selected = strategy.refresh_active_universe()

    assert selected == ["AAA", "BBB"]
    assert strategy.universe == ["AAA", "BBB"]


def test_refresh_active_universe_keeps_existing_universe_when_history_is_unavailable():
    strategy = _build_scanner_strategy()
    strategy.parameters = {"master_universe": ["AAA", "BBB"]}
    strategy.universe = ["KEEP", "ME"]
    strategy.get_historical_prices_for_assets = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down"))

    selected = strategy.refresh_active_universe()

    assert selected == ["KEEP", "ME"]
    assert strategy.universe == ["KEEP", "ME"]


def test_initialize_bootstraps_master_universe_and_schedules_weekly_refresh(monkeypatch):
    from lumibot.example_strategies import stonxx_india_bot as module

    strategy = _build_scanner_strategy()
    strategy.parameters = {
        "master_universe": "AAA, BBB, CCC",
        "dynamic_universe_size": 1,
        "IS_PAPER_TRADING": False,
    }
    strategy.is_backtesting = False
    strategy.broker = SimpleNamespace(data_source=SimpleNamespace(tzinfo=None))
    strategy.set_market = lambda market: setattr(strategy, "_market", market)
    strategy._ensure_paper_trade_file = lambda: None

    monkeypatch.setattr(module, "SentimentAnalyzer", None)
    monkeypatch.setattr(
        module.joblib,
        "load",
        lambda path: {
            "model": SimpleNamespace(predict=lambda frame: [0.0]),
            "features": [],
            "meta": {"mean_metrics": {"rmse": 0.0}},
        },
    )
    monkeypatch.setattr(
        module,
        "load_state",
        lambda path: {
            "active_trades": {},
            "pending_orders": [],
            "paper_cash": 1_000_000.0,
            "last_signal_date": None,
            "last_submission_date": None,
            "symbol_cooldowns": {},
        },
    )
    monkeypatch.setattr(module, "save_state", lambda *args, **kwargs: None)

    refreshed = []

    def fake_refresh():
        refreshed.append(True)
        strategy.universe = ["AAA"]
        return strategy.universe

    registered = []

    def fake_register(cron_schedule, callback):
        registered.append((cron_schedule, callback.__name__))
        return "job-id"

    strategy.refresh_active_universe = fake_refresh
    strategy.register_cron_callback = fake_register

    strategy.initialize()

    assert strategy._market == "XBOM"
    assert strategy.broker.data_source.tzinfo.zone == "Asia/Kolkata"
    assert strategy.master_universe == ["AAA", "BBB", "CCC"]
    assert strategy.universe == ["AAA"]
    assert refreshed == [True]
    assert ("45 15 * * 1-5", "generate_after_close_plan") in registered
    assert ("16 9 * * 1-5", "submit_pending_orders") in registered
    # The refresh callback is monkeypatched in this test, so only the cron schedule itself is stable.
    assert any(cron == "0 8 * * 1" for cron, _ in registered)
