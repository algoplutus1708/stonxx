import numpy as np
import pandas as pd
import pytest

from train_yf_model import (
    FEATURE_COLUMNS,
    FORWARD_HORIZON_DAYS,
    generate_temporal_splits,
    prepare_training_frame,
    prepare_symbol_inference_frame,
)
from yf_historical_fetcher import build_panel_from_histories


def _make_history(start_price: float, step: float, periods: int = 80) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=periods, tz="Asia/Kolkata")
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


def test_build_panel_from_histories_merges_benchmark_and_normalizes_symbols():
    histories = {
        "^NSEI": _make_history(20_000.0, 4.0),
        "RELIANCE.NS": _make_history(2_400.0, 1.5),
        "INFY.NS": _make_history(1_600.0, 1.0),
    }

    panel = build_panel_from_histories(histories, benchmark_ticker="^NSEI")

    assert not panel.empty
    assert sorted(panel["ticker"].unique().tolist()) == ["INFY", "RELIANCE"]
    assert panel["benchmark_ticker"].unique().tolist() == ["^NSEI"]
    assert panel["benchmark_close"].notna().all()
    assert panel["datetime"].is_monotonic_increasing


def test_prepare_training_frame_creates_features_and_forward_target():
    histories = {
        "^NSEI": _make_history(20_000.0, 4.0, periods=90),
        "RELIANCE.NS": _make_history(2_400.0, 2.0, periods=90),
        "INFY.NS": _make_history(1_600.0, 1.25, periods=90),
    }
    panel = build_panel_from_histories(histories, benchmark_ticker="^NSEI")

    model_frame = prepare_training_frame(panel, forward_horizon_days=FORWARD_HORIZON_DAYS)

    assert not model_frame.empty
    assert set(FEATURE_COLUMNS).issubset(model_frame.columns)
    assert model_frame["benchmark_forward_return_5d"].notna().all()

    reliance_rows = model_frame[model_frame["ticker"] == "RELIANCE"].sort_values("datetime").reset_index(drop=True)
    sample_row = reliance_rows.iloc[0]

    raw_prices = histories["RELIANCE.NS"]["close"].reset_index(drop=True)
    raw_benchmark = histories["^NSEI"]["close"].reset_index(drop=True)

    # The first modeled row appears after the 30-day lookback warmup.
    source_position = 30
    expected_target = raw_prices.iloc[source_position + FORWARD_HORIZON_DAYS] / raw_prices.iloc[source_position] - 1.0
    expected_stock_return_30 = raw_prices.iloc[source_position] / raw_prices.iloc[source_position - 30] - 1.0
    expected_benchmark_return_30 = (
        raw_benchmark.iloc[source_position] / raw_benchmark.iloc[source_position - 30] - 1.0
    )

    assert sample_row["target_forward_return_5d"] == pytest.approx(expected_target)
    assert sample_row["benchmark_alpha"] == pytest.approx(
        expected_stock_return_30 - expected_benchmark_return_30
    )


def test_generate_temporal_splits_respects_embargo_gap():
    histories = {
        "^NSEI": _make_history(20_000.0, 4.0, periods=120),
        "RELIANCE.NS": _make_history(2_400.0, 2.0, periods=120),
        "INFY.NS": _make_history(1_600.0, 1.25, periods=120),
        "SBIN.NS": _make_history(700.0, 0.8, periods=120),
    }
    panel = build_panel_from_histories(histories, benchmark_ticker="^NSEI")
    model_frame = prepare_training_frame(panel, forward_horizon_days=FORWARD_HORIZON_DAYS)

    splits = generate_temporal_splits(
        model_frame,
        n_splits=3,
        min_train_days=30,
        validation_window_days=15,
        embargo_days=5,
    )

    unique_dates = pd.Index(sorted(pd.to_datetime(model_frame["datetime"]).unique()))
    assert len(splits) == 3

    for split in splits:
        train_dates = pd.to_datetime(model_frame.loc[split.train_mask, "datetime"])
        validation_dates = pd.to_datetime(model_frame.loc[split.validation_mask, "datetime"])

        assert train_dates.max() == split.train_end
        assert validation_dates.min() == split.validation_start
        assert train_dates.max() < validation_dates.min()

        train_pos = unique_dates.get_loc(split.train_end)
        validation_pos = unique_dates.get_loc(split.validation_start)
        assert validation_pos - train_pos == 6


def test_prepare_symbol_inference_frame_matches_training_features():
    histories = {
        "^NSEI": _make_history(20_000.0, 4.0, periods=90),
        "RELIANCE.NS": _make_history(2_400.0, 2.0, periods=90),
        "INFY.NS": _make_history(1_600.0, 1.25, periods=90),
    }
    panel = build_panel_from_histories(histories, benchmark_ticker="^NSEI")
    training_frame = prepare_training_frame(panel, forward_horizon_days=FORWARD_HORIZON_DAYS)

    live_frame = prepare_symbol_inference_frame(
        histories["RELIANCE.NS"],
        histories["^NSEI"],
        ticker="RELIANCE",
    )

    training_symbol = training_frame[training_frame["ticker"] == "RELIANCE"].sort_values("datetime")
    live_symbol = live_frame.sort_values("datetime")
    comparison_datetime = training_symbol.iloc[-1]["datetime"]

    training_last = training_symbol[training_symbol["datetime"] == comparison_datetime].iloc[-1][FEATURE_COLUMNS]
    live_last = live_symbol[live_symbol["datetime"] == comparison_datetime].iloc[-1][FEATURE_COLUMNS]

    assert list(live_frame.columns) == ["datetime", "ticker", *FEATURE_COLUMNS]
    assert live_symbol["datetime"].max() > training_symbol["datetime"].max()
    for feature in FEATURE_COLUMNS:
        assert live_last[feature] == pytest.approx(training_last[feature])
