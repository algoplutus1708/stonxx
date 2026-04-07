"""
yf_historical_fetcher.py
========================
Standalone utility for downloading the free-tier data pipeline branch
using yfinance for 15-minute historical data over the last 60 days.

Features:
- Nifty 50 Index (^NSEI)
- Timezone forced standardisation to IST (Asia/Kolkata)
- Forward fills missing candle data
- Normalises column nomenclature specifically to lowercase
- Saves directly to highly compressed Parquet outputs.
- Contains strict Try/Except exception guards wrapping the network fetching logic.
"""

import os
import logging
from pathlib import Path

import pandas as pd
import yfinance as yf
from requests.exceptions import Timeout, RequestException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

IST_TZ = "Asia/Kolkata"

def fetch_and_clean_nifty_data() -> None:
    symbol = "^NSEI"
    period = "60d"
    interval = "15m"
    
    logger.info(f"Initialising download for {symbol} | Period: {period} | Interval: {interval}")
    
    try:
        # Wrap the API bound in an immediate try-catch. yf.Ticker abstracts the request but throws standard Web API Errors.
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            logger.error(f"yfinance returned an empty DataFrame for {symbol}. Verify network state and symbol availability.")
            return
            
        logger.info(f"Data retrieved. Raw shape: {df.shape}. Cleaning schema...")
        
        # 1. Normalise to stricly lowercase required internal schema
        df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        }, inplace=True)
        
        # Drop redundant yfinance metadata columns if they exist (Dividends, Stock Splits)
        cols_to_keep = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in cols_to_keep if c in df.columns]]
        
        # 2. Handle missing data due to market closures, holidays, or missing 15m ticks sequentially forward-filled
        original_nans = df.isna().sum().sum()
        df.ffill(inplace=True)
        if original_nans > 0:
            logger.info(f"Forward filled {original_nans} embedded NaN constraints.")
            
        # 3. Timezone Rigour: strip and assign IST
        # yfinance index is usually tz-aware representing the locale of the exchange.
        # "Strip any existing timezone info first if necessary to avoid offset conflicts, then localize to IST."
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
            
        df.index = df.index.tz_localize(IST_TZ)
        
        # 4. Storage logic
        output_dir = Path("data")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = output_dir / "nifty50_15m_yf.parquet"
        
        df.to_parquet(file_path, engine="pyarrow", compression="snappy")
        
        logger.info(f"Successfully processed and serialized robust internal schema to {file_path}")
        logger.info(f"Final internal shape: {df.shape}")
        
    except (Timeout, RequestException) as net_err:
        logger.error(f"Network degradation preventing yfinance fetch: {net_err}")
    except ValueError as val_err:
        logger.error(f"Value Error formatting internal dataframe schema limits: {val_err}")
    except Exception as exc:
        logger.error(f"Unexpected Critical Exception fetching historical yfinance block: {exc}")


if __name__ == "__main__":
    fetch_and_clean_nifty_data()
