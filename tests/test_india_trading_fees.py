"""
tests/test_india_trading_fees.py
=================================
Unit / regression tests for the Indian equity trading fee model.

Run with::

    pytest tests/test_india_trading_fees.py -v

No network calls, no broker credentials required.
"""

import math
import pytest

from lumibot.entities import IndiaTradingFee, make_india_equity_fees, TradingFee
from lumibot.entities.india_trading_fees import (
    _GST_RATE,
    _MARKET_SLIPPAGE_PCT,
    _SEBI_FEE_PCT,
    _NSE_MIS,
    _NSE_CNC,
    _BSE_MIS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expected_pct(rates, side: str, no_slip: bool = False) -> float:
    """Replicate _regulatory_pct + slippage so tests are independent of internals."""
    bkr   = rates.brokerage_pct
    stt   = rates.stt_buy_pct if side == "buy" else rates.stt_sell_pct
    exch  = rates.exchange_charge_pct
    gst   = _GST_RATE * (bkr + exch)
    sebi  = _SEBI_FEE_PCT
    stamp = rates.stamp_duty_buy_pct if side == "buy" else 0.0
    reg   = bkr + stt + exch + gst + sebi + stamp
    return reg if no_slip else reg + _MARKET_SLIPPAGE_PCT


# ---------------------------------------------------------------------------
# 1. Inheritance
# ---------------------------------------------------------------------------

class TestInheritance:
    def test_is_trading_fee_subclass(self):
        fee = IndiaTradingFee()
        assert isinstance(fee, TradingFee)

    def test_decimal_percent_fee(self):
        """percent_fee must be a Decimal (Lumibot broker expects this)."""
        from decimal import Decimal
        fee = IndiaTradingFee("MIS", "NSE", "buy")
        assert isinstance(fee.percent_fee, Decimal)

    def test_flat_fee_is_zero(self):
        from decimal import Decimal
        fee = IndiaTradingFee("MIS", "NSE", "sell")
        assert fee.flat_fee == Decimal("0")

    def test_per_contract_fee_is_zero(self):
        from decimal import Decimal
        fee = IndiaTradingFee("CNC", "NSE", "buy")
        assert fee.per_contract_fee == Decimal("0")


# ---------------------------------------------------------------------------
# 2. MIS / NSE effective percentages
# ---------------------------------------------------------------------------

class TestNSE_MIS:
    """All four order-type × side combos for NSE MIS."""

    def test_buy_market_effective_pct(self):
        fee = IndiaTradingFee("MIS", "NSE", "buy", maker=False, taker=True,
                              include_slippage=True)
        expected = _expected_pct(_NSE_MIS, "buy", no_slip=False)
        assert math.isclose(float(fee.percent_fee), expected, rel_tol=1e-9)

    def test_buy_limit_effective_pct(self):
        fee = IndiaTradingFee("MIS", "NSE", "buy", maker=True, taker=False,
                              include_slippage=False)
        expected = _expected_pct(_NSE_MIS, "buy", no_slip=True)
        assert math.isclose(float(fee.percent_fee), expected, rel_tol=1e-9)

    def test_sell_market_effective_pct(self):
        fee = IndiaTradingFee("MIS", "NSE", "sell", maker=False, taker=True,
                              include_slippage=True)
        expected = _expected_pct(_NSE_MIS, "sell", no_slip=False)
        assert math.isclose(float(fee.percent_fee), expected, rel_tol=1e-9)

    def test_sell_limit_effective_pct(self):
        fee = IndiaTradingFee("MIS", "NSE", "sell", maker=True, taker=False,
                              include_slippage=False)
        expected = _expected_pct(_NSE_MIS, "sell", no_slip=True)
        assert math.isclose(float(fee.percent_fee), expected, rel_tol=1e-9)

    def test_stt_zero_on_buy_side(self):
        """MIS intraday: STT is NOT charged on the buy side."""
        assert _NSE_MIS.stt_buy_pct == 0.0

    def test_stt_nonzero_on_sell_side(self):
        assert _NSE_MIS.stt_sell_pct == 0.00025


# ---------------------------------------------------------------------------
# 3. CNC / NSE effective percentages
# ---------------------------------------------------------------------------

class TestNSE_CNC:
    def test_brokerage_zero(self):
        """Free delivery — brokerage component must be 0."""
        assert _NSE_CNC.brokerage_pct == 0.0
        assert _NSE_CNC.brokerage_cap_inr == 0.0

    def test_stt_both_sides(self):
        assert _NSE_CNC.stt_buy_pct  == 0.001
        assert _NSE_CNC.stt_sell_pct == 0.001

    def test_buy_market_pct(self):
        fee = IndiaTradingFee("CNC", "NSE", "buy", maker=False, taker=True,
                              include_slippage=True)
        expected = _expected_pct(_NSE_CNC, "buy", no_slip=False)
        assert math.isclose(float(fee.percent_fee), expected, rel_tol=1e-9)

    def test_sell_limit_pct(self):
        fee = IndiaTradingFee("CNC", "NSE", "sell", maker=True, taker=False,
                              include_slippage=False)
        expected = _expected_pct(_NSE_CNC, "sell", no_slip=True)
        assert math.isclose(float(fee.percent_fee), expected, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 4. BSE variants
# ---------------------------------------------------------------------------

class TestBSE:
    def test_bse_exchange_charge_differs_from_nse(self):
        assert _BSE_MIS.exchange_charge_pct != _NSE_MIS.exchange_charge_pct
        assert _BSE_MIS.exchange_charge_pct == pytest.approx(0.0000375, rel=1e-6)

    def test_bse_mis_buy_market(self):
        fee = IndiaTradingFee("MIS", "BSE", "buy", maker=False, taker=True,
                              include_slippage=True)
        expected = _expected_pct(_BSE_MIS, "buy", no_slip=False)
        assert math.isclose(float(fee.percent_fee), expected, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 5. NRML product type (equity NRML ≡ MIS)
# ---------------------------------------------------------------------------

class TestNRML:
    def test_nrml_same_as_mis(self):
        mis_fee  = IndiaTradingFee("MIS",  "NSE", "buy")
        nrml_fee = IndiaTradingFee("NRML", "NSE", "buy")
        assert mis_fee.percent_fee == nrml_fee.percent_fee


# ---------------------------------------------------------------------------
# 6. Slippage toggle
# ---------------------------------------------------------------------------

class TestSlippage:
    def test_slippage_off_when_maker_only(self):
        """Maker-only fee must not carry slippage even if include_slippage=True."""
        fee = IndiaTradingFee("MIS", "NSE", "buy", maker=True, taker=False,
                              include_slippage=True)
        # slippage should be zero because taker=False
        assert fee._slippage_pct == 0.0

    def test_slippage_included_in_taker(self):
        fee = IndiaTradingFee("MIS", "NSE", "sell", maker=False, taker=True,
                              include_slippage=True)
        assert fee._slippage_pct == pytest.approx(_MARKET_SLIPPAGE_PCT)

    def test_slippage_disabled_globally(self):
        fee = IndiaTradingFee("MIS", "NSE", "buy", taker=True,
                              include_slippage=False)
        assert fee._slippage_pct == 0.0

    def test_sell_market_has_higher_effective_pct_than_limit(self):
        taker = IndiaTradingFee("MIS", "NSE", "sell", maker=False, taker=True)
        maker = IndiaTradingFee("MIS", "NSE", "sell", maker=True,  taker=False,
                                include_slippage=False)
        assert float(taker.percent_fee) > float(maker.percent_fee)


# ---------------------------------------------------------------------------
# 7. Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_product_type(self):
        with pytest.raises(ValueError, match="product_type"):
            IndiaTradingFee("MARGIN")

    def test_invalid_exchange(self):
        with pytest.raises(ValueError, match="exchange"):
            IndiaTradingFee("MIS", "MCX")

    def test_invalid_side(self):
        with pytest.raises(ValueError, match="side"):
            IndiaTradingFee("MIS", "NSE", "long")


# ---------------------------------------------------------------------------
# 8. Breakdown helper
# ---------------------------------------------------------------------------

class TestBreakdown:
    def setup_method(self):
        self.fee = IndiaTradingFee("MIS", "NSE", "buy", maker=False, taker=True,
                                   include_slippage=True)
        self.bd  = self.fee.breakdown(price=1000.0, quantity=10.0)

    def test_turnover_correct(self):
        assert self.bd["turnover_inr"] == pytest.approx(10_000.0)

    def test_brokerage_cap(self):
        """0.03% × ₹200,000 = ₹60 → exceeds ₹20 cap → capped at ₹20."""
        # Use a large order to guarantee raw_bkr > ₹20
        bd_large = self.fee.breakdown(price=2000.0, quantity=100.0)  # ₹200k turnover
        assert bd_large["brokerage_cap_applied"] is True
        assert bd_large["brokerage_inr"] == pytest.approx(20.0)

    def test_brokerage_uncapped_small_order(self):
        """0.03% × ₹100 = ₹0.03 — well below ₹20 cap → no cap applied."""
        bd_small = self.fee.breakdown(price=10.0, quantity=10.0)  # ₹100 turnover
        assert bd_small["brokerage_cap_applied"] is False
        assert bd_small["brokerage_inr"] == pytest.approx(0.03, rel=1e-6)

    def test_stt_zero_buy_mis(self):
        assert self.bd["stt_inr"] == pytest.approx(0.0)

    def test_gst_on_brokerage_plus_exchange(self):
        expected_gst = _GST_RATE * (self.bd["brokerage_inr"] + self.bd["exchange_charges_inr"])
        assert self.bd["gst_inr"] == pytest.approx(expected_gst, rel=1e-4)

    def test_slippage_in_breakdown(self):
        expected_slip = _MARKET_SLIPPAGE_PCT * 10_000.0
        assert self.bd["slippage_penalty_inr"] == pytest.approx(expected_slip, rel=1e-6)

    def test_total_equals_sum_of_parts(self):
        parts = (
            self.bd["brokerage_inr"]
            + self.bd["stt_inr"]
            + self.bd["exchange_charges_inr"]
            + self.bd["gst_inr"]
            + self.bd["sebi_fee_inr"]
            + self.bd["stamp_duty_inr"]
        )
        assert self.bd["total_statutory_inr"] == pytest.approx(parts, rel=1e-6)

    def test_total_with_slippage(self):
        expected = self.bd["total_statutory_inr"] + self.bd["slippage_penalty_inr"]
        assert self.bd["total_with_slippage_inr"] == pytest.approx(expected, rel=1e-6)

    def test_brokerage_cap_flag(self):
        """₹10k turnover: 0.03% = ₹3 → cap NOT applied."""
        bd_small = self.fee.breakdown(price=10.0, quantity=10.0)  # ₹100 turnover
        assert bd_small["brokerage_cap_applied"] is False

    def test_stamp_duty_nonzero_on_buy(self):
        assert self.bd["stamp_duty_inr"] > 0.0

    def test_stamp_duty_zero_on_sell(self):
        sell_fee = IndiaTradingFee("MIS", "NSE", "sell")
        bd = sell_fee.breakdown(price=1000.0, quantity=10.0)
        assert bd["stamp_duty_inr"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 9. make_india_equity_fees factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_returns_two_lists(self):
        buy_fees, sell_fees = make_india_equity_fees("MIS")
        assert isinstance(buy_fees,  list)
        assert isinstance(sell_fees, list)

    def test_each_list_has_two_elements(self):
        buy_fees, sell_fees = make_india_equity_fees("CNC")
        assert len(buy_fees)  == 2
        assert len(sell_fees) == 2

    def test_first_element_is_taker(self):
        buy_fees, _ = make_india_equity_fees("MIS")
        taker = buy_fees[0]
        assert taker.taker is True
        assert taker.maker is False

    def test_second_element_is_maker(self):
        buy_fees, _ = make_india_equity_fees("MIS")
        maker = buy_fees[1]
        assert maker.maker is True
        assert maker.taker is False

    def test_taker_has_slippage(self):
        buy_fees, _ = make_india_equity_fees("MIS", include_slippage=True)
        assert buy_fees[0]._slippage_pct > 0.0

    def test_maker_no_slippage(self):
        buy_fees, _ = make_india_equity_fees("MIS", include_slippage=True)
        assert buy_fees[1]._slippage_pct == 0.0

    def test_slippage_disabled_factory(self):
        buy_fees, sell_fees = make_india_equity_fees("MIS", include_slippage=False)
        for f in buy_fees + sell_fees:
            assert f._slippage_pct == 0.0

    def test_all_objects_are_india_trading_fee(self):
        buy_fees, sell_fees = make_india_equity_fees("CNC", "BSE")
        for f in buy_fees + sell_fees:
            assert isinstance(f, IndiaTradingFee)

    def test_bse_factory(self):
        buy_fees, _ = make_india_equity_fees("MIS", "BSE")
        assert buy_fees[0].exchange == "BSE"

    def test_sell_market_fee_exceeds_buy_market_mis(self):
        """MIS: STT on sell > 0, on buy = 0 → sell taker must cost more."""
        buy_fees, sell_fees = make_india_equity_fees("MIS")
        assert float(sell_fees[0].percent_fee) > float(buy_fees[0].percent_fee)

    def test_cnc_brokerage_zero_reflected(self):
        """CNC: no brokerage, so both sides should have identical brokerage component."""
        buy_fees, sell_fees = make_india_equity_fees("CNC")
        for f in buy_fees + sell_fees:
            assert f._rates.brokerage_pct == 0.0

    def test_repr_contains_key_info(self):
        fee = IndiaTradingFee("MIS", "NSE", "buy", maker=False, taker=True)
        r = repr(fee)
        assert "MIS" in r
        assert "NSE" in r
        assert "BUY" in r
