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
from lumibot.tools.parquet_series_cache import ParquetSeriesCache
from lumibot.tools.thetadata_queue_client import queue_request

logger = logging.getLogger(__name__)

CACHE_SUBFOLDER = "ibkr"

# IBKR Client Portal Gateway caps historical responses at ~1000 datapoints per call.
IBKR_HISTORY_MAX_POINTS = 1000
IBKR_DEFAULT_CRYPTO_VENUE = "ZEROHASH"
IBKR_DEFAULT_HISTORY_SOURCE = "Trades"


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
    source: Optional[str] = None,
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

    asset_type = str(getattr(asset, "asset_type", "") or "").lower()
    effective_exchange = exchange
    if asset_type in {"future", "cont_future"} and not effective_exchange:
        effective_exchange = (os.environ.get("IBKR_FUTURES_EXCHANGE") or "CME").strip().upper()
    if asset_type == "crypto" and not effective_exchange:
        effective_exchange = (os.environ.get("IBKR_CRYPTO_VENUE") or IBKR_DEFAULT_CRYPTO_VENUE).strip().upper()

    history_source = _normalize_history_source(source)

    # IMPORTANT (IBKR crypto daily semantics):
    # IBKR's `bar=1d` history is not a clean midnight-to-midnight 24/7 day series for crypto.
    # Daily-cadence strategies in LumiBot typically advance the simulation clock at midnight in
    # the strategy timezone. If we treat IBKR daily bars as authoritative, the series often
    # "ends" at a non-midnight timestamp and can lag by days, which triggers Data.checker()
    # stale-end errors and repeated refreshes (extremely slow; looks like "missing BTC data").
    #
    # Fix: for crypto only, derive daily bars from intraday history and align them to midnight
    # buckets in `LUMIBOT_DEFAULT_PYTZ`.
    if asset_type == "crypto" and _timestep_component(timestep) == "day":
        return _get_crypto_daily_bars(
            asset=asset,
            quote=quote,
            start_dt=start_utc,
            end_dt=end_utc,
            exchange=effective_exchange,
            include_after_hours=include_after_hours,
            source=history_source,
        )

    cache_file = _cache_file_for(
        asset=asset,
        quote=quote,
        timestep=timestep,
        exchange=effective_exchange,
        source=history_source,
    )
    cache_manager = get_backtest_cache()

    try:
        cache_manager.ensure_local_file(
            cache_file,
            payload=_remote_payload(asset, quote, timestep, effective_exchange, history_source),
        )
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
        segments: list[tuple[datetime, datetime]] = []
        if coverage_start is None or coverage_end is None:
            segments.append((start_utc, end_utc))
        else:
            # If the requested window has no overlap with the cached window, do NOT try to "bridge"
            # the gap. Fetch exactly the requested window and merge it into the cache as a disjoint
            # segment. Bridging can turn a 1-hour request into months of downloads.
            if end_local < coverage_start or start_local > coverage_end:
                segments.append((start_utc, end_utc))
            else:
                if start_local < coverage_start:
                    segments.append((start_utc, coverage_start.astimezone(timezone.utc)))
                if end_local > coverage_end:
                    segments.append((coverage_end.astimezone(timezone.utc), end_utc))

        for seg_start, seg_end in segments:
            if seg_start >= seg_end:
                continue
            try:
                fetched = _fetch_history_between_dates(
                    asset=asset,
                    quote=quote,
                    timestep=timestep,
                    start_dt=seg_start,
                    end_dt=seg_end,
                    exchange=effective_exchange,
                    include_after_hours=include_after_hours,
                    source=history_source,
                )
            except Exception as exc:
                # Avoid crashing the entire backtest on entitlement/session issues. Return an empty
                # frame so strategies can continue with a loud error in logs.
                logger.error(
                    "IBKR history fetch failed for %s/%s timestep=%s exchange=%s source=%s: %s",
                    getattr(asset, "symbol", None),
                    getattr(quote, "symbol", None) if quote else None,
                    timestep,
                    effective_exchange,
                    history_source,
                    exc,
                )
                fetched = pd.DataFrame()
            if fetched is not None and not fetched.empty:
                merged = _merge_frames(df_cache, fetched)
                _write_cache_frame(cache_file, merged)
                df_cache = merged

    if df_cache.empty:
        return df_cache

    # Best-effort: derive actionable bid/ask quotes for crypto *minute* bars so quote-based fills
    # behave realistically (buy at ask, sell at bid). IBKR history does not return separate
    # bid/ask fields, so we reconstruct them from Bid_Ask + Midpoint when needed.
    #
    # IMPORTANT (performance): do not do this for daily series (and avoid doing it for large
    # multi-month windows unless required) because it multiplies request volume.
    if asset_type == "crypto" and _timestep_component(timestep) == "minute":
        df_aug, changed = _maybe_augment_crypto_bid_ask(
            df_cache=df_cache,
            asset=asset,
            quote=quote,
            timestep=timestep,
            start_dt=start_utc,
            end_dt=end_utc,
            exchange=effective_exchange,
            include_after_hours=include_after_hours,
        )
        if changed:
            _write_cache_frame(cache_file, df_aug)
            df_cache = df_aug

    # Remove placeholder rows from the returned frame (but keep them in cache).
    frame = df_cache.loc[(df_cache.index >= start_local) & (df_cache.index <= end_local)].copy()
    if "missing" in frame.columns:
        frame = frame[~frame["missing"].fillna(False)]
        frame = frame.drop(columns=["missing"], errors="ignore")
    return frame


