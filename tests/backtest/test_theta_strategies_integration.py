"""
Acceptance smoke tests (ThetaData, prod-like env).

These are CI "release gate" smokes for the ThetaData backtesting stack.

Requirements (per release policy):
1) Run in a prod-like configuration: S3 cache enabled AND downloader creds configured.
2) The dev S3 cache is assumed warm for these specific fixtures.
3) The tests must FAIL if they try to hit the downloader queue (i.e., a cache miss should not
   silently fall back to ThetaData during CI).

Note: These are intentionally short-window smokes (not the full Strategy Library acceptance suite).
"""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import pytest
from dotenv import load_dotenv

pytestmark = [pytest.mark.acceptance_smoke]

DEFAULT_ENV_PATH = Path.home() / "Documents/Development/Strategy Library/Demos/.env"
# IMPORTANT: load local env *before* importing LumiBot internals so credentials-derived
# globals (like CACHE_REMOTE_CONFIG) reflect the intended smoke configuration.
_ENV_PATH_LOCAL = Path(os.environ.get("LUMIBOT_DEMOS_ENV", DEFAULT_ENV_PATH))
if _ENV_PATH_LOCAL.exists():
    load_dotenv(_ENV_PATH_LOCAL)


def _is_ci() -> bool:
    return (os.environ.get("GITHUB_ACTIONS", "").lower() == "true") or bool(os.environ.get("CI"))


