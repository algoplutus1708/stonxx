import numpy as np
import pandas as pd

from lumibot.tools.indicators import cagr, stats_summary, volatility


def _make_returns_df(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame({"return": [0.0, 1.0]}, index=index)


def _expected_cagr(start: pd.Timestamp, end: pd.Timestamp, total_return: float) -> float:
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    period_years = (end - start).days / 365.25
    return (1 + total_return) ** (1 / period_years) - 1


def test_cagr_supports_datetime64_us_index():
    """Regression: numpy datetime64[us] -> .astype('O') yields datetime.datetime (no / support)."""
    arr_us = np.array(
        ["2026-01-01T00:00:00.000000", "2027-01-01T00:00:00.000000"],
        dtype="datetime64[us]",
    )
    df = _make_returns_df(pd.Index(arr_us))

    value = cagr(df)
    assert isinstance(value, float)
    assert value != 0
    assert abs(value - _expected_cagr(pd.Timestamp("2026-01-01"), pd.Timestamp("2027-01-01"), total_return=1.0)) < 1e-12


def test_cagr_supports_datetime64_s_index():
    """Regression: datetime64[s] should not crash CAGR/volatility computations."""
    arr_s = np.array(["2026-01-01T00:00:00", "2027-01-01T00:00:00"], dtype="datetime64[s]")
    df = _make_returns_df(pd.Index(arr_s))

    value = cagr(df)
    assert isinstance(value, float)
    assert value != 0
    assert abs(value - _expected_cagr(pd.Timestamp("2026-01-01"), pd.Timestamp("2027-01-01"), total_return=1.0)) < 1e-12


def test_volatility_supports_datetime64_us_index():
    arr_us = np.array(
        ["2026-01-01T00:00:00.000000", "2027-01-01T00:00:00.000000"],
        dtype="datetime64[us]",
    )
    df = _make_returns_df(pd.Index(arr_us))

    value = volatility(df)
    assert isinstance(value, float)
    assert value != 0


def test_stats_summary_supports_datetime64_us_index():
    arr_us = np.array(
        ["2026-01-01T00:00:00.000000", "2027-01-01T00:00:00.000000"],
        dtype="datetime64[us]",
    )
    df = _make_returns_df(pd.Index(arr_us))

    result = stats_summary(df, risk_free_rate=0.0)
    assert set(result) == {"cagr", "volatility", "sharpe", "max_drawdown", "romad", "total_return"}
    assert result["cagr"] != 0
