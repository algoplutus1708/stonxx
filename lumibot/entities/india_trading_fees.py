"""
india_trading_fees.py
=====================
Indian Equity Trading Fee Model for Lumibot — NSE / BSE.

Implements every SEBI-regulated cost component for both intraday
(MIS / NRML) and delivery (CNC) equity trading.

Charge components (FY 2025-26, both NSE and BSE):
    - Brokerage          : ₹20 flat OR 0.03% whichever is lower (MIS/NRML)
                           ₹0 for delivery (CNC)
    - STT                : Securities Transaction Tax (side-dependent)
    - Exchange charges   : NSE 0.00345 % / BSE 0.00375 % per side
    - GST                : 18 % on (brokerage + exchange charges)
    - SEBI turnover fee  : ₹10 per crore (= 0.0001 %)
    - Stamp duty         : Buy side only (MIS 0.003 %, CNC 0.015 %)
    - Market-order slippage: 0.05 % of turnover (taker/market orders only)

Usage
-----
::

    from lumibot.entities.india_trading_fees import make_india_equity_fees

    buy_fees, sell_fees = make_india_equity_fees("MIS")       # intraday NSE
    buy_fees, sell_fees = make_india_equity_fees("CNC")       # delivery NSE
    buy_fees, sell_fees = make_india_equity_fees("MIS","BSE") # intraday BSE

    result = MyStrategy.backtest(
        YahooDataBacktesting,
        backtesting_start, backtesting_end,
        buy_trading_fees  = buy_fees,
        sell_trading_fees = sell_fees,
    )

Fee architecture
----------------
Lumibot evaluates each ``TradingFee`` as::

    trade_cost = flat_fee
               + price × qty × percent_fee
               + qty   × per_contract_fee

``make_india_equity_fees`` returns two lists — buy and sell — each
containing a *taker* object (market/stop orders, includes slippage) and a
*maker* object (limit/stop-limit orders, no slippage).

Brokerage cap note
------------------
The ₹20 cap on brokerage applies when turnover > ₹66,667
(i.e. 0.03 % × ₹66,667 ≈ ₹20).  Because Lumibot applies ``percent_fee``
uniformly, the 0.03 % rate is used.  For very large single orders this
slightly overstates brokerage (conservative / safe approach).
The ``breakdown()`` helper calculates the exact capped brokerage for
reporting / verification purposes.

References
----------
* Zerodha brokerage calculator: https://zerodha.com/brokerage-calculator
* NSE circular on transaction charges: NSE/CLER/46236/2023
"""

from __future__ import annotations

from dataclasses import dataclass

from lumibot.entities.trading_fee import TradingFee

# ---------------------------------------------------------------------------
# Rate constants  (all values as decimal fractions; 1 % == 0.01)
# ---------------------------------------------------------------------------

#: Slippage penalty applied only to market / stop (taker) orders.
_MARKET_SLIPPAGE_PCT: float = 0.0005   # 0.05 %

#: GST rate on brokerage + exchange charges (statutory, fixed since 2017).
_GST_RATE: float = 0.18                # 18 %

#: SEBI turnover fee: ₹10 per crore = 1e-7 per rupee.
_SEBI_FEE_PCT: float = 0.000001        # 0.0001 %


@dataclass(frozen=True)
class _FeeRates:
    """Immutable rate container for one product-type / exchange combination."""

    # Brokerage ─────────────────────────────────────────────────────────────
    brokerage_pct:     float   # percentage of turnover (0.03 % → 0.0003)
    brokerage_cap_inr: float   # ₹ cap per order (0 = unlimited / zero)

    # STT ────────────────────────────────────────────────────────────────────
    stt_buy_pct:  float        # STT on buy side
    stt_sell_pct: float        # STT on sell side

    # Exchange transaction charge ────────────────────────────────────────────
    exchange_charge_pct: float # applied to both sides

    # Stamp duty (buy side only) ─────────────────────────────────────────────
    stamp_duty_buy_pct: float


# ── NSE MIS / Intraday ──────────────────────────────────────────────────────
_NSE_MIS = _FeeRates(
    brokerage_pct     = 0.0003,     # 0.03 % (capped at ₹20)
    brokerage_cap_inr = 20.0,
    stt_buy_pct       = 0.0,        # STT not charged on buy side for MIS
    stt_sell_pct      = 0.00025,    # 0.025 % on sell side (intraday)
    exchange_charge_pct = 0.0000345,# 0.00345 % — NSE equity cash segment
    stamp_duty_buy_pct = 0.00003,   # 0.003 %
)

