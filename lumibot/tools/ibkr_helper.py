from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from lumibot.constants import LUMIBOT_CACHE_FOLDER, LUMIBOT_DEFAULT_PYTZ
from lumibot.entities import Asset
from lumibot.tools.backtest_cache import get_backtest_cache
from lumibot.tools.thetadata_queue_client import queue_request

logger = logging.getLogger(__name__)

CACHE_SUBFOLDER = "ibkr"

# IBKR Client Portal Gateway caps historical responses at ~1000 datapoints per call.
IBKR_HISTORY_MAX_POINTS = 1000


@dataclass(frozen=True)
class IbkrConidKey:
    asset_type: str
    symbol: str
    quote_symbol: str
    exchange: str
    expiration: str

    def to_key(self) -> str:
        return "|".join(
            [
                self.asset_type or "",
                self.symbol or "",
                self.quote_symbol or "",
                self.exchange or "",
                self.expiration or "",
            ]
        )


def get_price_data(
    *,
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    start_dt: datetime,
    end_dt: datetime,
    exchange: Optional[str] = None,
    include_after_hours: bool = True,
) -> pd.DataFrame:
    """Fetch IBKR historical bars (via the Data Downloader) and cache to parquet.

    This helper mirrors the ThetaData cache pattern:
    - local parquet under `LUMIBOT_CACHE_FOLDER/ibkr/...`
    - optional S3 mirroring via BacktestCacheManager
    - best-effort negative caching via `missing=True` placeholder rows (only for true NO_DATA)
    """
    start_utc = _to_utc(start_dt)
    end_utc = _to_utc(end_dt)
    if start_utc > end_utc:
        start_utc, end_utc = end_utc, start_utc
    start_local = start_utc.astimezone(LUMIBOT_DEFAULT_PYTZ)
    end_local = end_utc.astimezone(LUMIBOT_DEFAULT_PYTZ)

    cache_file = _cache_file_for(asset=asset, quote=quote, timestep=timestep, exchange=exchange)
    cache_manager = get_backtest_cache()

    try:
        cache_manager.ensure_local_file(cache_file, payload=_remote_payload(asset, quote, timestep, exchange))
    except Exception:
        pass

    df_cache = _read_cache_frame(cache_file)
    if not df_cache.empty:
        coverage_start = df_cache.index.min()
        coverage_end = df_cache.index.max()
    else:
        coverage_start = None
        coverage_end = None

    needs_fetch = (
        coverage_start is None
        or coverage_end is None
        or start_local < coverage_start
        or end_local > coverage_end
    )

    if needs_fetch:
        fetch_start = start_utc if coverage_start is None else min(start_utc, coverage_start.astimezone(timezone.utc))
        fetch_end = end_utc if coverage_end is None else max(end_utc, coverage_end.astimezone(timezone.utc))
        fetched = _fetch_history_between_dates(
            asset=asset,
            quote=quote,
            timestep=timestep,
            start_dt=fetch_start,
            end_dt=fetch_end,
            exchange=exchange,
            include_after_hours=include_after_hours,
        )
        if fetched is not None and not fetched.empty:
            merged = _merge_frames(df_cache, fetched)
            _write_cache_frame(cache_file, merged)
            df_cache = merged

    if df_cache.empty:
        return df_cache

    # Remove placeholder rows from the returned frame (but keep them in cache).
    frame = df_cache.loc[(df_cache.index >= start_local) & (df_cache.index <= end_local)].copy()
    if "missing" in frame.columns:
        frame = frame[~frame["missing"].fillna(False)]
        frame = frame.drop(columns=["missing"], errors="ignore")
    return frame


