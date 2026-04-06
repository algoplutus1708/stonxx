from lumibot.strategies.strategy import Strategy
from lumibot.entities import Asset
from datetime import datetime

class IndiaAIMomentum(Strategy):
    """
    Example strategy for the Indian market.
    Implements a simple momentum logic for large-cap NSE stocks.
    Includes MIS (Intraday) safety checks for 3:15 PM square-off.
    """
    
    def initialize(self, symbol="RELIANCE", quantity=1):
        self.symbol = symbol
        self.quantity = quantity
        self.sleeptime = "1 minute"
        self.target_asset = Asset(symbol=symbol, asset_type="stock")
        
        # Indian Market Hours (9:15 AM - 3:30 PM IST)
        self.market_close_time = "15:15" 

    def on_trading_iteration(self):
        # 1. Check for Square-off (MIS rules)
        current_time = self.get_datetime().strftime("%H:%M")
        if current_time >= self.market_close_time:
            self.log(f"Market close approaching ({current_time}). Squaring off positions.")
            self.sell_all()
            return

        # 2. Simple Momentum Logic
        bars = self.get_historical_prices(self.target_asset, 5, "minute")
        if bars is None:
            return
            
        df = bars.df
        last_price = df['close'].iloc[-1]
        avg_price = df['close'].mean()
        
        position = self.get_position(self.target_asset)
        
        if last_price > avg_price * 1.001 and position is None:
            self.log(f"Momentum detected! Buying {self.quantity} shares of {self.symbol}")
            order = self.create_order(self.target_asset, self.quantity, "buy")
            self.submit_order(order)
            
        elif last_price < avg_price * 0.999 and position is not None:
            self.log(f"Trend reversal! Selling {self.symbol}")
            order = self.create_order(self.target_asset, self.quantity, "sell")
            self.submit_order(order)

if __name__ == "__main__":
    # This part is usually handled by the runner script
    pass