# ── NSE CNC / Delivery ──────────────────────────────────────────────────────
_NSE_CNC = _FeeRates(
    brokerage_pct     = 0.0,        # Free delivery (Zerodha / Dhan style)
    brokerage_cap_inr = 0.0,
    stt_buy_pct       = 0.001,      # 0.1 % on both sides for delivery
    stt_sell_pct      = 0.001,
    exchange_charge_pct = 0.0000345,
    stamp_duty_buy_pct = 0.00015,   # 0.015 %
)

# ── BSE MIS / Intraday ──────────────────────────────────────────────────────
_BSE_MIS = _FeeRates(
    brokerage_pct     = 0.0003,
    brokerage_cap_inr = 20.0,
    stt_buy_pct       = 0.0,
    stt_sell_pct      = 0.00025,
    exchange_charge_pct = 0.0000375,# 0.00375 % — BSE equity cash segment
    stamp_duty_buy_pct = 0.00003,
)

# ── BSE CNC / Delivery ──────────────────────────────────────────────────────
_BSE_CNC = _FeeRates(
    brokerage_pct     = 0.0,
    brokerage_cap_inr = 0.0,
    stt_buy_pct       = 0.001,
    stt_sell_pct      = 0.001,
    exchange_charge_pct = 0.0000375,
    stamp_duty_buy_pct = 0.00015,
)