def _fetch_history_between_dates(
    *,
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    start_dt: datetime,
    end_dt: datetime,
    exchange: Optional[str],
    include_after_hours: bool,
) -> pd.DataFrame:
    conid = _resolve_conid(asset=asset, quote=quote, exchange=exchange)
    bar, bar_seconds = _timestep_to_ibkr_bar(timestep)
    period = _max_period_for_bar(bar)
    asset_type = str(getattr(asset, "asset_type", "") or "").lower()
    continuous = bool(
        asset_type == "cont_future"
        or (asset_type == "future" and getattr(asset, "expiration", None) is None)
    )

    cursor_end = _to_utc(end_dt)
    start_dt = _to_utc(start_dt)
    chunks: list[pd.DataFrame] = []

    # Fetch backwards (end -> start) to accommodate IBKR's 1000 datapoint cap.
    while cursor_end > start_dt:
        payload = _ibkr_history_request(
            conid=conid,
            period=period,
            bar=bar,
            start_time=cursor_end,
            exchange=exchange,
            include_after_hours=include_after_hours,
            continuous=continuous,
        )

        # IBKR typically returns {"data":[...]} (empty list means no data).
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            # True no-data: write placeholders so we don't hammer IBKR for the same range.
            _record_missing_window(asset=asset, quote=quote, timestep=timestep, exchange=exchange, start_dt=start_dt, end_dt=cursor_end)
            return pd.DataFrame()

        df = _history_payload_to_frame(data)
        if df.empty:
            _record_missing_window(asset=asset, quote=quote, timestep=timestep, exchange=exchange, start_dt=start_dt, end_dt=cursor_end)
            return pd.DataFrame()

        chunks.append(df)

        earliest = df.index.min()
        if earliest is None:
            break
        if earliest <= start_dt:
            break

        # Move cursor backwards, overlapping by one bar to avoid gaps from inclusive bounds.
        cursor_end = earliest - pd.Timedelta(seconds=bar_seconds)

        # If IBKR returns less than the max points, we likely reached the start of available history.
        if len(df) < IBKR_HISTORY_MAX_POINTS:
            break

    if not chunks:
        return pd.DataFrame()

    merged = pd.concat(chunks, axis=0).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged = merged.loc[(merged.index >= start_dt) & (merged.index <= end_dt)]
    return merged


def _ibkr_history_request(
    *,
    conid: int,
    period: str,
    bar: str,
    start_time: datetime,
    exchange: Optional[str],
    include_after_hours: bool,
    continuous: bool,
) -> Dict[str, Any]:
    base_url = _downloader_base_url()
    url = f"{base_url}/ibkr/iserver/marketdata/history"
    query = {
        "conid": str(int(conid)),
        "period": period,
        "bar": bar,
        "outsideRth": "true" if include_after_hours else "false",
        "startTime": start_time.strftime("%Y%m%d-%H:%M:%S"),
    }
    if continuous:
        query["continuous"] = "true"
    if exchange:
        query["exchange"] = str(exchange)

    result = queue_request(url=url, querystring=query, headers=None, timeout=None)
    if result is None:
        return {}
    if isinstance(result, dict) and result.get("error"):
        # Do not treat entitlement errors as NO_DATA; surface them to the caller.
        raise RuntimeError(f"IBKR history error: {result.get('error')}")
    return result


