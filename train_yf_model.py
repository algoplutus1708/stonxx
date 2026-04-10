"""Train a leak-aware daily baseline model for the Indian swing-trading panel.

The baseline predicts each stock's 5-trading-day forward return from a
split-adjusted daily Yahoo Finance panel. Validation is done with expanding
walk-forward splits plus an embargo gap so train dates always precede
validation dates globally across the entire stock panel. Training is hard-capped
at 2023-12-31 so 2024+ rows stay strictly out of sample.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, r2_score
from xgboost import XGBRegressor

DEFAULT_PANEL_PATH = "data/stonxx_daily_panel_yf.parquet"
DEFAULT_MODEL_PATH = "stonxx_daily_panel_model.joblib"
TRAIN_CUTOFF_DATE = "2023-12-31"
FORWARD_HORIZON_DAYS = 5
BENCHMARK_TICKER = "^NSEI"
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

FEATURE_COLUMNS = [
    "vol_norm_momentum",
    "rsi_5",
    "benchmark_alpha",
    "atr_pct_20",
    "volume_ratio_20",
]

XGB_PARAMS = {
    "objective": "reg:squarederror",
    "n_estimators": 300,
    "max_depth": 3,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 20,
    "reg_alpha": 0.5,
    "reg_lambda": 2.0,
    "random_state": 42,
}


@dataclass(frozen=True)
class TemporalSplit:
    fold: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    train_mask: np.ndarray
    validation_mask: np.ndarray


def _download_default_price_panel(output_path: Path) -> None:
    """Generate the default Yahoo Finance panel at the requested path."""
    from yf_historical_fetcher import fetch_data

    fetch_data(output_path=str(output_path))


def load_price_panel(path: str = DEFAULT_PANEL_PATH) -> pd.DataFrame:
    """Load the daily stock panel saved by yf_historical_fetcher.py.

    If the default panel path is missing, build it automatically with the
    Yahoo fetcher so the trainer can run end-to-end from a clean checkout.
    """
    panel_path = Path(path)
    default_panel_path = Path(DEFAULT_PANEL_PATH).resolve(strict=False)

    if not panel_path.exists():
        if panel_path.resolve(strict=False) != default_panel_path:
            raise FileNotFoundError(
                f"Panel file not found: {panel_path}. Run `python yf_historical_fetcher.py --output {panel_path}` "
                "or point --panel-path at an existing parquet file."
            )

        print(f"[train_yf_model] Missing default panel {panel_path}; building it now.")
        _download_default_price_panel(panel_path)

    if not panel_path.exists():
        raise FileNotFoundError(
            f"Panel file could not be created: {panel_path}. Run `python yf_historical_fetcher.py` and try again."
        )

    frame = pd.read_parquet(panel_path)
    required = {"datetime", "ticker", "open", "high", "low", "close", "volume", "benchmark_close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Panel file is missing required columns: {sorted(missing)}")

    frame = frame.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    frame = frame.sort_values(["ticker", "datetime"]).reset_index(drop=True)
    return frame


def apply_training_cutoff(panel: pd.DataFrame, cutoff_date: str = TRAIN_CUTOFF_DATE) -> pd.DataFrame:
    """Drop all rows strictly after the out-of-sample training cutoff."""
    frame = panel.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"])

    cutoff = pd.Timestamp(cutoff_date) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    tzinfo = getattr(frame["datetime"].dt, "tz", None)
    if tzinfo is not None:
        cutoff = cutoff.tz_localize(tzinfo)

    filtered = frame.loc[frame["datetime"] <= cutoff].copy()
    if filtered.empty:
        raise ValueError(f"No rows remain on or before training cutoff {cutoff_date}")

    filtered = filtered.sort_values(["ticker", "datetime"]).reset_index(drop=True)
    return filtered


def compute_rsi(series: pd.Series, length: int) -> pd.Series:
    """Compute Wilder RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(avg_gain != 0.0, 0.0)
    return rsi


def compute_true_range(group: pd.DataFrame) -> pd.Series:
    """Compute daily true range."""
    prev_close = group["close"].shift(1)
    high_low = group["high"] - group["low"]
    high_close = (group["high"] - prev_close).abs()
    low_close = (group["low"] - prev_close).abs()
    return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)


def normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize one OHLCV history frame to lowercase daily columns."""
    normalized = frame.copy()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    missing = [column for column in OHLCV_COLUMNS if column not in normalized.columns]
    if missing:
        raise ValueError(f"History frame is missing required OHLCV columns: {missing}")

    if "datetime" in normalized.columns:
        normalized["datetime"] = pd.to_datetime(normalized["datetime"])
        normalized = normalized.set_index("datetime")

    normalized.index = pd.to_datetime(normalized.index)
    normalized.index.name = "datetime"
    normalized = normalized[OHLCV_COLUMNS].sort_index()
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    return normalized


def _prepare_feature_frame(
    panel: pd.DataFrame,
    *,
    forward_horizon_days: int,
    include_target: bool,
) -> pd.DataFrame:
    """Build the shared feature matrix for training or live inference."""
    frame = panel.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    frame = frame.sort_values(["ticker", "datetime"]).reset_index(drop=True)

    benchmark = (
        frame[["datetime", "benchmark_close"]]
        .drop_duplicates(subset=["datetime"])
        .sort_values("datetime")
        .reset_index(drop=True)
    )
    benchmark["benchmark_return_30"] = benchmark["benchmark_close"].pct_change(30)
    benchmark["benchmark_forward_return_5d"] = (
        benchmark["benchmark_close"].shift(-forward_horizon_days) / benchmark["benchmark_close"] - 1.0
    )
    frame = frame.drop(columns=["benchmark_close"]).merge(benchmark, on="datetime", how="left")

    by_ticker = frame.groupby("ticker", group_keys=False)
    prev_close = by_ticker["close"].shift(1)
    frame["true_range"] = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["sma_20"] = by_ticker["close"].transform(lambda s: s.rolling(20).mean())
    frame["atr_20"] = by_ticker["true_range"].transform(lambda s: s.rolling(20).mean())
    frame["vol_norm_momentum"] = (frame["close"] - frame["sma_20"]) / frame["atr_20"].replace(0.0, np.nan)
    frame["rsi_5"] = by_ticker["close"].transform(lambda s: compute_rsi(s, 5))
    frame["stock_return_30"] = by_ticker["close"].transform(lambda s: s.pct_change(30))
    frame["benchmark_alpha"] = frame["stock_return_30"] - frame["benchmark_return_30"]
    frame["atr_pct_20"] = frame["atr_20"] / frame["close"].replace(0.0, np.nan)
    frame["volume_ratio_20"] = frame["volume"] / by_ticker["volume"].transform(lambda s: s.rolling(20).mean())
    output_columns = ["datetime", "ticker", *FEATURE_COLUMNS]
    if include_target:
        frame["target_forward_return_5d"] = by_ticker["close"].transform(
            lambda s: s.shift(-forward_horizon_days) / s - 1.0
        )
        output_columns.extend(["target_forward_return_5d", "benchmark_forward_return_5d"])

    model_frame = frame[output_columns].dropna()
    model_frame = model_frame.sort_values(["datetime", "ticker"]).reset_index(drop=True)
    return model_frame


def prepare_training_frame(
    panel: pd.DataFrame,
    *,
    forward_horizon_days: int = FORWARD_HORIZON_DAYS,
) -> pd.DataFrame:
    """Build the feature matrix and 5-day forward return target."""
    return _prepare_feature_frame(
        panel,
        forward_horizon_days=forward_horizon_days,
        include_target=True,
    )


def prepare_symbol_inference_frame(
    stock_history: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    *,
    ticker: str = "LIVE",
) -> pd.DataFrame:
    """Build the exact live feature frame for one symbol and the benchmark."""
    stock = normalize_history_frame(stock_history).reset_index()
    stock["ticker"] = ticker

    benchmark = normalize_history_frame(benchmark_history)[["close"]].rename(columns={"close": "benchmark_close"})
    benchmark = benchmark.reset_index()
    panel = stock.merge(benchmark, on="datetime", how="inner")

    return _prepare_feature_frame(
        panel,
        forward_horizon_days=FORWARD_HORIZON_DAYS,
        include_target=False,
    )


def generate_temporal_splits(
    frame: pd.DataFrame,
    *,
    n_splits: int = 4,
    min_train_days: int = 504,
    validation_window_days: int = 126,
    embargo_days: int = FORWARD_HORIZON_DAYS,
) -> list[TemporalSplit]:
    """Create expanding walk-forward splits with a global-date embargo."""
    unique_dates = pd.Index(sorted(pd.to_datetime(frame["datetime"]).unique()))
    min_required = min_train_days + embargo_days + validation_window_days
    if len(unique_dates) < min_required:
        raise ValueError(f"Need at least {min_required} unique dates, found {len(unique_dates)}")

    max_train_end_position = len(unique_dates) - embargo_days - validation_window_days - 1
    candidate_positions = np.linspace(
        min_train_days - 1,
        max_train_end_position,
        num=n_splits,
        dtype=int,
    )

    splits: list[TemporalSplit] = []
    seen_train_end_positions: set[int] = set()
    for fold_number, train_end_position in enumerate(candidate_positions, start=1):
        if train_end_position in seen_train_end_positions:
            continue
        seen_train_end_positions.add(train_end_position)

        validation_start_position = train_end_position + embargo_days + 1
        validation_end_position = validation_start_position + validation_window_days - 1
        if validation_end_position >= len(unique_dates):
            continue

        train_start = unique_dates[0]
        train_end = unique_dates[train_end_position]
        validation_start = unique_dates[validation_start_position]
        validation_end = unique_dates[validation_end_position]

        datetimes = pd.to_datetime(frame["datetime"])
        train_mask = (datetimes >= train_start) & (datetimes <= train_end)
        validation_mask = (datetimes >= validation_start) & (datetimes <= validation_end)
        splits.append(
            TemporalSplit(
                fold=fold_number,
                train_start=pd.Timestamp(train_start),
                train_end=pd.Timestamp(train_end),
                validation_start=pd.Timestamp(validation_start),
                validation_end=pd.Timestamp(validation_end),
                train_mask=train_mask.to_numpy(),
                validation_mask=validation_mask.to_numpy(),
            )
        )

    if not splits:
        raise ValueError("No valid temporal splits could be created")

    return splits


def _make_model() -> XGBRegressor:
    return XGBRegressor(**XGB_PARAMS)


def compute_top_k_excess_return(
    validation_frame: pd.DataFrame,
    predictions: np.ndarray,
    *,
    top_k: int = 3,
) -> float:
    """Measure average excess 5-day return of the top-ranked names per date."""
    scored = validation_frame[["datetime", "ticker", "target_forward_return_5d", "benchmark_forward_return_5d"]].copy()
    scored["prediction"] = predictions

    selected_returns = []
    for _, bucket in scored.groupby("datetime"):
        candidates = bucket[bucket["prediction"] > 0].sort_values("prediction", ascending=False).head(top_k)
        if candidates.empty:
            continue
        excess = candidates["target_forward_return_5d"] - candidates["benchmark_forward_return_5d"]
        selected_returns.append(excess.mean())

    if not selected_returns:
        return float("nan")
    return float(np.mean(selected_returns))


def evaluate_fold(validation_frame: pd.DataFrame, predictions: np.ndarray) -> dict[str, float]:
    """Compute regression and ranking metrics for one validation fold."""
    actual = validation_frame["target_forward_return_5d"].to_numpy()
    pred_sign = predictions > 0
    actual_sign = actual > 0
    directional_accuracy = float(np.mean(pred_sign == actual_sign))

    predicted_series = pd.Series(predictions)
    actual_series = pd.Series(actual)
    if predicted_series.nunique(dropna=True) <= 1 or actual_series.nunique(dropna=True) <= 1:
        spearman_ic = float("nan")
    else:
        spearman_ic = float(predicted_series.corr(actual_series, method="spearman"))
    mse = float(mean_squared_error(actual, predictions))
    rmse = float(np.sqrt(mse))
    r2 = float(r2_score(actual, predictions))

    return {
        "mse": mse,
        "rmse": rmse,
        "r2": r2,
        "directional_accuracy": directional_accuracy,
        "spearman_ic": spearman_ic,
        "top_3_excess_return": compute_top_k_excess_return(validation_frame, predictions, top_k=3),
    }


def nanmean_or_nan(values: list[float]) -> float:
    """Return nanmean without emitting warnings when every value is NaN."""
    array = np.asarray(values, dtype=float)
    if np.isnan(array).all():
        return float("nan")
    return float(np.nanmean(array))


def train_baseline_model(
    *,
    panel_path: str = DEFAULT_PANEL_PATH,
    model_path: str = DEFAULT_MODEL_PATH,
    n_splits: int = 4,
    min_train_days: int = 504,
    validation_window_days: int = 126,
    embargo_days: int = FORWARD_HORIZON_DAYS,
) -> dict:
    """Train and persist the daily XGBoost baseline."""
    panel = load_price_panel(panel_path)
    panel = apply_training_cutoff(panel)
    frame = prepare_training_frame(panel, forward_horizon_days=FORWARD_HORIZON_DAYS)
    splits = generate_temporal_splits(
        frame,
        n_splits=n_splits,
        min_train_days=min_train_days,
        validation_window_days=validation_window_days,
        embargo_days=embargo_days,
    )

    print(f"Loaded panel rows through {TRAIN_CUTOFF_DATE}: {len(panel):,}")
    print(f"Training rows after feature prep: {len(frame):,}")
    print(f"Stocks in panel: {frame['ticker'].nunique()}")
    print(f"Feature columns: {FEATURE_COLUMNS}")

    fold_results: list[dict] = []
    for split in splits:
        train_frame = frame.iloc[split.train_mask]
        validation_frame = frame.iloc[split.validation_mask]

        model = _make_model()
        model.fit(train_frame[FEATURE_COLUMNS], train_frame["target_forward_return_5d"])
        predictions = model.predict(validation_frame[FEATURE_COLUMNS])
        metrics = evaluate_fold(validation_frame, predictions)

        result = {
            "fold": split.fold,
            "train_start": split.train_start.strftime("%Y-%m-%d"),
            "train_end": split.train_end.strftime("%Y-%m-%d"),
            "validation_start": split.validation_start.strftime("%Y-%m-%d"),
            "validation_end": split.validation_end.strftime("%Y-%m-%d"),
            **metrics,
        }
        fold_results.append(result)

        print(
            f"\nFold {split.fold}: "
            f"train {result['train_start']} -> {result['train_end']} | "
            f"validation {result['validation_start']} -> {result['validation_end']}"
        )
        print(
            "  "
            f"MSE={result['mse']:.6f} | RMSE={result['rmse']:.6f} | "
            f"R2={result['r2']:.4f} | DirAcc={result['directional_accuracy']:.4f} | "
            f"IC={result['spearman_ic']:.4f} | Top3Excess={result['top_3_excess_return']:.4f}"
        )

    final_model = _make_model()
    final_model.fit(frame[FEATURE_COLUMNS], frame["target_forward_return_5d"])
    importance = {
        feature: round(float(score), 6) for feature, score in zip(FEATURE_COLUMNS, final_model.feature_importances_)
    }

    mean_metrics = {
        key: round(
            nanmean_or_nan([result[key] for result in fold_results]),
            6,
        )
        for key in ["mse", "rmse", "r2", "directional_accuracy", "spearman_ic", "top_3_excess_return"]
    }

    artifact = {
        "model": final_model,
        "features": FEATURE_COLUMNS,
        "meta": {
            "panel_path": panel_path,
            "model_type": "XGBRegressor",
            "benchmark_ticker": BENCHMARK_TICKER,
            "forward_horizon_days": FORWARD_HORIZON_DAYS,
            "embargo_days": embargo_days,
            "validation_window_days": validation_window_days,
            "n_splits": len(fold_results),
            "stocks": sorted(frame["ticker"].unique().tolist()),
            "train_start": frame["datetime"].min().strftime("%Y-%m-%d"),
            "train_end": frame["datetime"].max().strftime("%Y-%m-%d"),
            "mean_metrics": mean_metrics,
            "feature_importance": importance,
        },
        "cv_results": fold_results,
    }
    joblib.dump(artifact, model_path)

    print("\nSaved baseline artifact:")
    print(f"  Path: {model_path}")
    print(f"  Mean metrics: {mean_metrics}")
    print(f"  Feature importance: {importance}")
    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-path", default=DEFAULT_PANEL_PATH, help="Input panel parquet path.")
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH, help="Output model artifact path.")
    parser.add_argument("--n-splits", type=int, default=4, help="Number of expanding walk-forward folds.")
    parser.add_argument("--min-train-days", type=int, default=504, help="Minimum unique training dates before fold 1.")
    parser.add_argument(
        "--validation-window-days",
        type=int,
        default=126,
        help="Unique trading dates in each validation window.",
    )
    parser.add_argument(
        "--embargo-days",
        type=int,
        default=FORWARD_HORIZON_DAYS,
        help="Gap between train end and validation start.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_baseline_model(
        panel_path=args.panel_path,
        model_path=args.model_path,
        n_splits=args.n_splits,
        min_train_days=args.min_train_days,
        validation_window_days=args.validation_window_days,
        embargo_days=args.embargo_days,
    )


if __name__ == "__main__":
    main()