_RATES_MAP: dict[tuple[str, str], _FeeRates] = {
    ("NSE", "MIS"):  _NSE_MIS,
    ("NSE", "NRML"): _NSE_MIS,   # NRML equity ≡ MIS for charges
    ("NSE", "CNC"):  _NSE_CNC,
    ("BSE", "MIS"):  _BSE_MIS,
    ("BSE", "NRML"): _BSE_MIS,
    ("BSE", "CNC"):  _BSE_CNC,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _regulatory_pct(rates: _FeeRates, side: str) -> float:
    """Return the total regulatory cost fraction for a given side.

    Uses the percentage form of brokerage (0.03 %).  The ₹20 cap causes a
    *slight over-charge* only for orders with turnover > ₹66,667; the
    error is at most (0.0003 × turnover − 20) / turnover → bounded and
    conservative.
    """
    bkr      = rates.brokerage_pct
    stt      = rates.stt_buy_pct if side == "buy" else rates.stt_sell_pct
    exch     = rates.exchange_charge_pct
    gst      = _GST_RATE * (bkr + exch)
    sebi     = _SEBI_FEE_PCT
    stamp    = rates.stamp_duty_buy_pct if side == "buy" else 0.0
    return bkr + stt + exch + gst + sebi + stamp


# ---------------------------------------------------------------------------
# IndiaTradingFee
# ---------------------------------------------------------------------------

class IndiaTradingFee(TradingFee):
    """TradingFee subclass encoding all Indian equity regulatory costs.

    Parameters
    ----------
    product_type : str
        ``"MIS"`` (intraday) | ``"NRML"`` (overnight margin) | ``"CNC"`` (delivery).
    exchange : str
        ``"NSE"`` (default) | ``"BSE"``.
    side : str
        ``"buy"`` or ``"sell"``.  Determines which STT / stamp duty rate applies.
    maker : bool
        Apply this fee to limit / stop-limit orders.  Default ``True``.
    taker : bool
        Apply this fee to market / stop orders.  Default ``True``.
    include_slippage : bool
        Add the 0.05 % market-order slippage penalty (affects taker orders
        only; ignored for maker-only instances).  Default ``True``.

    Examples
    --------
    >>> from lumibot.entities.india_trading_fees import make_india_equity_fees
    >>> buy_fees, sell_fees = make_india_equity_fees("MIS")
    >>> # Pass directly to backtest() or Trader
    """

    def __init__(
        self,
        product_type: str = "MIS",
        exchange: str = "NSE",
        side: str = "buy",
        maker: bool = True,
        taker: bool = True,
        include_slippage: bool = True,
    ) -> None:
        product  = str(product_type).strip().upper()
        exch     = str(exchange).strip().upper()
        side_key = str(side).strip().lower()

        # ── Validate inputs ─────────────────────────────────────────────────
        if product not in ("MIS", "CNC", "NRML"):
            raise ValueError(
                f"product_type must be 'MIS', 'CNC', or 'NRML'; got {product_type!r}"
            )
        if exch not in ("NSE", "BSE"):
            raise ValueError(f"exchange must be 'NSE' or 'BSE'; got {exchange!r}")
        if side_key not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell'; got {side!r}")

        # ── Look up rate table ───────────────────────────────────────────────
        rates = _RATES_MAP[(exch, product)]

        # ── Compute effective percentage ─────────────────────────────────────
        reg_pct       = _regulatory_pct(rates, side_key)
        # Slippage is a cost that mimics the spread penalty on market orders.
        # It is included only when this object covers taker (market) orders.
        slip_pct      = _MARKET_SLIPPAGE_PCT if (include_slippage and taker) else 0.0
        total_pct     = reg_pct + slip_pct

        # ── Persist metadata for breakdown / repr ────────────────────────────
        self.product_type       = product
        self.exchange           = exch
        self.side               = side_key
        self._rates             = rates
        self._regulatory_pct    = reg_pct
        self._slippage_pct      = slip_pct
        self._include_slippage  = include_slippage

        # flat_fee = 0: see "Brokerage cap note" in module docstring.
        super().__init__(
            flat_fee         = 0.0,
            percent_fee      = total_pct,
            per_contract_fee = 0.0,
            maker            = maker,
            taker            = taker,
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def breakdown(self, price: float = 1000.0, quantity: float = 10.0) -> dict:
        """Return an itemised cost breakdown for the given trade parameters.

        This method uses the *exact* brokerage cap (max ₹20) rather than
        the percentage approximation, so it may differ slightly from what
        the backtesting engine deducts for large orders.

        Parameters
        ----------
        price : float
            Share price in INR (default ₹1,000).
        quantity : float
            Number of shares (default 10).

        Returns
        -------
        dict
            Keys: component → INR amount, plus totals and effective rate.

        Example
        -------
        >>> from lumibot.entities.india_trading_fees import IndiaTradingFee
        >>> fee = IndiaTradingFee("MIS", side="buy")
        >>> fee.breakdown(price=2500, quantity=40)
        """
        rates    = self._rates
        side     = self.side
        turnover = price * quantity

        # Exact brokerage with cap
        raw_bkr   = rates.brokerage_pct * turnover
        brokerage = (
            min(raw_bkr, rates.brokerage_cap_inr)
            if rates.brokerage_cap_inr > 0
            else raw_bkr
        )

        stt    = (rates.stt_buy_pct if side == "buy" else rates.stt_sell_pct) * turnover
        exch   = rates.exchange_charge_pct * turnover
        gst    = _GST_RATE * (brokerage + exch)
        sebi   = _SEBI_FEE_PCT * turnover
        stamp  = (rates.stamp_duty_buy_pct * turnover) if side == "buy" else 0.0
        slip   = self._slippage_pct * turnover

        total_statutory     = brokerage + stt + exch + gst + sebi + stamp
        total_with_slippage = total_statutory + slip

        return {
            "product_type":              self.product_type,
            "exchange":                  self.exchange,
            "side":                      side.upper(),
            "turnover_inr":              round(turnover, 2),
            # ── Itemised charges ────────────────────────────────────────────
            "brokerage_inr":             round(brokerage, 4),
            "stt_inr":                   round(stt, 4),
            "exchange_charges_inr":      round(exch, 4),
            "gst_inr":                   round(gst, 4),
            "sebi_fee_inr":              round(sebi, 4),
            "stamp_duty_inr":            round(stamp, 4),
            "slippage_penalty_inr":      round(slip, 4),
            # ── Totals ──────────────────────────────────────────────────────
            "total_statutory_inr":       round(total_statutory, 4),
            "total_with_slippage_inr":   round(total_with_slippage, 4),
            "effective_cost_pct":        round(float(self.percent_fee) * 100, 6),
            # ── Notes ───────────────────────────────────────────────────────
            "brokerage_cap_applied":     (raw_bkr > rates.brokerage_cap_inr
                                          and rates.brokerage_cap_inr > 0),
            "applies_to_order_types":    (
                "market/stop" if (self.taker and not self.maker) else
                "limit/stop-limit" if (self.maker and not self.taker) else
                "all orders"
            ),
        }

    def __repr__(self) -> str:
        return (
            f"IndiaTradingFee("
            f"product={self.product_type}, "
            f"exchange={self.exchange}, "
            f"side={self.side.upper()}, "
            f"effective={float(self.percent_fee)*100:.5f}%, "
            f"slippage={'yes' if self._slippage_pct else 'no'}, "
            f"maker={self.maker}, taker={self.taker})"
        )


# ---------------------------------------------------------------------------
# Factory function  ← recommended entry point
# ---------------------------------------------------------------------------

def make_india_equity_fees(
    product_type: str = "MIS",
    exchange: str = "NSE",
    include_slippage: bool = True,
) -> tuple[list[IndiaTradingFee], list[IndiaTradingFee]]:
    """Build ``(buy_fees, sell_fees)`` ready for Lumibot backtesting.

    Each returned list contains **two** ``IndiaTradingFee`` objects:

    * **Taker** instance  — applied to market / stop orders.
      Includes the 0.05 % slippage penalty when ``include_slippage=True``.
    * **Maker** instance  — applied to limit / stop-limit orders.
      No slippage penalty regardless of ``include_slippage``.

    Parameters
    ----------
    product_type : str
        ``"MIS"`` (intraday) | ``"NRML"`` | ``"CNC"`` (delivery).
    exchange : str
        ``"NSE"`` (default) | ``"BSE"``.
    include_slippage : bool
        Add 0.05 % slippage to market-order fills.  Default ``True``.

    Returns
    -------
    tuple[list[IndiaTradingFee], list[IndiaTradingFee]]
        ``(buy_fees, sell_fees)`` — pass directly to ``strategy.backtest()``.

    Examples
    --------
    >>> from lumibot.entities.india_trading_fees import make_india_equity_fees
    >>> from lumibot.backtesting import YahooDataBacktesting
    >>>
    >>> buy_fees, sell_fees = make_india_equity_fees("MIS")
    >>> MyStrategy.backtest(
    ...     YahooDataBacktesting, start, end,
    ...     buy_trading_fees  = buy_fees,
    ...     sell_trading_fees = sell_fees,
    ... )
    """
    # Taker fees — market / stop orders (slippage included for market orders)
    buy_taker  = IndiaTradingFee(
        product_type, exchange, side="buy",
        maker=False, taker=True,
        include_slippage=include_slippage,
    )
    sell_taker = IndiaTradingFee(
        product_type, exchange, side="sell",
        maker=False, taker=True,
        include_slippage=include_slippage,
    )

    # Maker fees — limit / stop-limit orders (no slippage)
    buy_maker  = IndiaTradingFee(
        product_type, exchange, side="buy",
        maker=True, taker=False,
        include_slippage=False,
    )
    sell_maker = IndiaTradingFee(
        product_type, exchange, side="sell",
        maker=True, taker=False,
        include_slippage=False,
    )

    return [buy_taker, buy_maker], [sell_taker, sell_maker]


# ---------------------------------------------------------------------------
# Quick self-check  (python -m lumibot.entities.india_trading_fees)
# ---------------------------------------------------------------------------

def _print_summary() -> None:
    """Print a human-readable rate summary for verification."""
    print("\n" + "=" * 70)
    print("  Indian Equity Fee Summary — FY 2025-26")
    print("=" * 70)

    for product in ("MIS", "CNC"):
        for exchange in ("NSE", "BSE"):
            buy_fees, sell_fees = make_india_equity_fees(product, exchange)
            buy_taker, buy_maker   = buy_fees
            sell_taker, sell_maker = sell_fees

            print(f"\n  {exchange}  {product}")
            print(f"  {'─'*40}")
            for label, obj in [
                ("BUY  market ", buy_taker),
                ("BUY  limit  ", buy_maker),
                ("SELL market ", sell_taker),
                ("SELL limit  ", sell_maker),
            ]:
                bd = obj.breakdown()
                print(
                    f"  {label}  "
                    f"effective={bd['effective_cost_pct']:.5f}%  "
                    f"(statutory={bd['total_statutory_inr']:.4f}  "
                    f"slip={bd['slippage_penalty_inr']:.4f}  "
                    f"total={bd['total_with_slippage_inr']:.4f}  "
                    f"on ₹{bd['turnover_inr']:.0f})"
                )

    print()


if __name__ == "__main__":
    _print_summary()
