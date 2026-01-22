#!/usr/bin/env python3
from __future__ import annotations

"""
warm_ibkr_speed_burner_data.py

One-time cache warmer for the IBKR speed burner benchmarks.

This script intentionally DOES hit the downloader (cold run) to populate parquet cache so that
warm-cache benchmarks can be measured as queue-free and bounded.

It does not print any secrets; it relies on environment variables already configured in the shell.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _force_source_tree_imports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))


def _lock_down_env() -> None:
    # Avoid recursive `.env` discovery (latency + accidental secrets loading).
    os.environ.setdefault("LUMIBOT_DISABLE_DOTENV", "true")
    os.environ.setdefault("IS_BACKTESTING", "true")


def _load_repo_dotenv_if_needed() -> None:
    """Best-effort local `.env` load for developer convenience.

    This script is explicitly a cache warmer and needs downloader credentials.
    We avoid LumiBot's recursive `.env` discovery (which logs) and instead load only the
    repo-local `.env` if present, without printing any values.
    """
    if (os.environ.get("DATADOWNLOADER_BASE_URL") or "").strip() and (os.environ.get("DATADOWNLOADER_API_KEY") or "").strip():
        return
    try:
        from dotenv import dotenv_values
    except Exception:
        return

    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / ".env"
    if not env_path.exists():
        return

    values = dotenv_values(env_path)
    for key in ("DATADOWNLOADER_BASE_URL", "DATADOWNLOADER_API_KEY", "DATADOWNLOADER_API_KEY_HEADER"):
        val = (values.get(key) or "").strip()
        if val and not (os.environ.get(key) or "").strip():
            os.environ[key] = val


def _require_env(name: str) -> str:
    val = (os.environ.get(name) or "").strip()
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def main() -> int:
    _lock_down_env()
    _force_source_tree_imports()

    # Require downloader creds. This script is explicitly for warming caches.
    _load_repo_dotenv_if_needed()
    base_url = _require_env("DATADOWNLOADER_BASE_URL").rstrip("/")
    api_key = _require_env("DATADOWNLOADER_API_KEY")
    api_key_header = (os.environ.get("DATADOWNLOADER_API_KEY_HEADER") or "X-Downloader-Key").strip() or "X-Downloader-Key"

    # Fail fast if the downloader is unreachable instead of stalling on queue waits.
    try:
        import requests

        resp = requests.get(
            f"{base_url}/healthz",
            headers={api_key_header: api_key},
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Downloader not reachable/healthy (warm step aborted): {exc}") from exc

    from lumibot.entities import Asset
    import lumibot.tools.ibkr_helper as ibkr_helper

    # Match the warm-cache benchmark window.
    # `bench_ibkr_speed_burner_warm_cache.py` uses America/New_York 09:30–19:30, which corresponds
    # to 14:30–00:30 UTC on this date.
    window_start = datetime(2025, 12, 8, 14, 30, tzinfo=timezone.utc)
    window_end = datetime(2025, 12, 9, 0, 30, tzinfo=timezone.utc)

    fut_mes = Asset("MES", asset_type=Asset.AssetType.FUTURE, expiration=date(2025, 12, 19), multiplier=5)
    fut_mnq = Asset("MNQ", asset_type=Asset.AssetType.FUTURE, expiration=date(2025, 12, 19), multiplier=2)
    btc = Asset("BTC", asset_type=Asset.AssetType.CRYPTO)
    eth = Asset("ETH", asset_type=Asset.AssetType.CRYPTO)
    sol = Asset("SOL", asset_type=Asset.AssetType.CRYPTO)

    # Pull enough history for lookbacks (minute=100, day=20) + a bit of padding.
    minute_start = window_start - timedelta(hours=4)
    # Futures daily bars are aligned to the `us_futures` session calendar (weekends/holidays), so
    # requesting extra padding is reasonable.
    futures_day_start = window_start - timedelta(days=90)
    # Crypto daily bars are currently derived from intraday history; avoid warming enormous minute
    # ranges by keeping padding small but sufficient for length=20.
    crypto_day_start = window_start - timedelta(days=30)

    assets = [
        (fut_mes, "minute", minute_start, window_end),
        (fut_mnq, "minute", minute_start, window_end),
        (fut_mes, "15minute", minute_start, window_end),
        (fut_mes, "day", futures_day_start, window_end),
        (fut_mnq, "day", futures_day_start, window_end),
        (btc, "minute", minute_start, window_end),
        (eth, "minute", minute_start, window_end),
        (sol, "minute", minute_start, window_end),
        (btc, "day", crypto_day_start, window_end),
        (eth, "day", crypto_day_start, window_end),
        (sol, "day", crypto_day_start, window_end),
    ]

    for asset, timestep, start, end in assets:
        print(
            f"WARM start asset={getattr(asset, 'symbol', asset)} type={getattr(asset, 'asset_type', '')} timestep={timestep}",
            flush=True,
        )
        df = ibkr_helper.get_price_data(
            asset=asset,
            quote=None,
            timestep=timestep,
            start_dt=start,
            end_dt=end,
            exchange=None,
            include_after_hours=True,
            source="Trades",
        )
        if df is None or df.empty:
            raise RuntimeError(f"Failed to warm {asset} timestep={timestep}: empty dataframe")
        print(f"WARM ok asset={getattr(asset, 'symbol', asset)} timestep={timestep} rows={len(df)}", flush=True)

    print("IBKR speed burner warm: OK (parquet cache populated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
