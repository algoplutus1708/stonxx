"""Build a split-adjusted daily Yahoo Finance panel for Indian equities.

This script downloads a diversified NSE cash-equity universe plus a benchmark
index and saves a long-form parquet dataset that can be fed directly into the
daily swing-model trainer.
"""

from __future__ import annotations

import argparse
import os
from typing import Callable

import pandas as pd
import yfinance as yf

DEFAULT_UNIVERSE = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "ITC.NS",
    "SUNPHARMA.NS",
    "LT.NS",
    "TATAMOTORS.NS",
    "HINDUNILVR.NS",
    "BHARTIARTL.NS",
    "MARUTI.NS",
    "AXISBANK.NS",
    "ASIANPAINT.NS",
]
DEFAULT_BENCHMARK = "^NSEI"
DEFAULT_OUTPUT_PATH = "data/stonxx_daily_panel_yf.parquet"
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def normalize_symbol(ticker: str) -> str:
    """Map Yahoo ticker strings back to the plain NSE symbol used by the bot."""
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker.rsplit(".", 1)[0].upper()
    return ticker.upper()


def normalize_history_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalize a yfinance response into a tz-aware daily OHLCV frame."""
    if raw.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        try:
            df.columns = df.columns.droplevel(1)
        except Exception:
            df.columns = [col[0] for col in df.columns]

    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
        "Adj Close": "adj_close",
    }
    df = df.rename(columns=rename_map)

    # When auto_adjust=True, Close is already corporate-action adjusted.
    if "close" not in df.columns and "adj_close" in df.columns:
        df["close"] = df["adj_close"]

    for column in OHLCV_COLUMNS:
        if column not in df.columns:
            raise ValueError(f"{ticker} is missing required column '{column}'")

    df = df[OHLCV_COLUMNS].copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("Asia/Kolkata")
    else:
        df.index = df.index.tz_convert("Asia/Kolkata")
    df.index = df.index.normalize()
    df.index.name = "datetime"
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def fetch_symbol_history(
    ticker: str,
    *,
    start: str | None = None,
    end: str | None = None,
    period: str = "max",
    interval: str = "1d",
    auto_adjust: bool = True,
    download_fn: Callable[..., pd.DataFrame] = yf.download,
) -> pd.DataFrame:
    """Fetch one symbol from Yahoo Finance and normalize its columns."""
    kwargs = {
        "tickers": ticker,
        "interval": interval,
        "auto_adjust": auto_adjust,
        "progress": False,
        "actions": False,
    }
    if start or end:
        kwargs["start"] = start
        kwargs["end"] = end
    else:
        kwargs["period"] = period

    raw = download_fn(**kwargs)
    return normalize_history_frame(raw, ticker)


def build_panel_from_histories(
    histories: dict[str, pd.DataFrame],
    *,
    benchmark_ticker: str = DEFAULT_BENCHMARK,
) -> pd.DataFrame:
    """Build a long-form stock panel with a same-day benchmark close."""
    if benchmark_ticker not in histories:
        raise ValueError(f"Benchmark {benchmark_ticker} was not provided")

    benchmark = histories[benchmark_ticker].copy()
    if benchmark.empty:
        raise ValueError(f"Benchmark {benchmark_ticker} returned no data")

    benchmark = benchmark[["close"]].rename(columns={"close": "benchmark_close"})
    benchmark.index.name = "datetime"

    frames = []
    for ticker, history in histories.items():
        if ticker == benchmark_ticker or history.empty:
            continue
        merged = history.join(benchmark, how="inner")
        if merged.empty:
            continue
        merged = merged.reset_index()
        merged["ticker"] = normalize_symbol(ticker)
        merged["benchmark_ticker"] = benchmark_ticker
        frames.append(merged)

    if not frames:
        return pd.DataFrame(
            columns=["datetime", "ticker", *OHLCV_COLUMNS, "benchmark_close", "benchmark_ticker"]
        )

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["datetime", "ticker"]).reset_index(drop=True)
    return panel


def fetch_data(
    *,
    tickers: list[str] | None = None,
    benchmark_ticker: str = DEFAULT_BENCHMARK,
    start: str | None = None,
    end: str | None = None,
    period: str = "max",
    output_path: str = DEFAULT_OUTPUT_PATH,
    auto_adjust: bool = True,
    download_fn: Callable[..., pd.DataFrame] = yf.download,
) -> pd.DataFrame:
    """Download the default research universe and save the resulting panel."""
    symbols = list(tickers or DEFAULT_UNIVERSE)
    if benchmark_ticker not in symbols:
        symbols.append(benchmark_ticker)

    histories: dict[str, pd.DataFrame] = {}
    for ticker in symbols:
        print(f"Fetching {ticker}...")
        history = fetch_symbol_history(
            ticker,
            start=start,
            end=end,
            period=period,
            auto_adjust=auto_adjust,
            download_fn=download_fn,
        )
        if history.empty:
            print(f"  [WARN] No data returned for {ticker}")
        else:
            print(
                f"  [OK] {len(history):,} rows | "
                f"{history.index.min().date()} -> {history.index.max().date()}"
            )
        histories[ticker] = history

    panel = build_panel_from_histories(histories, benchmark_ticker=benchmark_ticker)
    if panel.empty:
        raise RuntimeError("Yahoo fetch completed but produced an empty stock panel")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    panel.to_parquet(output_path, index=False)

    print(f"\nSaved {len(panel):,} panel rows for {panel['ticker'].nunique()} stocks.")
    print(f"Date range: {panel['datetime'].min()} -> {panel['datetime'].max()}")
    print(f"Output: {output_path}")
    return panel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        help="Optional Yahoo tickers to override the default diversified universe.",
    )
    parser.add_argument("--benchmark", default=DEFAULT_BENCHMARK, help="Benchmark Yahoo ticker.")
    parser.add_argument("--start", default=None, help="Optional start date (YYYY-MM-DD).")
    parser.add_argument("--end", default=None, help="Optional end date (YYYY-MM-DD).")
    parser.add_argument("--period", default="max", help="Yahoo period when start/end are omitted.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Output parquet path.")
    parser.add_argument(
        "--raw-prices",
        action="store_true",
        help="Disable auto-adjustment. The default uses split/dividend-adjusted prices.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fetch_data(
        tickers=args.tickers,
        benchmark_ticker=args.benchmark,
        start=args.start,
        end=args.end,
        period=args.period,
        output_path=args.output,
        auto_adjust=not args.raw_prices,
    )


if __name__ == "__main__":
    main()