def _frame_has_actionable_bid_ask(df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False
    if "bid" not in df.columns or "ask" not in df.columns:
        return False
    bid = pd.to_numeric(df["bid"], errors="coerce")
    ask = pd.to_numeric(df["ask"], errors="coerce")
    spread = ask - bid
    return bool((spread > 0).any())


def _get_cached_bars_for_source(
    *,
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    start_dt: datetime,
    end_dt: datetime,
    exchange: Optional[str],
    include_after_hours: bool,
    source: str,
) -> pd.DataFrame:
    start_utc = _to_utc(start_dt)
    end_utc = _to_utc(end_dt)
    if start_utc > end_utc:
        start_utc, end_utc = end_utc, start_utc
    start_local = start_utc.astimezone(LUMIBOT_DEFAULT_PYTZ)
    end_local = end_utc.astimezone(LUMIBOT_DEFAULT_PYTZ)

    history_source = _normalize_history_source(source)
    cache_file = _cache_file_for(asset=asset, quote=quote, timestep=timestep, exchange=exchange, source=history_source)
    cache_manager = get_backtest_cache()
    try:
        cache_manager.ensure_local_file(
            cache_file,
            payload=_remote_payload(asset, quote, timestep, exchange, history_source),
        )
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
        segments: list[tuple[datetime, datetime]] = []
        if coverage_start is None or coverage_end is None:
            segments.append((start_utc, end_utc))
        else:
            if end_local < coverage_start or start_local > coverage_end:
                segments.append((start_utc, end_utc))
            else:
                if start_local < coverage_start:
                    segments.append((start_utc, coverage_start.astimezone(timezone.utc)))
                if end_local > coverage_end:
                    segments.append((coverage_end.astimezone(timezone.utc), end_utc))

        for seg_start, seg_end in segments:
            if seg_start >= seg_end:
                continue
            try:
                fetched = _fetch_history_between_dates(
                    asset=asset,
                    quote=quote,
                    timestep=timestep,
                    start_dt=seg_start,
                    end_dt=seg_end,
                    exchange=exchange,
                    include_after_hours=include_after_hours,
                    source=history_source,
                )
            except Exception as exc:
                logger.error(
                    "IBKR history fetch failed for %s/%s timestep=%s exchange=%s source=%s: %s",
                    getattr(asset, "symbol", None),
                    getattr(quote, "symbol", None) if quote else None,
                    timestep,
                    exchange,
                    history_source,
                    exc,
                )
                fetched = pd.DataFrame()
            if fetched is not None and not fetched.empty:
                merged = _merge_frames(df_cache, fetched)
                _write_cache_frame(cache_file, merged)
                df_cache = merged

    if df_cache.empty:
        return df_cache

    frame = df_cache.loc[(df_cache.index >= start_local) & (df_cache.index <= end_local)].copy()
    if "missing" in frame.columns:
        frame = frame[~frame["missing"].fillna(False)]
        frame = frame.drop(columns=["missing"], errors="ignore")
    return frame


def _maybe_augment_crypto_bid_ask(
    *,
    df_cache: pd.DataFrame,
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    start_dt: datetime,
    end_dt: datetime,
    exchange: Optional[str],
    include_after_hours: bool,
) -> tuple[pd.DataFrame, bool]:
    if df_cache is None or df_cache.empty:
        return df_cache, False
    if _frame_has_actionable_bid_ask(df_cache):
        return df_cache, False

    try:
        bid_ask = _get_cached_bars_for_source(
            asset=asset,
            quote=quote,
            timestep=timestep,
            start_dt=start_dt,
            end_dt=end_dt,
            exchange=exchange,
            include_after_hours=include_after_hours,
            source="Bid_Ask",
        )
        midpoint = _get_cached_bars_for_source(
            asset=asset,
            quote=quote,
            timestep=timestep,
            start_dt=start_dt,
            end_dt=end_dt,
            exchange=exchange,
            include_after_hours=include_after_hours,
            source="Midpoint",
        )
    except Exception:
        return df_cache, False

    derived = _derive_bid_ask_from_bid_ask_and_midpoint(bid_ask, midpoint)
    if derived is None or derived.empty:
        return df_cache, False

    updated = df_cache.copy()
    updated.loc[derived.index, "bid"] = derived["bid"]
    updated.loc[derived.index, "ask"] = derived["ask"]

    # Any residual NaNs fall back to the trade/mark close.
    if "close" in updated.columns:
        updated["bid"] = pd.to_numeric(updated.get("bid"), errors="coerce").where(
            ~pd.to_numeric(updated.get("bid"), errors="coerce").isna(),
            pd.to_numeric(updated.get("close"), errors="coerce"),
        )
        updated["ask"] = pd.to_numeric(updated.get("ask"), errors="coerce").where(
            ~pd.to_numeric(updated.get("ask"), errors="coerce").isna(),
            pd.to_numeric(updated.get("close"), errors="coerce"),
        )

    if not _frame_has_actionable_bid_ask(updated):
        return df_cache, False

    return updated, True


def _fetch_history_between_dates(
    *,
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    start_dt: datetime,
    end_dt: datetime,
    exchange: Optional[str],
    include_after_hours: bool,
    source: str,
) -> pd.DataFrame:
    conid = _resolve_conid(asset=asset, quote=quote, exchange=exchange)
    bar, bar_seconds, _cache_timestep = _timestep_to_ibkr_bar(timestep)
    period = _max_period_for_bar(bar)
    asset_type = str(getattr(asset, "asset_type", "") or "").lower()
    continuous = bool(asset_type == "cont_future")

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
            source=source,
        )

        # IBKR typically returns {"data":[...]} (empty list means no data).
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            # True no-data: write placeholders so we don't hammer IBKR for the same range.
            _record_missing_window(
                asset=asset,
                quote=quote,
                timestep=timestep,
                exchange=exchange,
                source=source,
                start_dt=start_dt,
                end_dt=cursor_end,
            )
            return pd.DataFrame()

        df = _history_payload_to_frame(data)
        if df.empty:
            _record_missing_window(
                asset=asset,
                quote=quote,
                timestep=timestep,
                exchange=exchange,
                source=source,
                start_dt=start_dt,
                end_dt=cursor_end,
            )
            return pd.DataFrame()

        chunks.append(df)

        earliest = df.index.min()
        if earliest is None:
            break
        if earliest <= start_dt:
            break

        # Move cursor backwards.
        #
        # IBKR history bounds are effectively inclusive, and we de-dupe on merge anyway, so it is
        # safer to continue from `earliest` instead of subtracting a whole bar (which can skip the
        # requested start boundary for coarse bars like 1h/1d).
        next_cursor_end = earliest
        if next_cursor_end >= cursor_end:
            next_cursor_end = earliest - pd.Timedelta(seconds=bar_seconds)
        cursor_end = next_cursor_end

        # Do not assume `len(df) < 1000` implies we're at the start of history.
        # IBKR can return fewer bars due to gaps/vendor behavior; breaking early can leave large
        # holes (and can trigger stale-end refresh loops in daily backtests).

    if not chunks:
        return pd.DataFrame()

    merged = pd.concat(chunks, axis=0).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    # IMPORTANT: Do not clamp to the requested window here.
    #
    # IBKR can return the "latest available" bars even when the requested window is in the
    # future (or otherwise outside the available range). We still want to persist those bars
    # to the cache to warm future requests and avoid repeatedly hammering the downloader.
    #
    # The caller (`get_price_data`) performs the final slice for the requested time range.
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
    source: str,
) -> Dict[str, Any]:
    base_url = _downloader_base_url()
    url = f"{base_url}/ibkr/iserver/marketdata/history"
    query = {
        "conid": str(int(conid)),
        "period": period,
        "bar": bar,
        "outsideRth": "true" if include_after_hours else "false",
        "source": source,
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
    # Default quote fields: treat bid/ask as the last-trade/mark series until we can derive a
    # real bid/ask spread. This ensures the quote-fill model remains functional even when
    # IBKR does not provide true NBBO history.
    if "close" in df.columns:
        df["bid"] = df["close"]
        df["ask"] = df["close"]
    return df


def _derive_bid_ask_from_bid_ask_and_midpoint(
    bid_ask: pd.DataFrame,
    midpoint: pd.DataFrame,
) -> pd.DataFrame:
    """Derive per-bar bid/ask quotes using IBKR Bid_Ask + Midpoint history.

    IBKR's Client Portal history endpoint returns OHLC bars for different "sources":
    - Trades: prints-based bars
    - Midpoint: midpoint bars
    - Bid_Ask: IBKR-style BID_ASK bars (historically: open/low use bid, close/high use ask)

    The payload does NOT include separate bid/ask fields. For backtesting fills, we want a
    stable bid/ask at each bar timestamp. The best-effort reconstruction is:
    - ask_close = Bid_Ask.close
    - mid_close = Midpoint.close
    - bid_close = 2 * mid_close - ask_close

    The result is clamped defensively to avoid negative/inverted spreads.
    """
    if bid_ask is None or bid_ask.empty or midpoint is None or midpoint.empty:
        return pd.DataFrame()
    if "close" not in bid_ask.columns or "close" not in midpoint.columns:
        return pd.DataFrame()

    joined = (
        pd.concat(
            [
                bid_ask[["close"]].rename(columns={"close": "ask_close"}),
                midpoint[["close"]].rename(columns={"close": "mid_close"}),
            ],
            axis=1,
            join="inner",
        )
        .dropna()
        .copy()
    )
    if joined.empty:
        return pd.DataFrame()

    ask = pd.to_numeric(joined["ask_close"], errors="coerce")
    mid = pd.to_numeric(joined["mid_close"], errors="coerce")
    bid = 2 * mid - ask

    out = pd.DataFrame(index=joined.index)
    out["bid"] = bid
    out["ask"] = ask

    invalid = (
        out["bid"].isna()
        | out["ask"].isna()
        | (out["bid"] <= 0)
        | (out["ask"] <= 0)
        | (out["bid"] > out["ask"])
    )
    if invalid.any():
        mid_valid = mid > 0
        use_mid = invalid & mid_valid
        out.loc[use_mid, "bid"] = mid[use_mid]
        out.loc[use_mid, "ask"] = mid[use_mid]

        # If midpoint itself is invalid (<=0), leave as NaN so callers can fall back to
        # the trade/mark close instead of propagating negative prices into fills.
        use_nan = invalid & ~mid_valid
        if use_nan.any():
            out.loc[use_nan, "bid"] = float("nan")
            out.loc[use_nan, "ask"] = float("nan")

    return out


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
    source: str,
    start_dt: datetime,
    end_dt: datetime,
) -> None:
    # Add a bracketing placeholder window (two rows) to cache.
    cache_file = _cache_file_for(asset=asset, quote=quote, timestep=timestep, exchange=exchange, source=source)
    cache_manager = get_backtest_cache()
    try:
        cache_manager.ensure_local_file(cache_file, payload=_remote_payload(asset, quote, timestep, exchange, source))
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


