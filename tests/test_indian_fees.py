"""
tests/test_indian_fees.py
=========================
Comprehensive pytest suite for Indian Equity Fees edge cases using mock Orders,
matching mathematical outputs down to 2 decimal places.
"""
import pytest
from lumibot.entities.india_trading_fees import make_india_equity_fees

class MockAsset:
    def __init__(self, symbol="TEST"):
        self.symbol = symbol

class MockOrder:
    def __init__(self, quantity, side, order_type="market"):
        self.quantity = quantity
        self.side = side
        self.order_type = order_type
        self.asset = MockAsset()
        self.identifier = "mock-id-123"

def test_1_share_order():
    """Test extreme edge case: 1-share order."""
    # 1-share BUY MIS ₹2500
    buy_fees, _ = make_india_equity_fees("MIS", "NSE")
    taker_fee = buy_fees[0]
    
    order = MockOrder(quantity=1, side="buy", order_type="market")
    result = taker_fee.calculate_for_order(order, fill_price=2500.0)
    
    # Assert breakdown to 2 decimal places
    # Brokerage (0.03%): 0.75
    # STT: 0
    # Exch (0.0000345): 0.08625 -> ~0.0863
    # GST (18% on B+Ex): 0.150525
    # SEBI (0.000001): 0.0025
    # Stamp: 0.075
    # Total statutory: 0.75 + 0.08625 + 0.150525 + 0.0025 + 0.075 = 1.064275
    # Slippage: +0.05% * 2500 = 1.25 -> Total: 2.314275
    assert round(result["total_statutory_inr"], 2) == 1.06
    assert round(result["total_inr"], 2) == 2.31

def test_100k_share_intraday_order():
    """Test extreme edge case: Intraday order of 100,000 shares."""
    # 100,000-share BUY MIS ₹500
    buy_fees, _ = make_india_equity_fees("MIS", "NSE")
    taker_fee = buy_fees[0]
    
    order = MockOrder(quantity=100_000, side="buy", order_type="market")
    result = taker_fee.calculate_for_order(order, fill_price=500.0)
    
    # Turnover: 50,000,000
    # Raw Brokerage: 15,000 -> Capped at 20!
    assert result["brokerage_cap_applied"] is True
    assert round(result["brokerage_inr"], 2) == 20.00
    
    # Statutory: 20(cap) + 1725(exch) + 314.1(gst) + 50(sebi) + 1500(stamp) = 3609.1
    assert round(result["total_statutory_inr"], 2) == 3609.10
    
    # Slippage: 25000 -> Total: 28609.1
    assert round(result["total_inr"], 2) == 28609.10

def test_delivery_order():
    """Test delivery (CNC) order."""
    # 100-share BUY CNC ₹1000
    buy_fees, _ = make_india_equity_fees("CNC", "NSE")
    taker_fee = buy_fees[0]
    
    order = MockOrder(quantity=100, side="buy", order_type="market")
    result = taker_fee.calculate_for_order(order, fill_price=1000.0)
    
    # Turnover: 100,000
    # Brokerage: 0
    # STT: 100
    # Exch: 3.45
    # GST: 0.621
    # SEBI: 0.1
    # Stamp: 15
    # Statutory: 119.171
    # Slippage: 50
    assert round(result["brokerage_inr"], 2) == 0.00
    assert round(result["total_statutory_inr"], 2) == 119.17
    assert round(result["total_inr"], 2) == 169.17

def test_malformed_order_zero_division_guard():
    """Test robust try/except blocks for missing metadata/zeros."""
    buy_fees, _ = make_india_equity_fees("MIS")
    taker_fee = buy_fees[0]
    
    class BadOrder:
        pass
        
    # Bad order should safely return zero values via the exception block
    # and not crash the bot
    result = taker_fee.calculate_for_order(BadOrder(), fill_price=100.0)
    assert result["error"] is not None
    assert "missing quantity" in result["error"]
    assert result["total_inr"] == 0.0
    
    bad_order_qty_zero = MockOrder(quantity=0, side="buy")
    result_zero = taker_fee.calculate_for_order(bad_order_qty_zero, fill_price=100.0)
    assert result_zero["error"] is not None
    assert "non-positive quantity" in result_zero["error"]
    assert result_zero["total_inr"] == 0.0
