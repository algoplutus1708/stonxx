import os
import pandas as pd
import numpy as np
import joblib
import yfinance as yf
from datetime import datetime

from lumibot.data_sources import PandasData
from lumibot.strategies.strategy import Strategy
from lumibot.entities.india_trading_fees import make_india_equity_fees
from lumibot.entities import Asset, Data

class ThreeBulletSynthesis(Strategy):
    def initialize(self):
        self.sleeptime = "1d" 
        self.set_market("BSE")
        
        # Load the pre-trained XGBoost model
        model_path = "nifty_daily_model.joblib"
        if not os.path.exists(model_path):
            self.log_message(f"CRITICAL: {model_path} not found!", color="red")
            return
        self.model = joblib.load(model_path)
        
        # Define Universe
        self.tickers = ['RELIANCE.NS', 'HDFCBANK.NS', 'TCS.NS', 'ITC.NS', 'LT.NS']
        self.index_symbol = '^NSEI'

    def calculate_features(self, df):
        """
        Computes required indicators (RSI, MACD, ATR, Lagged Returns)
        matching the model's training features.
        """
        df = df.copy()
        
        # 1. Target (placeholder for structure)
        df['target'] = np.where(df['close'].shift(-1) > df['open'].shift(-1), 1.0, 0.0)
        
        # 2. RSI (14-period)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss
        df['rsi_14'] = 100 - (100 / (1 + rs))
        
        # 3. MACD
        ema_12 = df['close'].ewm(span=12, adjust=False).mean()
        ema_26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema_12 - ema_26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # 4. ATR (Normalized)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift(1)).abs()
        low_close = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        df['atr_14_norm'] = atr / df['close']
        
        # 5. Lagged Returns
        daily_returns = df['close'].pct_change()
        df['return_lag_1'] = daily_returns.shift(1)
        df['return_lag_2'] = daily_returns.shift(2)
        df['return_lag_3'] = daily_returns.shift(3)
        
        # Drop raw prices
        cols_to_drop = ['open', 'high', 'low', 'close', 'volume', 'target']
        df.drop(columns=[col for col in cols_to_drop if col in df.columns], inplace=True)
        df.dropna(inplace=True)
        
        return df

    def on_trading_iteration(self):
        # 1. THE MASTER SWITCH (CRITICAL)
        index_asset = Asset(symbol=self.index_symbol, asset_type='index')
        index_bars = self.get_historical_prices(index_asset, 250, "day")
        if index_bars is None or len(index_bars) < 200:
            return

        index_df = index_bars.df
        nifty_price = index_df['close'].iloc[-1]
        nifty_sma_200 = index_df['close'].rolling(window=200).mean().iloc[-1]
        macro_bull = nifty_price > nifty_sma_200

        # PANIC BUTTON: Instant liquidation if macro_bull is False
        if not macro_bull:
            self.log_message("MACD BEAR DETECTED - ACTIVATING PANIC BUTTON (LIQUIDATING ALL)", color="red")
            self.sell_all()
            return

        # 2. EVALUATE HELD POSITIONS FOR EXIT
        current_positions = self.get_positions()
        for position in current_positions:
            asset = position.asset
            bars = self.get_historical_prices(asset, 50, "day")
            if bars is None or len(bars) < 10:
                continue
                
            # Run model for exit signal
            raw_df = bars.df.copy()
            # Mock latest row to preserve data through feature engineering dropna
            new_idx = raw_df.index[-1] + pd.Timedelta(days=1)
            raw_df.loc[new_idx] = raw_df.iloc[-1]
            
            feat_df = self.calculate_features(raw_df)
            if feat_df.empty:
                continue
                
            required_features = ['rsi_14', 'macd', 'macd_signal', 'macd_hist', 'atr_14_norm', 'return_lag_1', 'return_lag_2', 'return_lag_3']
            x_input = pd.DataFrame([feat_df.iloc[-1][required_features]])
            prob_up = self.model.predict_proba(x_input)[0][1]

            # EXIT LOGIC: Signal Fade
            if prob_up < 0.47:
                self.log_message(f"EXIT SIGNAL for {asset.symbol} (Prob: {prob_up:.4f})")
                self.submit_order(self.create_order(asset, position.quantity, "sell"))

        # 3. EVALUATE UNIVERSE FOR ENTRY
        active_positions = self.get_positions()
        if len(active_positions) >= 3:
            return

        for ticker in self.tickers:
            # Skip if already held
            if any(p.asset.symbol == ticker for p in active_positions):
                continue
                
            asset = Asset(symbol=ticker, asset_type='stock')
            bars = self.get_historical_prices(asset, 250, "day")
            if bars is None or len(bars) < 200:
                continue
            
            raw_df = bars.df.copy()
            price = raw_df['close'].iloc[-1]
            asset_sma_200 = raw_df['close'].rolling(window=200).mean().iloc[-1]
            
            # Feature calculation for entry
            new_idx = raw_df.index[-1] + pd.Timedelta(days=1)
            raw_df.loc[new_idx] = raw_df.iloc[-1]
            feat_df = self.calculate_features(raw_df)
            if feat_df.empty:
                continue
            
            required_features = ['rsi_14', 'macd', 'macd_signal', 'macd_hist', 'atr_14_norm', 'return_lag_1', 'return_lag_2', 'return_lag_3']
            x_input = pd.DataFrame([feat_df.iloc[-1][required_features]])
            prob_up = self.model.predict_proba(x_input)[0][1]

            # ENTRY LOGIC
            if prob_up > 0.515 and price > asset_sma_200 and len(self.get_positions()) < 3:
                # Sizing: exactly 33.3% of total portfolio value
                portfolio_value = self.get_portfolio_value()
                allocation = portfolio_value * 0.333
                qty = int(allocation // price)
                
                if qty > 0:
                    self.log_message(f"ENTRY SIGNAL for {ticker} (Prob: {prob_up:.4f})")
                    order = self.create_order(asset, qty, "buy")
                    self.submit_order(order)
                    # Break loop if we just filled to 3 positions
                    if len(self.get_positions()) >= 2: # Check before this buy is confirmed locally
                        pass 

if __name__ == "__main__":
    universe = ['RELIANCE.NS', 'HDFCBANK.NS', 'TCS.NS', 'ITC.NS', 'LT.NS', '^NSEI']
    data_dict = {}
    datetime_start = None
    datetime_end = None
    
    print(f"\nFETCHING DATA FOR UNIVERSE: {universe}")
    start_str = "2020-01-01"
    end_str = datetime.now().strftime("%Y-%m-%d")
    
    for ticker in universe:
        df = yf.download(ticker, start=start_str, end=end_str, progress=False)
        if df.empty:
            continue
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.rename(columns={
            'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'
        })
        df.index = pd.to_datetime(df.index, utc=True)
        
        asset_type = 'index' if ticker == '^NSEI' else 'stock'
        asset = Asset(symbol=ticker, asset_type=asset_type)
        data_dict[asset] = Data(asset=asset, df=df, timestep="day")

        # Track start/end
        s, e = df.index.min().to_pydatetime(), df.index.max().to_pydatetime()
        datetime_start = s if datetime_start is None else max(datetime_start, s)
        datetime_end = e if datetime_end is None else min(datetime_end, e)

    data_source = PandasData(
        pandas_data=data_dict,
        datetime_start=datetime_start,
        datetime_end=datetime_end
    )
    
    # Fees - Indian CNC Delivery
    buy_fees, sell_fees = make_india_equity_fees(product_type="CNC", exchange="NSE")

    print("\n" + "="*50)
    print("STARTING 3-BULLET SYNTHESIS BACKTEST")
    print("="*50)

    results = ThreeBulletSynthesis.backtest(
        data_source=data_source,
        initial_cash=1000000,
        buy_trading_fees=buy_fees,
        sell_trading_fees=sell_fees,
        show_plot=False,
        show_tearsheet=False
    )

    if results:
        metrics = results[0] if isinstance(results, list) else results
        total_return = metrics.get('total_return', 0)
        cagr = metrics.get('cagr', 0)
        max_drawdown = metrics.get('max_drawdown', 0)
        
        # Handle dict format for max_drawdown if necessary
        if isinstance(max_drawdown, dict):
            max_drawdown = max_drawdown.get('drawdown', 0)

        print("\n" + "="*50)
        print("FINAL RESULTS")
        print("="*50)
        print(f"Total Return : {total_return*100:.2f}%")
        print(f"CAGR         : {cagr*100:.2f}%")
        print(f"Max Drawdown : {max_drawdown*100:.2f}%")
        print("="*50 + "\n")