def _crypto_day_bounds(start_local: datetime, end_local: datetime) -> tuple[datetime, datetime]:
    """Return inclusive midnight-to-midnight day bucket bounds in `LUMIBOT_DEFAULT_PYTZ`.

    LumiBot treats BACKTESTING_END as exclusive. If the requested end timestamp is exactly
    midnight, exclude that day from the derived daily series.
    """
    start_day = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = end_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if end_local == end_day:
        end_day = end_day - pd.Timedelta(days=1)
    if end_day < start_day:
        end_day = start_day
    return start_day, end_day


def _derive_daily_from_intraday(
    intraday: pd.DataFrame,
    *,
    start_day: datetime,
    end_day: datetime,
) -> pd.DataFrame:
    """Derive daily OHLCV bars from an intraday OHLCV dataframe (crypto: 24/7 days)."""
    idx = pd.date_range(start=start_day, end=end_day, freq="D", tz=LUMIBOT_DEFAULT_PYTZ)
    if intraday is None or intraday.empty:
        out = pd.DataFrame(index=idx, columns=["open", "high", "low", "close", "volume", "missing"])
        out["missing"] = True
        return out

    df = intraday.copy()
    df.index = pd.to_datetime(df.index, utc=True, errors="coerce").tz_convert(LUMIBOT_DEFAULT_PYTZ)
    df = df[~df.index.isna()].sort_index()
    if df.empty:
        out = pd.DataFrame(index=idx, columns=["open", "high", "low", "close", "volume", "missing"])
        out["missing"] = True
        return out

    day_key = df.index.normalize()
    grouped = df.groupby(day_key)
    daily = pd.DataFrame(
        {
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(min_count=1) if "volume" in df.columns else pd.NA,
        }
    )
    daily_idx = pd.DatetimeIndex(daily.index)
    if daily_idx.tz is None:
        daily.index = daily_idx.tz_localize(LUMIBOT_DEFAULT_PYTZ)
    else:
        daily.index = daily_idx.tz_convert(LUMIBOT_DEFAULT_PYTZ)
    daily = daily.sort_index()
    daily["missing"] = False

    daily = daily.reindex(idx)
    close = pd.to_numeric(daily.get("close"), errors="coerce")
    daily["missing"] = daily["missing"].fillna(True) | close.isna()

    # IBKR crypto history is often effectively 24/5: weekend days may be absent even though
    # strategies are frequently configured as 24/7. To keep daily-cadence backtests stable
    # (no refresh loops / "missing BTC day"), forward-fill short gaps (<= 3 days) using the
    # prior close. This mirrors the existing Data.checker() tolerance window.
    if close is not None and not close.empty:
        filled_close = close.ffill(limit=3)
        filled_mask = close.isna() & filled_close.notna()
        if filled_mask.any():
            daily.loc[filled_mask, "close"] = filled_close[filled_mask]
            for col in ("open", "high", "low"):
                if col in daily.columns:
                    daily.loc[filled_mask, col] = pd.to_numeric(daily.loc[filled_mask, col], errors="coerce").fillna(
                        daily.loc[filled_mask, "close"]
                    )
            if "volume" in daily.columns:
                daily.loc[filled_mask, "volume"] = pd.to_numeric(daily.loc[filled_mask, "volume"], errors="coerce").fillna(0)
            daily.loc[filled_mask, "missing"] = False
    return daily


