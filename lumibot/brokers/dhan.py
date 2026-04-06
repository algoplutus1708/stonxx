import logging
from dhanhq import dhanhq as DhanAPI
from lumibot.brokers.broker import Broker
from lumibot.entities import Order, Position

class Dhan(Broker):
    """
    Broker class for the Indian market via Dhan API.
    """
    
    # Dhan specific constants
    NSE = "NSE"
    NSE_FNO = "NSE_FNO"
    BSE = "BSE"
    BSE_FNO = "BSE_FNO"
    
    # Transaction types
    BUY = "BUY"
    SELL = "SELL"
    
    # Order types
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SLM = "SLM"
    
    # Product types
    INTRA = "INTRA"  # MIS
    CNC = "CNC"      # Delivery
    MARGIN = "MARGIN" # F&O Margin
    
    def __init__(self, client_id, access_token, name="dhan", **kwargs):
        super().__init__(name=name, **kwargs)
        self.client_id = client_id
        self.access_token = access_token
        self.api = DhanAPI(client_id, access_token)
        
    def get_positions(self):
        """
        Get all current positions on Dhan.
        """
        response = self.api.get_positions()
        positions = []
        if response and response.get('status') == 'success':
            for pos in response.get('data', []):
                # Mapping Dhan fields to Lumibot Position
                positions.append(Position(
                    symbol=pos.get('tradingSymbol'),
                    quantity=float(pos.get('netQty', 0)),
                    price=float(pos.get('avgPrice', 0)),
                    # product_type=pos.get('productType')
                ))
        return positions
    
    def get_tracked_order(self, order_id):
        """
        Get details of a specific order by its Dhan order ID.
        """
        response = self.api.get_order_by_id(order_id)
        if response and response.get('status') == 'success':
            data = response.get('data', {})
            return self._parse_dhan_order(data)
        return None

    def get_orders(self, strategy_name=None):
        """
        Get all orders from Dhan.
        """
        response = self.api.get_order_list()
        orders = []
        if response and response.get('status') == 'success':
            for d_order in response.get('data', []):
                order = self._parse_dhan_order(d_order)
                if strategy_name is None or order.strategy_name == strategy_name:
                    orders.append(order)
        return orders

    def _parse_dhan_order(self, dhan_order):
        """
        Parse Dhan API order response into a Lumibot Order object.
        """
        order_id = dhan_order.get('orderId')
        symbol = dhan_order.get('tradingSymbol')
        status_raw = dhan_order.get('orderStatus', '').upper()
        
        # Map status
        status = Order.OrderStatus.NEW
        if status_raw == "FILLED":
            status = Order.OrderStatus.FILLED
        elif status_raw == "CANCELLED":
            status = Order.OrderStatus.CANCELED
        elif status_raw in ["REJECTED", "FAILED"]:
            status = Order.OrderStatus.ERROR
            
        quantity = float(dhan_order.get('quantity', 0))
        price = float(dhan_order.get('price', 0))
        avg_price = float(dhan_order.get('avgPrice', 0))
        
        order = Order(
            asset=symbol, # This should ideally be an Asset object
            quantity=quantity,
            side="buy" if dhan_order.get('transactionType') == "BUY" else "sell",
            limit_price=price,
            avg_fill_price=avg_price,
            status=status,
            identifier=order_id
        )
        return order

    def submit_order(self, order):
        """
        Submit a new order to Dhan.
        """
        try:
            # Determine product type from order parameters if available, else default to INTRA (MIS)
            p_type = getattr(order, "product_type", self.INTRA)
            if p_type not in [self.INTRA, self.CNC, self.MARGIN]:
                p_type = self.INTRA

            # Map Lumibot order to Dhan API call
            response = self.api.place_order(
                security_id=str(getattr(order.asset, "dhan_id", order.asset.symbol)), 
                exchange_segment=getattr(order.asset, "exchange", self.NSE),
                transaction_type=self.BUY if order.side == "buy" else self.SELL,
                quantity=int(order.quantity),
                order_type=self.MARKET if order.type == "market" else self.LIMIT,
                product_type=p_type,
                price=float(order.limit_price or 0),
                trigger_price=float(order.stop_price or 0)
            )
            
            if response and response.get('status') == 'success':
                order.identifier = response.get('data', {}).get('orderId')
                order.status = "submitted"
                return order
            else:
                logging.error(f"Dhan order submission failed: {response}")
                order.status = "failed"
                return order
        except Exception as e:
            logging.error(f"Dhan order submission error: {e}")
            order.status = "failed"
            return order

    def cancel_order(self, order):
        """
        Cancel a pending order on Dhan.
        """
        if not order.identifier:
            return False
            
        response = self.api.cancel_order(order.identifier)
        return response and response.get('status') == 'success'
