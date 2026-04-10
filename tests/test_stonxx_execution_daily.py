from datetime import date

from lumibot.example_strategies.stonxx_india_bot import (
    compute_order_quantity,
    next_trading_day,
    rank_long_candidates,
)


def test_compute_order_quantity_respects_risk_and_notional_caps():
    quantity = compute_order_quantity(
        portfolio_value=1_000_000.0,
        current_price=2_000.0,
        atr_20=20.0,
        available_cash=1_000_000.0,
        risk_budget_pct=0.01,
        max_position_pct=0.10,
    )

    # Risk budget allows 500 shares, but the 10% notional cap limits us to 50.
    assert quantity == 50


def test_compute_order_quantity_respects_available_cash():
    quantity = compute_order_quantity(
        portfolio_value=1_000_000.0,
        current_price=2_000.0,
        atr_20=20.0,
        available_cash=30_000.0,
        risk_budget_pct=0.01,
        max_position_pct=0.10,
    )

    assert quantity == 15


def test_rank_long_candidates_filters_negative_and_low_conviction_signals():
    signals = [
        {"symbol": "A", "predicted_return": 0.032},
        {"symbol": "B", "predicted_return": -0.005},
        {"symbol": "C", "predicted_return": 0.011},
        {"symbol": "D", "predicted_return": 0.008},
    ]

    ranked = rank_long_candidates(
        signals,
        minimum_predicted_return=0.01,
        max_positions=2,
    )

    assert [item["symbol"] for item in ranked] == ["A", "C"]


def test_next_trading_day_skips_weekend():
    assert next_trading_day(date(2026, 4, 10)).isoformat() == "2026-04-13"