def _history_payload_to_frame(data: Any) -> pd.DataFrame:
    df = pd.DataFrame(data)
    if df.empty:
        return df

    # IBKR payload columns: t(ms), o, h, l, c, v.
    rename = {"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    df = df.rename(columns=rename)
    if "timestamp" not in df.columns:
        return pd.DataFrame()

    ts = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce")
    df = df.drop(columns=["timestamp"], errors="ignore")
    df.index = ts
    df = df[~df.index.isna()]
    df = df.sort_index()
    df.index = df.index.tz_convert(LUMIBOT_DEFAULT_PYTZ)
    df["missing"] = False
    return df


def _merge_frames(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        return incoming
    if incoming is None or incoming.empty:
        return existing
    merged = pd.concat([existing, incoming], axis=0).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    if "missing" in merged.columns:
        merged["missing"] = merged["missing"].fillna(False)
    return merged


def _record_missing_window(
    *,
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    exchange: Optional[str],
    start_dt: datetime,
    end_dt: datetime,
) -> None:
    # Add a bracketing placeholder window (two rows) to cache.
    cache_file = _cache_file_for(asset=asset, quote=quote, timestep=timestep, exchange=exchange)
    cache_manager = get_backtest_cache()
    try:
        cache_manager.ensure_local_file(cache_file, payload=_remote_payload(asset, quote, timestep, exchange))
    except Exception:
        pass

    df = _read_cache_frame(cache_file)
    placeholder = pd.DataFrame(
        {
            "open": [pd.NA, pd.NA],
            "high": [pd.NA, pd.NA],
            "low": [pd.NA, pd.NA],
            "close": [pd.NA, pd.NA],
            "volume": [pd.NA, pd.NA],
            "missing": [True, True],
        },
        index=pd.DatetimeIndex([_to_utc(start_dt), _to_utc(end_dt)]).tz_convert(LUMIBOT_DEFAULT_PYTZ),
    )
    merged = _merge_frames(df, placeholder)
    _write_cache_frame(cache_file, merged)


def _resolve_conid(*, asset: Asset, quote: Optional[Asset], exchange: Optional[str]) -> int:
    cache_file = Path(LUMIBOT_CACHE_FOLDER) / CACHE_SUBFOLDER / "conids.json"
    cache_manager = get_backtest_cache()
    try:
        cache_manager.ensure_local_file(cache_file, payload={"provider": "ibkr", "type": "conids"})
    except Exception:
        pass

    mapping: Dict[str, int] = {}
    if cache_file.exists():
        try:
            mapping = json.loads(cache_file.read_text(encoding="utf-8")) or {}
        except Exception:
            mapping = {}

    key = _conid_key(asset=asset, quote=quote, exchange=exchange).to_key()
    cached = mapping.get(key)
    if isinstance(cached, int) and cached > 0:
        return cached

    conid = _lookup_conid_remote(asset=asset, quote=quote, exchange=exchange)
    mapping[key] = int(conid)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
    try:
        cache_manager.on_local_update(cache_file, payload={"provider": "ibkr", "type": "conids"})
    except Exception:
        pass
    return int(conid)


def _lookup_conid_remote(*, asset: Asset, quote: Optional[Asset], exchange: Optional[str]) -> int:
    asset_type = str(getattr(asset, "asset_type", "") or "").lower()
    if asset_type in {"future", "cont_future"}:
        return _lookup_conid_future(asset=asset, exchange=exchange)
    if asset_type in {"crypto"}:
        return _lookup_conid_crypto(asset=asset, quote=quote)

    # Default: fall back to secdef search and use the first conid.
    base_url = _downloader_base_url()
    url = f"{base_url}/ibkr/iserver/secdef/search"
    payload = queue_request(url=url, querystring={"symbol": asset.symbol}, headers=None, timeout=None)
    if isinstance(payload, list) and payload:
        conid = payload[0].get("conid")
        if conid is not None:
            return int(conid)
    raise RuntimeError(f"Unable to resolve IBKR conid for {asset.symbol} (type={asset_type})")


def _lookup_conid_crypto(*, asset: Asset, quote: Optional[Asset]) -> int:
    # Best-effort: IBKR crypto availability depends on region; conid mappings differ by venue.
    base_url = _downloader_base_url()
    url = f"{base_url}/ibkr/iserver/secdef/search"
    payload = queue_request(url=url, querystring={"symbol": asset.symbol}, headers=None, timeout=None)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected IBKR secdef/search response for crypto: {payload}")
    for entry in payload:
        sections = entry.get("sections") or []
        for section in sections:
            if str(section.get("secType") or "").upper() == "CRYPTO":
                conid = entry.get("conid")
                if conid is not None:
                    return int(conid)
    # Fallback: accept the first conid.
    if payload:
        conid = payload[0].get("conid")
        if conid is not None:
            return int(conid)
    raise RuntimeError(f"Unable to resolve IBKR crypto conid for {asset.symbol}/{getattr(quote,'symbol',None)}")


def _lookup_conid_future(*, asset: Asset, exchange: Optional[str]) -> int:
    base_url = _downloader_base_url()
    url = f"{base_url}/ibkr/trsrv/futures"
    desired_exchange = exchange or "CME"
    query = {"symbols": asset.symbol, "exchange": desired_exchange, "secType": "FUT"}
    payload = queue_request(url=url, querystring=query, headers=None, timeout=None)
    # Response shape: { "<symbol>": [ {conid, expirationDate, ...}, ... ] }
    if not isinstance(payload, dict):
        # Some gateways require secType=CONTFUT to list contracts.
        payload = queue_request(
            url=url,
            querystring={"symbols": asset.symbol, "exchange": desired_exchange, "secType": "CONTFUT"},
            headers=None,
            timeout=None,
        )
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected IBKR trsrv/futures response: {payload}")
    contracts = payload.get(asset.symbol) or payload.get(asset.symbol.upper()) or []
    if not isinstance(contracts, list) or not contracts:
        raise RuntimeError(f"No futures contracts returned for {asset.symbol} on {desired_exchange}")

    expiration = getattr(asset, "expiration", None)
    if expiration is not None:
        target = expiration.strftime("%Y%m%d")
        for contract in contracts:
            if str(contract.get("expirationDate") or "") == target:
                return int(contract["conid"])

    # Default: earliest expiration (front month) – used for smoke tests like MES.
    def _exp_key(item: Dict[str, Any]) -> int:
        try:
            return int(item.get("expirationDate") or 0)
        except Exception:
            return 0

    chosen = min(contracts, key=_exp_key)
    return int(chosen["conid"])


def _cache_file_for(*, asset: Asset, quote: Optional[Asset], timestep: str, exchange: Optional[str]) -> Path:
    provider_root = Path(LUMIBOT_CACHE_FOLDER) / CACHE_SUBFOLDER
    asset_folder = _asset_folder(asset)
    timestep_component = _timestep_component(timestep)
    exch = (exchange or "").strip().upper() or "AUTO"
    symbol = _safe_component(getattr(asset, "symbol", "") or "symbol")
    quote_symbol = _safe_component(getattr(quote, "symbol", "") or "USD") if quote else "USD"
    expiration = getattr(asset, "expiration", None)
    exp_component = expiration.strftime("%Y%m%d") if expiration else ""
    filename = f"{asset_folder}_{symbol}_{quote_symbol}_{timestep_component}_{exch}{'_' + exp_component if exp_component else ''}.parquet"
    return provider_root / asset_folder / timestep_component / "bars" / filename


def _asset_folder(asset: Asset) -> str:
    asset_type = str(getattr(asset, "asset_type", "") or "").lower()
    if asset_type in {"crypto"}:
        return "crypto"
    if asset_type in {"future", "cont_future"}:
        return "future"
    return asset_type or "asset"


def _timestep_component(timestep: str) -> str:
    cleaned = str(timestep or "minute").strip().lower()
    return cleaned.replace(" ", "")


def _safe_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.upper())


def _timestep_to_ibkr_bar(timestep: str) -> Tuple[str, int]:
    raw = (timestep or "minute").strip().lower()
    raw = raw.replace(" ", "")
    raw = raw.replace("minutes", "minute").replace("hours", "hour").replace("days", "day")

    if raw in {"minute", "1minute", "m", "1m"}:
        return "1min", 60
    if raw.endswith("minute"):
        qty = raw.removesuffix("minute") or "1"
        minutes = int(qty)
        return f"{minutes}min", minutes * 60

    if raw in {"hour", "1hour", "h", "1h"}:
        return "1h", 60 * 60
    if raw.endswith("hour"):
        qty = raw.removesuffix("hour") or "1"
        hours = int(qty)
        return f"{hours}h", hours * 60 * 60

    if raw in {"day", "1day", "d", "1d"}:
        return "1d", 24 * 60 * 60
    if raw.endswith("day"):
        qty = raw.removesuffix("day") or "1"
        days = int(qty)
        return f"{days}d", days * 24 * 60 * 60

    if raw.endswith("min"):
        minutes = int(raw.removesuffix("min") or "1")
        return f"{minutes}min", minutes * 60

    raise ValueError(f"Unsupported IBKR timestep: {timestep}")


def _max_period_for_bar(bar: str) -> str:
    """Return an IBKR `period` that requests at most ~1000 datapoints for the bar size."""
    normalized = (bar or "").strip().lower()
    if normalized.endswith("min"):
        multiplier = int(normalized.removesuffix("min") or "1")
        return f"{IBKR_HISTORY_MAX_POINTS * multiplier}min"
    if normalized.endswith("h"):
        multiplier = int(normalized.removesuffix("h") or "1")
        return f"{IBKR_HISTORY_MAX_POINTS * multiplier}h"
    if normalized.endswith("d"):
        multiplier = int(normalized.removesuffix("d") or "1")
        return f"{IBKR_HISTORY_MAX_POINTS * multiplier}d"
    return f"{IBKR_HISTORY_MAX_POINTS}min"


def _read_cache_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if not isinstance(df.index, pd.DatetimeIndex):
        # Defensive: older caches might have a column index.
        if "datetime" in df.columns:
            df = df.set_index(pd.to_datetime(df["datetime"], utc=True, errors="coerce"))
            df = df.drop(columns=["datetime"], errors="ignore")
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[~df.index.isna()]
    df = df.sort_index()
    df.index = df.index.tz_convert(LUMIBOT_DEFAULT_PYTZ)
    if "missing" in df.columns:
        df["missing"] = df["missing"].fillna(False)
    else:
        df["missing"] = False
    return df


def _write_cache_frame(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df_to_save = df.copy()
    if not isinstance(df_to_save.index, pd.DatetimeIndex):
        raise ValueError("IBKR cache frames must be indexed by datetime")
    df_to_save.to_parquet(path)
    try:
        get_backtest_cache().on_local_update(path, payload=_remote_payload_from_path(path))
    except Exception:
        pass


def _remote_payload(asset: Asset, quote: Optional[Asset], timestep: str, exchange: Optional[str]) -> Dict[str, object]:
    return {
        "provider": "ibkr",
        "symbol": getattr(asset, "symbol", None),
        "asset_type": str(getattr(asset, "asset_type", "") or ""),
        "quote": getattr(quote, "symbol", None) if quote else None,
        "timestep": timestep,
        "exchange": exchange,
        "expiration": getattr(asset, "expiration", None).isoformat() if getattr(asset, "expiration", None) else None,
    }


def _remote_payload_from_path(path: Path) -> Dict[str, object]:
    return {"provider": "ibkr", "path": path.as_posix()}


def _conid_key(asset: Asset, quote: Optional[Asset], exchange: Optional[str]) -> IbkrConidKey:
    asset_type = str(getattr(asset, "asset_type", "") or "").lower()
    symbol = str(getattr(asset, "symbol", "") or "")
    quote_symbol = str(getattr(quote, "symbol", "") or "") if quote else ""
    exch = (exchange or "").strip().upper()
    expiration = ""
    if getattr(asset, "expiration", None) is not None:
        try:
            expiration = asset.expiration.strftime("%Y%m%d")  # type: ignore[union-attr]
        except Exception:
            expiration = str(asset.expiration)
    return IbkrConidKey(
        asset_type=asset_type,
        symbol=symbol,
        quote_symbol=quote_symbol,
        exchange=exch,
        expiration=expiration,
    )


def _downloader_base_url() -> str:
    return os.environ.get("DATADOWNLOADER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _to_utc(dt_value: datetime) -> datetime:
    if isinstance(dt_value, pd.Timestamp):
        dt_value = dt_value.to_pydatetime()
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=LUMIBOT_DEFAULT_PYTZ)
    return dt_value.astimezone(timezone.utc)
