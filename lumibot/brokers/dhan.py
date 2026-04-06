"""
lumibot/brokers/dhan.py
========================
Production-grade Dhan broker for the Indian Stock Market (NSE / BSE).

Implements the full LumiBot ``Broker`` abstract interface so this can be
used as a live-trading broker alongside ``DhanData`` as the data source.

Supported product types
-----------------------
* ``INTRA``  — MIS (intraday, margin).  Auto-squared by Dhan at ~15:20 IST
               if the strategy doesn't close before market close.
* ``CNC``    — Delivery / Cash-and-Carry.  Positions held overnight.
* ``MARGIN`` — NRML / F&O margin product.

Indian session
--------------
NSE / BSE continuous session: 09:15 – 15:30 IST (Mon–Fri, excluding holidays).
The broker guard in ``is_market_open()`` uses the ``pytz`` IST timezone so it
works correctly regardless of the host machine's local timezone.

Order flow
----------
Dhan has a **polling-based** order model (no real-time WebSocket for retail
accounts).  ``_register_stream_events`` sets up a polling loop via
``_run_stream`` that runs in a background thread and dispatches order
state-change events to the LumiBot order engine.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Union

from termcolor import colored

from lumibot.brokers.broker import Broker
from lumibot.entities import Asset, Order, Position
from lumibot.tools.lumibot_logger import get_logger

try:
    from dhanhq import dhanhq as DhanAPI
    _DHAN_AVAILABLE = True
except ImportError:
    _DHAN_AVAILABLE = False

try:
    import pytz
    _IST = pytz.timezone("Asia/Kolkata")
    _PYTZ_AVAILABLE = True
except ImportError:
    _PYTZ_AVAILABLE = False
    _IST = None

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# NSE continuous cash-equity session: 09:15 – 15:30 IST
_NSE_OPEN_HH_MM  = (9, 15)
_NSE_CLOSE_HH_MM = (15, 30)

# MIS forced square-off: 15:15 IST (5 min before auto-squareoff at 15:20)
_MIS_SQUAREOFF_HH_MM = (15, 15)

# Dhan exchange segment codes
_SEGMENT_NSE_EQ  = "NSE_EQ"
_SEGMENT_BSE_EQ  = "BSE_EQ"
_SEGMENT_NSE_FNO = "NSE_FNO"
_SEGMENT_BSE_FNO = "BSE_FNO"

# Dhan order status strings → LumiBot statuses
_DHAN_STATUS_MAP = {
    "PENDING":          Order.OrderStatus.NEW,
    "OPEN":             Order.OrderStatus.NEW,
    "TRANSIT":          Order.OrderStatus.NEW,
    "TRADED":           Order.OrderStatus.FILLED,
    "PARTIALLY_TRADED": Order.OrderStatus.PARTIALLY_FILLED,
    "CANCELLED":        Order.OrderStatus.CANCELED,
    "REJECTED":         Order.OrderStatus.ERROR,
    "EXPIRED":          Order.OrderStatus.CANCELED,
    "FAILED":           Order.OrderStatus.ERROR,
}

# Polling interval for the order-status background thread (seconds)
_POLL_INTERVAL_LIVE = 5


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _ist_now() -> datetime:
    """Return the current wall-clock time in IST."""
    if _PYTZ_AVAILABLE and _IST:
        return datetime.now(_IST)
    # Fall back to UTC + 5:30 offset without pytz
    from datetime import timezone as _tz, timedelta
    ist_offset = _tz(timedelta(hours=5, minutes=30))
    return datetime.now(ist_offset)


def _is_nse_session_open() -> bool:
    """Return True if the NSE continuous cash session is currently open."""
    now = _ist_now()
    weekday = now.weekday()  # 0=Mon … 6=Sun
    if weekday >= 5:  # Saturday / Sunday
        return False
    open_hm  = _NSE_OPEN_HH_MM
    close_hm = _NSE_CLOSE_HH_MM
    current_hm = (now.hour, now.minute)
    return open_hm <= current_hm < close_hm


def _is_mis_squareoff_time() -> bool:
    """Return True if it is at or past the MIS forced-squareoff window."""
    now = _ist_now()
    return (now.hour, now.minute) >= _MIS_SQUAREOFF_HH_MM


# ---------------------------------------------------------------------------
# Dhan Broker
# ---------------------------------------------------------------------------

class Dhan(Broker):
    """
    LumiBot broker implementation for the Indian stock market via the Dhan API.

    Parameters
    ----------
    client_id : str
        Dhan API client / account ID.
    access_token : str
        Dhan API access token.
    default_product_type : str
        One of ``"INTRA"`` (MIS, intraday – default), ``"CNC"`` (delivery),
        or ``"MARGIN"`` (F&O / NRML).
    poll_interval : int
        Seconds between order-status polls.  Default is 5.
    data_source : DataSource, optional
        Override the data source used for price queries.  If not supplied,
        the strategy runner will inject one automatically.
    """

    NAME = "Dhan"

    # Dhan exchange segment constants
    NSE    = "NSE"
    NSE_EQ = _SEGMENT_NSE_EQ
    BSE    = "BSE"
    BSE_EQ = _SEGMENT_BSE_EQ
    NSE_FNO = _SEGMENT_NSE_FNO

    # Order transaction types
    BUY  = "BUY"
    SELL = "SELL"

    # Order types
    MARKET = "MARKET"
    LIMIT  = "LIMIT"
    SL     = "SL"
    SLM    = "SLM"

    # Product types
    INTRA  = "INTRA"   # MIS
    CNC    = "CNC"     # Delivery
    MARGIN = "MARGIN"  # F&O NRML

    # Validity
    VALIDITY_DAY = "DAY"
    VALIDITY_IOC = "IOC"

    def __init__(
        self,
        client_id: str,
        access_token: str,
        default_product_type: str = "INTRA",
        poll_interval: int = _POLL_INTERVAL_LIVE,
        data_source=None,
        name: str = "dhan",
        connect_stream: bool = True,
        **kwargs,
    ):
        super().__init__(
            name=name,
            data_source=data_source,
            connect_stream=connect_stream,
            **kwargs,
        )
        self.client_id    = client_id
        self.access_token = access_token
        self._poll_interval = max(1, poll_interval)

        # Validate / normalise product type
        _valid_types = {self.INTRA, self.CNC, self.MARGIN}
        ptype = (default_product_type or self.INTRA).upper()
        self.default_product_type = ptype if ptype in _valid_types else self.INTRA

        # Initialise the Dhan API client
        if not _DHAN_AVAILABLE:
            logger.error(
                colored(
                    "dhanhq package is not installed.  Install with: pip install dhanhq",
                    "red",
                )
            )
            self._api = None
        else:
            try:
                self._api = DhanAPI(client_id, access_token)
                logger.info(colored("Dhan broker: API client initialised.", "green"))
            except Exception as exc:
                logger.error(colored(f"Dhan broker: failed to initialise API – {exc}", "red"))
                self._api = None

        # Background polling state
        self._poll_thread: threading.Thread | None = None
        self._stop_poll   = threading.Event()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _exchange_segment(self, asset: Asset) -> str:
        """Map an Asset to the Dhan exchange segment string."""
        exchange = getattr(asset, "exchange", "NSE") or "NSE"
        exchange = str(exchange).upper()
        asset_type = getattr(asset, "asset_type", "stock") or "stock"
        if "FNO" in exchange or asset_type in ("option", "future"):
            return _SEGMENT_NSE_FNO
        if "BSE" in exchange:
            return _SEGMENT_BSE_EQ
        return _SEGMENT_NSE_EQ

    def _dhan_symbol(self, asset: Asset) -> str:
        """Return the bare trading symbol (strip .NS / .BO suffixes)."""
        symbol = str(asset.symbol).upper()
        for suffix in (".NS", ".BO"):
            if symbol.endswith(suffix):
                symbol = symbol[: -len(suffix)]
        return symbol

    def _security_id(self, asset: Asset) -> str:
        """
        Return the Dhan security_id for an asset.

        Dhan requires a numeric security_id for order placement.  If the asset
        carries a ``dhan_id`` attribute we use it; otherwise we fall back to
        the trading symbol (which works for segment=NSE_EQ with ISIN lookups).
        """
        return str(getattr(asset, "dhan_id", None) or self._dhan_symbol(asset))

    # ------------------------------------------------------------------
    # Market session guard
    # ------------------------------------------------------------------

    def is_market_open(self) -> bool:
        """Return True if the NSE continuous cash session is open."""
        return _is_nse_session_open()

    # ------------------------------------------------------------------
    # Required Broker abstract methods — Orders
    # ------------------------------------------------------------------

    def _submit_order(self, order: Order) -> Order:
        """
        Submit an order to Dhan.

        Maps LumiBot ``Order`` fields to the Dhan ``place_order`` API.
        Returns the order with ``identifier`` set on success, or with
        ``status = "error"`` on failure.
        """
        if self._api is None:
            logger.error("Dhan._submit_order: API not available.")
            order.set_error("Dhan API not available")
            return order

        # Determine product type
        p_type = getattr(order, "product_type", None) or self.default_product_type
        if p_type not in {self.INTRA, self.CNC, self.MARGIN}:
            p_type = self.default_product_type

        # Order type
        if order.type == Order.OrderType.MARKET:
            order_type = self.MARKET
        elif order.type == Order.OrderType.LIMIT:
            order_type = self.LIMIT
        elif order.type == Order.OrderType.STOP:
            order_type = self.SLM
        elif order.type == Order.OrderType.STOP_LIMIT:
            order_type = self.SL
        else:
            order_type = self.MARKET

        try:
            response = self._api.place_order(
                security_id      = self._security_id(order.asset),
                exchange_segment = self._exchange_segment(order.asset),
                transaction_type = self.BUY if order.side == "buy" else self.SELL,
                quantity         = int(abs(order.quantity)),
                order_type       = order_type,
                product_type     = p_type,
                price            = float(order.limit_price or 0),
                trigger_price    = float(order.stop_price  or 0),
                validity         = self.VALIDITY_DAY,
                tag              = getattr(order, "tag", "LumiBot")[:20],
            )

            if response and response.get("status") == "success":
                order_id = response.get("data", {}).get("orderId")
                order.identifier = order_id
                logger.info(
                    colored(
                        f"Dhan order submitted: {order.side.upper()} {order.quantity} "
                        f"{self._dhan_symbol(order.asset)} → orderId={order_id}",
                        "green",
                    )
                )
            else:
                error_msg = (response or {}).get("remarks", {}).get("errorCode", "unknown")
                logger.error(
                    colored(f"Dhan order submission failed: {response}", "red")
                )
                order.set_error(f"Dhan rejected order: {error_msg}")

        except Exception as exc:
            logger.error(colored(f"Dhan._submit_order exception: {exc}", "red"))
            order.set_error(str(exc))

        return order

    def cancel_order(self, order: Order) -> None:
        """Cancel a pending order on Dhan."""
        if self._api is None:
            logger.error("Dhan.cancel_order: API not available.")
            return

        identifier = getattr(order, "identifier", None)
        if not identifier:
            logger.warning("Dhan.cancel_order: order has no broker identifier.")
            return

        try:
            response = self._api.cancel_order(order_id=identifier)
            if response and response.get("status") == "success":
                logger.info(colored(f"Dhan: cancelled order {identifier}", "yellow"))
            else:
                logger.warning(f"Dhan.cancel_order non-success: {response}")
        except Exception as exc:
            logger.error(colored(f"Dhan.cancel_order exception: {exc}", "red"))

    def _modify_order(
        self,
        order: Order,
        limit_price: Union[float, None] = None,
        stop_price: Union[float, None] = None,
    ):
        """Modify limit/stop price of an open order."""
        if self._api is None:
            return
        identifier = getattr(order, "identifier", None)
        if not identifier:
            return
        try:
            self._api.modify_order(
                order_id      = identifier,
                order_type    = self.LIMIT if limit_price else self.MARKET,
                leg_name      = "ENTRY_LEG",  # Only relevant for OCO
                quantity      = int(abs(order.quantity)),
                price         = float(limit_price or 0),
                trigger_price = float(stop_price or 0),
                validity      = self.VALIDITY_DAY,
                disclosed_quantity = 0,
            )
        except Exception as exc:
            logger.error(colored(f"Dhan._modify_order exception: {exc}", "red"))

    # ------------------------------------------------------------------
    # Required Broker abstract methods — Orders (parsing + pulling)
    # ------------------------------------------------------------------

    def _parse_broker_order(
        self,
        response: dict,
        strategy_name: str,
        strategy_object=None,
    ) -> Order | None:
        """Convert a Dhan API order dict to a LumiBot ``Order``."""
        if not response:
            return None

        try:
            symbol   = response.get("tradingSymbol", "UNKNOWN")
            order_id = response.get("orderId")
            side     = "buy" if response.get("transactionType", "BUY") == "BUY" else "sell"
            quantity = float(response.get("quantity", 0))
            price    = float(response.get("price", 0) or 0)
            avg_fill = float(response.get("avgPrice", 0) or 0)

            # Determine order type
            ord_type_raw = response.get("orderType", "MARKET").upper()
            if ord_type_raw == "LIMIT":
                ord_type = Order.OrderType.LIMIT
            elif ord_type_raw == "SL":
                ord_type = Order.OrderType.STOP_LIMIT
            elif ord_type_raw == "SLM":
                ord_type = Order.OrderType.STOP
            else:
                ord_type = Order.OrderType.MARKET

            # Status
            raw_status = response.get("orderStatus", "PENDING").upper()
            lumi_status = _DHAN_STATUS_MAP.get(raw_status, Order.OrderStatus.NEW)

            asset = Asset(symbol=symbol, asset_type="stock")
            order = Order(
                strategy        = strategy_name,
                asset           = asset,
                quantity        = quantity,
                side            = side,
                type            = ord_type,
                limit_price     = price if ord_type == Order.OrderType.LIMIT else None,
                avg_fill_price  = avg_fill,
                identifier      = order_id,
            )
            order.status = lumi_status
            return order

        except Exception as exc:
            logger.error(f"Dhan._parse_broker_order error: {exc} — response={response}")
            return None

    def _pull_broker_order(self, identifier: str) -> Order | None:
        """Fetch a single order from Dhan by its orderId."""
        if self._api is None:
            return None
        try:
            response = self._api.get_order_by_id(order_id=identifier)
            if response and response.get("status") == "success":
                data = response.get("data")
                if isinstance(data, list) and data:
                    data = data[0]
                return self._parse_broker_order(data, strategy_name="")
        except Exception as exc:
            logger.error(f"Dhan._pull_broker_order({identifier}): {exc}")
        return None

    def _pull_broker_all_orders(self) -> list[dict]:
        """Fetch all orders from Dhan for the current session."""
        if self._api is None:
            return []
        try:
            response = self._api.get_order_list()
            if response and response.get("status") == "success":
                return response.get("data", []) or []
        except Exception as exc:
            logger.error(f"Dhan._pull_broker_all_orders: {exc}")
        return []

    # ------------------------------------------------------------------
    # Required Broker abstract methods — Positions
    # ------------------------------------------------------------------

    def _pull_positions(self, strategy) -> list[Position]:
        """Pull all open positions from Dhan."""
        if self._api is None:
            return []
        strategy_name = strategy.name if hasattr(strategy, "name") else str(strategy)
        positions = []
        try:
            response = self._api.get_positions()
            if not response or response.get("status") != "success":
                return []
            for pos in response.get("data", []) or []:
                qty = float(pos.get("netQty", 0) or 0)
                if qty == 0:
                    continue
                symbol = pos.get("tradingSymbol", "")
                asset  = Asset(symbol=symbol, asset_type="stock")
                positions.append(
                    Position(
                        strategy = strategy_name,
                        asset    = asset,
                        quantity = qty,
                        avg_fill_price = float(pos.get("avgCostPrice", 0) or 0),
                    )
                )
        except Exception as exc:
            logger.error(f"Dhan._pull_positions: {exc}")
        return positions

    def _pull_position(self, strategy, asset: Asset) -> Position | None:
        """Pull a single position by asset from Dhan."""
        all_positions = self._pull_positions(strategy)
        symbol = self._dhan_symbol(asset)
        for pos in all_positions:
            if str(pos.asset.symbol).upper() == symbol:
                return pos
        return None

    # ------------------------------------------------------------------
    # Required Broker abstract methods — Account
    # ------------------------------------------------------------------

    def _get_balances_at_broker(self, quote_asset: Asset, strategy) -> tuple:
        """
        Fetch cash / equity balances from Dhan fund limits.

        Returns
        -------
        tuple : (cash, positions_value, portfolio_value)  all in INR
        """
        if self._api is None:
            return 0.0, 0.0, 0.0
        try:
            response = self._api.get_fund_limits()
            if response and response.get("status") == "success":
                data = response.get("data", {}) or {}
                # Dhan fields: availabelBalance, sodLimit, collateralAmount
                available = float(data.get("availabelBalance", 0) or 0)
                collateral = float(data.get("collateralAmount", 0) or 0)
                utilized  = float(data.get("utilizedAmount", 0) or 0)
                cash = available
                # Approximate portfolio value as available + utilized margin
                portfolio_value = available + utilized + collateral
                positions_value = portfolio_value - cash
                return cash, positions_value, portfolio_value
        except Exception as exc:
            logger.error(f"Dhan._get_balances_at_broker: {exc}")
        return 0.0, 0.0, 0.0

    def get_historical_account_value(self) -> dict:
        """Historical P&L not supported via Dhan API; returns empty placeholder."""
        logger.info("Dhan.get_historical_account_value: not available via Dhan API.")
        return {"hourly": None, "daily": None}

    # ------------------------------------------------------------------
    # Required Broker abstract methods — Streaming / polling
    # ------------------------------------------------------------------

    def _get_stream_object(self):
        """Dhan uses polling; no persistent stream object needed."""
        return None

    def _register_stream_events(self):
        """
        Set up order-event polling.

        Dhan doesn't provide a push WebSocket for retail accounts, so we poll
        ``get_order_list()`` every ``_poll_interval`` seconds and dispatch
        order state-change events to the LumiBot order engine callbacks.
        """
        self._stop_poll.clear()
        logger.info(
            colored(
                f"Dhan: starting order-poll thread (interval={self._poll_interval}s)",
                "cyan",
            )
        )

        def _on_trade_event_fill(order, price, filled_quantity):
            self._process_filled_order(order, price, filled_quantity)

        def _on_trade_event_cancel(order):
            self._process_canceled_order(order)

        def _on_trade_event_error(order, error_msg):
            self._process_error_order(order, error_msg)

        def _on_trade_event_partial(order, price, quantity):
            self._process_partially_filled_order(order, price, quantity)

        def _poll_loop():
            _seen: dict[str, str] = {}  # orderId → last known status
            while not self._stop_poll.is_set():
                try:
                    raw_orders = self._pull_broker_all_orders()
                    for raw in raw_orders:
                        oid     = raw.get("orderId")
                        status  = (raw.get("orderStatus") or "").upper()
                        prev    = _seen.get(oid)
                        if status == prev:
                            continue
                        _seen[oid] = status

                        # Lookup the tracked LumiBot order
                        tracked = self.get_tracked_order(oid, use_placeholders=True)
                        if tracked is None:
                            continue

                        price_filled = float(raw.get("avgPrice", 0) or 0)
                        qty_filled   = float(raw.get("filledQty", 0) or 0)

                        lumi_status = _DHAN_STATUS_MAP.get(status, Order.OrderStatus.NEW)

                        if lumi_status == Order.OrderStatus.FILLED:
                            _on_trade_event_fill(tracked, price_filled, qty_filled)
                        elif lumi_status == Order.OrderStatus.PARTIALLY_FILLED:
                            _on_trade_event_partial(tracked, price_filled, qty_filled)
                        elif lumi_status == Order.OrderStatus.CANCELED:
                            _on_trade_event_cancel(tracked)
                        elif lumi_status == Order.OrderStatus.ERROR:
                            error_msg = raw.get("remarks", {}).get("errorCode", "unknown")
                            _on_trade_event_error(tracked, error_msg)

                except Exception as exc:
                    logger.warning(f"Dhan poll loop error: {exc}")

                self._stop_poll.wait(timeout=self._poll_interval)

        self._poll_thread = threading.Thread(
            target=_poll_loop,
            name="dhan-order-poll",
            daemon=True,
        )
        self._poll_thread.start()

    def _run_stream(self):
        """
        Start the polling stream.  Called by the broker's ``connect_stream``
        mechanism.  The actual work happens in ``_register_stream_events``.
        """
        self._register_stream_events()

    def cleanup_streams(self):
        """Stop the polling thread on shutdown."""
        self._stop_poll.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)
        super().cleanup_streams()
