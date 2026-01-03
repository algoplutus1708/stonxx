"""
Acceptance smokes (ThetaData, S3-only).

These tests exist to enforce two properties in CI:
1) The dev S3 cache has the objects we expect for a minimal ThetaData options/quotes path.
2) LumiBot can hydrate from S3 in strict read-only mode (fail fast on cache miss) without
   falling back to the ThetaData downloader.

They intentionally do not run full-year backtests (too slow for PR CI).
"""

# ruff: noqa: I001
import os
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv

pytestmark = [pytest.mark.acceptance_smoke]

DEFAULT_ENV_PATH = Path.home() / "Documents/Development/Strategy Library/Demos/.env"


def _ensure_env_loaded() -> None:
    env_path_local = Path(os.environ.get("LUMIBOT_DEMOS_ENV", DEFAULT_ENV_PATH))
    if env_path_local.exists():
        load_dotenv(env_path_local)

    required = [
        "LUMIBOT_CACHE_BACKEND",
        "LUMIBOT_CACHE_MODE",
        "LUMIBOT_CACHE_S3_BUCKET",
        "LUMIBOT_CACHE_S3_PREFIX",
        "LUMIBOT_CACHE_S3_REGION",
        "LUMIBOT_CACHE_S3_ACCESS_KEY_ID",
        "LUMIBOT_CACHE_S3_SECRET_ACCESS_KEY",
        "LUMIBOT_CACHE_S3_VERSION",
    ]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" or os.environ.get("CI"):
            pytest.fail(f"Missing required env vars for S3 cache-backed acceptance smokes: {missing}")
        pytest.skip(f"Missing required env vars for S3 cache-backed acceptance smokes: {missing}")

    backend = (os.environ.get("LUMIBOT_CACHE_BACKEND") or "").strip().lower()
    mode = (os.environ.get("LUMIBOT_CACHE_MODE") or "").strip().lower()
    if backend != "s3" or mode not in {"s3_readonly", "readonly", "ro"}:
        message = (
            "Acceptance smokes must run with S3 cache read-only mode. "
            f"Got LUMIBOT_CACHE_BACKEND={backend!r} LUMIBOT_CACHE_MODE={mode!r}"
        )
        if os.environ.get("GITHUB_ACTIONS", "").lower() == "true" or os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)

    os.environ.setdefault("LUMIBOT_CACHE_STRICT", "true")


def test_s3_cache_can_hydrate_spxw_chain_file() -> None:
    _ensure_env_loaded()

    from lumibot.entities import Asset
    from lumibot.tools.backtest_cache import get_backtest_cache, reset_backtest_cache_manager
    from lumibot.tools.thetadata_helper import get_chains_cached

    reset_backtest_cache_manager(for_testing=True)
    cache = get_backtest_cache()

    assert cache.enabled
    assert cache.mode.value == "s3_readonly"
    assert cache.strict is True

    chains = get_chains_cached(
        Asset(symbol="SPXW", asset_type="index"),
        current_date=date(2024, 1, 22),
    )

    assert isinstance(chains, dict)
    assert chains.get("Multiplier") == 100
    assert isinstance(chains.get("Chains"), dict)
    assert "CALL" in chains["Chains"]
    assert "PUT" in chains["Chains"]


def test_s3_cache_can_hydrate_known_spxw_minute_quotes() -> None:
    _ensure_env_loaded()

    from lumibot.constants import LUMIBOT_CACHE_FOLDER
    from lumibot.tools.backtest_cache import get_backtest_cache, reset_backtest_cache_manager

    reset_backtest_cache_manager(for_testing=True)
    cache = get_backtest_cache()

    call_path = (
        Path(LUMIBOT_CACHE_FOLDER)
        / "thetadata"
        / "option"
        / "minute"
        / "quote"
        / "option_SPXW_240122_4865.0_CALL_minute_quote.parquet"
    )
    put_path = (
        Path(LUMIBOT_CACHE_FOLDER)
        / "thetadata"
        / "option"
        / "minute"
        / "quote"
        / "option_SPXW_240122_4865.0_PUT_minute_quote.parquet"
    )

    cache.ensure_local_file(call_path)
    cache.ensure_local_file(put_path)

    call_df = pd.read_parquet(call_path)
    put_df = pd.read_parquet(put_path)

    assert not call_df.empty
    assert not put_df.empty
    assert {"bid", "ask", "datetime"}.issubset(set(call_df.columns))
    assert {"bid", "ask", "datetime"}.issubset(set(put_df.columns))


def test_strict_s3_readonly_raises_on_cache_miss() -> None:
    _ensure_env_loaded()

    from lumibot.constants import LUMIBOT_CACHE_FOLDER
    from lumibot.tools.backtest_cache import RemoteCacheMissError, get_backtest_cache, reset_backtest_cache_manager

    reset_backtest_cache_manager(for_testing=True)
    cache = get_backtest_cache()

    missing_path = (
        Path(LUMIBOT_CACHE_FOLDER)
        / "thetadata"
        / "stock"
        / "day"
        / "ohlc"
        / "stock_THIS_SYMBOL_SHOULD_NOT_EXIST_day_ohlc.parquet"
    )
    with pytest.raises(RemoteCacheMissError):
        cache.ensure_local_file(missing_path)