def _get_crypto_daily_bars(
    *,
    asset: Asset,
    quote: Optional[Asset],
    start_dt: datetime,
    end_dt: datetime,
    exchange: Optional[str],
    include_after_hours: bool,
    source: str,
) -> pd.DataFrame:
    """Return crypto daily bars aligned to midnight days in `LUMIBOT_DEFAULT_PYTZ`."""
    start_local = _to_utc(start_dt).astimezone(LUMIBOT_DEFAULT_PYTZ)
    end_local = _to_utc(end_dt).astimezone(LUMIBOT_DEFAULT_PYTZ)
    start_day, end_day = _crypto_day_bounds(start_local, end_local)

    exch = (exchange or os.environ.get("IBKR_CRYPTO_VENUE") or IBKR_DEFAULT_CRYPTO_VENUE).strip().upper()
    # IMPORTANT: keep derived daily bars in a separate cache namespace so we don't mix them with
    # legacy `bar=1d` results (which have different semantics and timestamps).
    derived_source = f"{source}_DERIVED_DAILY"
    cache_file = _cache_file_for(asset=asset, quote=quote, timestep="day", exchange=exch, source=derived_source)
    cache = ParquetSeriesCache(cache_file, remote_payload=_remote_payload(asset, quote, "day", exch, derived_source))
    cache.hydrate_remote()
    df_cache = cache.read()

    if not df_cache.empty:
        coverage_start = df_cache.index.min()
        coverage_end = df_cache.index.max()
    else:
        coverage_start = None
        coverage_end = None

    needs_fetch = (
        coverage_start is None
        or coverage_end is None
        or start_day < coverage_start
        or end_day > coverage_end
    )

    if needs_fetch:
        fetch_start = start_day if coverage_start is None else min(start_day, coverage_start)
        fetch_end = (end_day + pd.Timedelta(days=1)) if coverage_end is None else max(end_day + pd.Timedelta(days=1), coverage_end)

        hourly = _get_cached_bars_for_source(
            asset=asset,
            quote=quote,
            timestep="hour",
            start_dt=fetch_start,
            end_dt=fetch_end,
            exchange=exch,
            include_after_hours=include_after_hours,
            source=source,
        )
        daily = _derive_daily_from_intraday(hourly, start_day=fetch_start, end_day=(fetch_end - pd.Timedelta(days=1)))

        missing_days = daily.index[daily["missing"].fillna(True)]
        for day in missing_days:
            day_start = day
            day_end = day + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            minute = _get_cached_bars_for_source(
                asset=asset,
                quote=quote,
                timestep="minute",
                start_dt=day_start,
                end_dt=day_end,
                exchange=exch,
                include_after_hours=True,
                source=source,
            )
            if minute is None or minute.empty:
                continue
            filled = _derive_daily_from_intraday(minute, start_day=day_start, end_day=day_start)
            if not filled.empty and not bool(filled["missing"].iloc[0]):
                daily.loc[day_start, ["open", "high", "low", "close", "volume"]] = filled.iloc[0][
                    ["open", "high", "low", "close", "volume"]
                ]
                daily.loc[day_start, "missing"] = False

        merged = ParquetSeriesCache.merge(df_cache, daily)
        cache.write(merged, remote_payload=_remote_payload(asset, quote, "day", exch, derived_source))
        df_cache = merged

    if df_cache.empty:
        return df_cache

    frame = df_cache.loc[(df_cache.index >= start_day) & (df_cache.index <= end_day)].copy()
    if "missing" in frame.columns:
        frame = frame[~frame["missing"].fillna(False)]
        frame = frame.drop(columns=["missing"], errors="ignore")
    if "close" in frame.columns:
        frame["bid"] = pd.to_numeric(frame.get("bid", frame["close"]), errors="coerce").fillna(frame["close"])
        frame["ask"] = pd.to_numeric(frame.get("ask", frame["close"]), errors="coerce").fillna(frame["close"])
    return frame


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
        if getattr(asset, "expiration", None) is None and asset_type != "cont_future":
            raise ValueError(
                "IBKR futures require an explicit expiration on Asset(asset_type='future'). "
                "Use asset_type='cont_future' for continuous futures."
            )
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
    venue = (os.environ.get("IBKR_CRYPTO_VENUE") or IBKR_DEFAULT_CRYPTO_VENUE).strip().upper()
    desired_quote = str(getattr(quote, "symbol", "") or "").strip().upper() if quote is not None else ""
    payload = queue_request(
        url=url,
        querystring={"symbol": asset.symbol, "secType": "CRYPTO"},
        headers=None,
        timeout=None,
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected IBKR secdef/search response for crypto: {payload}")
    for entry in payload:
        entry_currency = str(entry.get("currency") or "").strip().upper()
        sections = entry.get("sections") or []
        for section in sections:
            if str(section.get("secType") or "").upper() == "CRYPTO":
                if venue:
                    exch = str(section.get("exchange") or "").upper()
                    if venue not in exch:
                        continue
                section_currency = str(section.get("currency") or "").strip().upper()
                resolved_currency = section_currency or entry_currency
                if desired_quote and resolved_currency and desired_quote != resolved_currency:
                    continue
                conid = entry.get("conid")
                if conid is not None:
                    return int(conid)
    # Fallback: accept the first conid.
    if payload and not desired_quote:
        conid = payload[0].get("conid")
        if conid is not None:
            return int(conid)
    raise RuntimeError(
        f"Unable to resolve IBKR crypto conid for {asset.symbol}/{getattr(quote,'symbol',None)} "
        f"(venue={venue or 'AUTO'})."
    )


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


def _cache_file_for(
    *,
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    exchange: Optional[str],
    source: str,
) -> Path:
    provider_root = Path(LUMIBOT_CACHE_FOLDER) / CACHE_SUBFOLDER
    asset_folder = _asset_folder(asset)
    _bar, _bar_seconds, timestep_component = _timestep_to_ibkr_bar(timestep)
    exch = (exchange or "").strip().upper() or "AUTO"
    symbol = _safe_component(getattr(asset, "symbol", "") or "symbol")
    quote_symbol = _safe_component(getattr(quote, "symbol", "") or "USD") if quote else "USD"
    expiration = getattr(asset, "expiration", None)
    exp_component = expiration.strftime("%Y%m%d") if expiration else ""
    source_component = _safe_component(source)
    suffix = f"_{exp_component}" if exp_component else ""
    filename = f"{asset_folder}_{symbol}_{quote_symbol}_{timestep_component}_{exch}_{source_component}{suffix}.parquet"
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


def _timestep_to_ibkr_bar(timestep: str) -> Tuple[str, int, str]:
    raw = (timestep or "minute").strip().lower()
    raw = raw.replace(" ", "")
    raw = raw.replace("minutes", "minute").replace("hours", "hour").replace("days", "day")

    if raw in {"minute", "1minute", "m", "1m"}:
        return "1min", 60, "minute"
    if raw.endswith("minute"):
        qty = raw.removesuffix("minute") or "1"
        minutes = int(qty)
        return f"{minutes}min", minutes * 60, f"{minutes}minute"

    if raw in {"hour", "1hour", "h", "1h"}:
        return "1h", 60 * 60, "hour"
    if raw.endswith("hour"):
        qty = raw.removesuffix("hour") or "1"
        hours = int(qty)
        return f"{hours}h", hours * 60 * 60, f"{hours}hour"

    if raw in {"day", "1day", "d", "1d"}:
        return "1d", 24 * 60 * 60, "day"
    if raw.endswith("day"):
        qty = raw.removesuffix("day") or "1"
        days = int(qty)
        return f"{days}d", days * 24 * 60 * 60, f"{days}day"

    if raw.endswith("min"):
        minutes = int(raw.removesuffix("min") or "1")
        return f"{minutes}min", minutes * 60, f"{minutes}minute"

    raise ValueError(f"Unsupported IBKR timestep: {timestep}")


def _normalize_history_source(source: Optional[str]) -> str:
    raw = (source or os.environ.get("IBKR_HISTORY_SOURCE") or IBKR_DEFAULT_HISTORY_SOURCE).strip()
    if not raw:
        return IBKR_DEFAULT_HISTORY_SOURCE
    normalized = raw.strip().lower().replace("-", "_")
    if normalized in {"trades", "trade"}:
        return "Trades"
    if normalized in {"midpoint", "mid"}:
        return "Midpoint"
    if normalized in {"bid_ask", "bidask"}:
        return "Bid_Ask"
    raise ValueError(f"Unsupported IBKR history source '{source}'. Expected Trades, Midpoint, or Bid_Ask.")


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


def _remote_payload(
    asset: Asset,
    quote: Optional[Asset],
    timestep: str,
    exchange: Optional[str],
    source: str,
) -> Dict[str, object]:
    return {
        "provider": "ibkr",
        "symbol": getattr(asset, "symbol", None),
        "asset_type": str(getattr(asset, "asset_type", "") or ""),
        "quote": getattr(quote, "symbol", None) if quote else None,
        "timestep": timestep,
        "exchange": exchange,
        "source": source,
        "expiration": getattr(asset, "expiration", None).isoformat() if getattr(asset, "expiration", None) else None,
    }


def _remote_payload_from_path(path: Path) -> Dict[str, object]:
    return {"provider": "ibkr", "path": path.as_posix()}


def _conid_key(asset: Asset, quote: Optional[Asset], exchange: Optional[str]) -> IbkrConidKey:
    asset_type = str(getattr(asset, "asset_type", "") or "").lower()
    symbol = str(getattr(asset, "symbol", "") or "")
    quote_symbol = str(getattr(quote, "symbol", "") or "") if quote else ""
    exch = (exchange or "").strip().upper()
    if asset_type == "crypto" and not exch:
        exch = (os.environ.get("IBKR_CRYPTO_VENUE") or IBKR_DEFAULT_CRYPTO_VENUE).strip().upper()
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