def _ensure_env_loaded() -> None:
    """Load local dev env when available, and enforce required prod-like env for smokes."""
    required = [
        # S3 cache (dev bucket)
        "LUMIBOT_CACHE_BACKEND",
        "LUMIBOT_CACHE_MODE",
        "LUMIBOT_CACHE_S3_BUCKET",
        "LUMIBOT_CACHE_S3_PREFIX",
        "LUMIBOT_CACHE_S3_REGION",
        "LUMIBOT_CACHE_S3_ACCESS_KEY_ID",
        "LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY",
        "LUMIBOT_CACHE_S3_VERSION",
        # Downloader configured (even though smokes must not use it when cache is warm)
        "DATADOWNLOADER_BASE_URL",
        "DATADOWNLOADER_API_KEY",
    ]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        message = f"Missing required env vars for ThetaData acceptance smokes: {missing}"
        if _is_ci():
            pytest.fail(message)
        pytest.skip(message)

    backend = (os.environ.get("LUMIBOT_CACHE_BACKEND") or "").strip().lower()
    mode = (os.environ.get("LUMIBOT_CACHE_MODE") or "").strip().lower()
    allowed_modes = {"readwrite", "rw", "s3_readwrite", "readonly", "ro", "s3_readonly"}
    if backend != "s3" or mode not in allowed_modes:
        message = (
            "Acceptance smokes must run with the S3 cache enabled. "
            f"Got LUMIBOT_CACHE_BACKEND={backend!r} LUMIBOT_CACHE_MODE={mode!r}"
        )
        if _is_ci():
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture()
def forbid_downloader_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if anything tries to hit the downloader queue in these smokes."""
    from lumibot.tools import thetadata_queue_client

    def _forbidden(*args, **kwargs):  # noqa: ANN001
        raise AssertionError(
            "Acceptance smoke attempted to hit the ThetaData downloader queue "
            f"(queue_request called). args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr(thetadata_queue_client, "queue_request", _forbidden)


def _assert_df_has_quote_cols(df: pd.DataFrame) -> None:
    assert df is not None
    assert not df.empty
    assert {"bid", "ask"}.issubset(set(df.columns))
    # Some cache loaders keep `datetime` as a column; others set it as the index.
    if "datetime" not in df.columns:
        assert df.index is not None


def _iter_option_quote_records(df: pd.DataFrame) -> Iterable[tuple[float, float]]:
    for _, row in df.iterrows():
        yield float(row["bid"]) if pd.notna(row["bid"]) else float("nan"), float(row["ask"]) if pd.notna(row["ask"]) else float("nan")


def test_smoke_spxw_chain_and_minute_quotes_are_cached(forbid_downloader_queue: None) -> None:
    """
    This test exercises the critical "warm cache" path without running a full-year strategy:
    - Hydrate an SPXW chain file from S3.
    - Hydrate known SPXW minute-quote parquet files from S3.

    If *any* of these are missing, the test must fail (no silent fallback to downloader).
    """
    _ensure_env_loaded()

    from lumibot.entities import Asset
    from lumibot.tools.backtest_cache import reset_backtest_cache_manager
    from lumibot.tools.thetadata_helper import get_chains_cached, get_price_data

    reset_backtest_cache_manager(for_testing=True)

    chains = get_chains_cached(
        Asset(symbol="SPXW", asset_type="index"),
        current_date=dt.date(2024, 1, 22),
    )
    assert isinstance(chains, dict)
    assert chains.get("Multiplier") == 100
    assert isinstance(chains.get("Chains"), dict)
    assert "CALL" in chains["Chains"]
    assert "PUT" in chains["Chains"]

    call = Asset(
        symbol="SPXW",
        asset_type="option",
        expiration=dt.date(2024, 1, 22),
        strike=4865.0,
        right="CALL",
        multiplier=100,
        underlying_asset=Asset(symbol="SPX", asset_type="index"),
    )
    put = Asset(
        symbol="SPXW",
        asset_type="option",
        expiration=dt.date(2024, 1, 22),
        strike=4865.0,
        right="PUT",
        multiplier=100,
        underlying_asset=Asset(symbol="SPX", asset_type="index"),
    )

    start = dt.datetime(2024, 1, 22, 9, 30)
    end = dt.datetime(2024, 1, 22, 16, 0)
    call_df = get_price_data(call, start=start, end=end, timespan="minute", datastyle="quote")
    put_df = get_price_data(put, start=start, end=end, timespan="minute", datastyle="quote")

    _assert_df_has_quote_cols(call_df)
    _assert_df_has_quote_cols(put_df)

    # Sanity: quotes should have at least some valid bid/ask points.
    assert any(
        (bid > 0.0 and ask > 0.0 and ask >= bid)
        for bid, ask in _iter_option_quote_records(call_df)
    )
    assert any(
        (bid > 0.0 and ask > 0.0 and ask >= bid)
        for bid, ask in _iter_option_quote_records(put_df)
    )


def test_smoke_spxw_short_window_backtest_uses_warm_cache_only(forbid_downloader_queue: None) -> None:
    """
    End-to-end backtest smoke (short window) to prove that:
    - The full backtesting loop can run with ThetaDataBacktestingPandas
    - With a warm dev S3 cache, it does not need the downloader queue
    - The resulting performance stats are sane and stable
    """
    _ensure_env_loaded()

    from lumibot.backtesting import ThetaDataBacktestingPandas
    from lumibot.entities import Asset, Order
    from lumibot.strategies import Strategy

    class _SPXWSingleContractSmoke(Strategy):
        def initialize(self) -> None:
            self.sleeptime = "1M"
            self.vars.opened = False
            self.vars.closed = False
            self.vars.entry_dt = None
            self.vars.contract = Asset(
                symbol="SPXW",
                asset_type="option",
                expiration=dt.date(2024, 1, 22),
                strike=4865.0,
                right="CALL",
                multiplier=100,
                underlying_asset=Asset(symbol="SPX", asset_type="index"),
            )

        def on_trading_iteration(self) -> None:
            now = self.get_datetime()
            if not self.vars.opened:
                self.vars.opened = True
                self.vars.entry_dt = now
                order = self.create_order(
                    self.vars.contract,
                    1,
                    side=Order.OrderSide.BUY,
                    order_type=Order.OrderType.MARKET,
                )
                self.submit_order(order)
                return

            if self.vars.closed:
                return

            try:
                entry_dt = self.vars.entry_dt
            except Exception:
                entry_dt = None
            if entry_dt is None:
                return

            if now >= entry_dt + dt.timedelta(minutes=5):
                position = self.get_position(self.vars.contract)
                if position is None or position.quantity <= 0:
                    self.vars.closed = True
                    return

                order = self.create_order(
                    self.vars.contract,
                    position.quantity,
                    side=Order.OrderSide.SELL,
                    order_type=Order.OrderType.MARKET,
                )
                self.submit_order(order)
                self.vars.closed = True

    started = time.perf_counter()
    results = _SPXWSingleContractSmoke.backtest(
        datasource_class=ThetaDataBacktestingPandas,
        backtesting_start=dt.datetime(2024, 1, 22, 10, 0),
        backtesting_end=dt.datetime(2024, 1, 22, 10, 15),
        show_plot=False,
        show_tearsheet=False,
        save_tearsheet=False,
        show_indicators=False,
        save_logfile=False,
        show_progress_bar=False,
        quiet_logs=False,
        budget=100_000,
    )
    elapsed_s = time.perf_counter() - started

    # CI safety net: this should be fast on a warm cache. Keep the ceiling generous to avoid
    # flakiness from transient runner noise, but still catch pathological regressions.
    assert elapsed_s < 300.0, f"Smoke backtest took too long: {elapsed_s:.1f}s"

    assert isinstance(results, dict)
    assert {"cagr", "max_drawdown", "total_return"}.issubset(set(results.keys()))
    assert results["max_drawdown"] is not None and "drawdown" in results["max_drawdown"]
    assert isinstance(results["total_return"], (int, float))
