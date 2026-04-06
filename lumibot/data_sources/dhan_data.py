import logging
from datetime import datetime, timedelta
from dhanhq import dhanhq as DhanAPI
from lumibot.data_sources import DataSourceBacktesting
from lumibot.data_sources.yahoo_data import YahooData
from lumibot.entities import Asset, Bars

class DhanData(DataSourceBacktesting):
    """
    Data source for the Indian market via Dhan API.
    Uses Yahoo Finance as a cost-optimized fallback for historical data.
    """
    
    SOURCE = "DHAN"
    
    def __init__(self, client_id, access_token, use_yfinance_historical=True, datetime_start=None, datetime_end=None, **kwargs):
        # Set default date range if not provided (matches YahooData pattern)
        if datetime_start is None:
            datetime_start = datetime.now() - timedelta(days=365)
        if datetime_end is None:
            datetime_end = datetime.now()

        super().__init__(datetime_start=datetime_start, datetime_end=datetime_end, **kwargs)
        self.client_id = client_id
        self.access_token = access_token
        self.use_yfinance_historical = use_yfinance_historical
        
        # Necessary for Strategy initialization
        self._data_store = {}
        self._last_price_cache = {}
        self._last_price_cache_datetime = None
        
        self.api = DhanAPI(client_id, access_token)
        
        # Initialize Yahoo fallback if needed
        if self.use_yfinance_historical:
            self.yahoo = YahooData(datetime_start=datetime_start, datetime_end=datetime_end, **kwargs)
        else:
            self.yahoo = None

    def get_historical_prices(self, asset, length, timestep="day", **kwargs):
        """
        Fetch historical prices. Redirects to Yahoo Finance for India if configured.
        """
        if self.use_yfinance_historical:
            # Map Dhan symbol to Yahoo symbol (e.g., RELIANCE -> RELIANCE.NS)
            symbol_upper = asset.symbol.upper()
            if symbol_upper.endswith(".NS") or symbol_upper.endswith(".BO"):
                yahoo_symbol = symbol_upper
            else:
                # Default to NSE if no suffix and exchange is not BSE
                exchange = getattr(asset, "exchange", "NSE")
                suffix = ".BO" if exchange == "BSE" else ".NS"
                yahoo_symbol = f"{symbol_upper}{suffix}"

            yahoo_asset = Asset(symbol=yahoo_symbol, asset_type=asset.asset_type)
            return self.yahoo.get_historical_prices(yahoo_asset, length, timestep, **kwargs)
        
        # Native Dhan historical implementation (if implemented)
        return self._get_native_historical(asset, length, timestep, **kwargs)

    def _get_native_historical(self, asset, length, timestep, **kwargs):
        # Implementation using self.api.historical_daily_data or intraday_minute_data
        logging.warning("Native Dhan historical data not fully implemented yet. Using fallback.")
        return None

    def get_quote(self, asset):
        """
        Get live quote from Dhan.
        """
        # Dhan needs security_id for quotes. 
        # In a real implementation, we'd have a mapping table.
        # For now, we assume asset.symbol IS the security_id or we look it up.
        response = self.api.ohlc_data(securities={"NSE_EQ": [asset.symbol]})
        if response and response.get('status') == 'success':
            data = response.get('data', {}).get(asset.symbol, {})
            return {
                "open": data.get('open', 0),
                "high": data.get('high', 0),
                "low": data.get('low', 0),
                "close": data.get('lp', 0),
                "volume": data.get('v', 0)
            }
        return None

    def get_last_price(self, asset):
        """
        Get the last price of an asset.
        """
        quote = self.get_quote(asset)
        if quote:
            return quote.get("close")
        return None

    def get_chains(self, asset):
        """
        Get option chains for an asset. (Not yet implemented for Dhan)
        """
        return {}
