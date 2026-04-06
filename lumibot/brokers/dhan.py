import logging
from dhanhq import DhanContext, dhanhq as DhanAPI
from lumibot.brokers.broker import Broker
from lumibot.entities import Order, Position
from lumibot.constants import BrokerConstants

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
        self.dhan_context = DhanContext(client_id, access_token)
        self.api = DhanAPI(self.dhan_context)
        
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
            return self._parse_dhan_order(response.get('data', {}))
        return None

    def _parse_dhan_order(self, dhan_order):
        # Implementation of order parsing
        return Order(...)

    def submit_order(self, order):
        """
        Submit a new order to Dhan.
        """
        try:
            # Map Lumibot order to Dhan API call
            response = self.api.place_order(
                security_id=order.asset.symbol, # Needs mapping if not using security_id
                exchange_segment=self.NSE, # Default for now
                transaction_type=self.BUY if order.side == "buy" else self.SELL,
                quantity=order.quantity,
                order_type=self.MARKET if order.type == "market" else self.LIMIT,
                product_type=self.INTRA, # Default to Intraday
                price=order.limit_price or 0,
                trigger_price=order.stop_price or 0
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
