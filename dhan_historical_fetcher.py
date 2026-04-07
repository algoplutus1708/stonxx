"""
dhan_historical_fetcher.py
==========================
Standalone utility to fetch 1-minute OHLCV historical data from Dhan HQ API.

Features:
- Date-range pagination (30-day chunks)
- Exponential backoff for 429/500 errors
- Safe try/except blocks catching RequestException, Timeout, etc.
- Forward fills NaN values
- Localizes timestamps to Indian Standard Time (Asia/Kolkata)
- Highly compressed column-based Parquet saving
"""

import os
import time
import logging
import datetime
from pathlib import Path
from typing import Optional, List

import pandas as pd
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

DHAN_HISTORICAL_URL = "https://api.dhan.co/charts/historical"
IST_TZ = "Asia/Kolkata"
MAX_RETRIES = 5
DAYS_PER_CHUNK = 20  # Limit per pagination chunk to avoid huge payloads

# ── Core Fetching Logic ───────────────────────────────────────────────────────

def fetch_chunk(
    client_id: str,
    access_token: str,
    symbol: str,
    exchange_segment: str,
    instrument: str,
    from_date: str,
    to_date: str
) -> pd.DataFrame:
    """
    Fetches a specific date range from Dhan API with exponential backoff.
    Gracefully handles failures by returning an empty DataFrame if max retries exceeded.
    """
    headers = {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = {
        "symbol": symbol,
        "exchangeSegment": exchange_segment,
        "instrument": instrument,
        "expiryCode": 0,
        "fromDate": from_date,
        "toDate": to_date
    }

    retries = 0
    backoff = 1  # starting backoff in seconds

    while retries <= MAX_RETRIES:
        try:
            logger.debug(f"Fetching chunk {from_date} to {to_date} (Attempt {retries + 1})")
            response = requests.post(
                DHAN_HISTORICAL_URL,
                headers=headers,
                json=payload,
                timeout=15.0
            )

            # Check rate limits / server errors
            if response.status_code in [429, 500, 502, 503, 504]:
                logger.warning(
                    f"Received HTTP {response.status_code} for range {from_date}-{to_date}. "
                    f"Retrying in {backoff}s..."
                )
                time.sleep(backoff)
                retries += 1
                backoff *= 2
                continue
            
            response.raise_for_status()
            
            data_json = response.json()
            if data_json.get("status") == "failure" or "data" not in data_json:
                error_msg = data_json.get("remarks") or data_json.get("error_message") or "Unknown API Error"
                logger.error(f"Dhan API Error ({from_date} to {to_date}): {error_msg}")
                return pd.DataFrame()

            # The Dhan API returns lists inside the `data` dictionary:
            # { "start_Time": [...], "open": [...], ... }
            series_data = data_json["data"]
            if not series_data or not series_data.get("start_Time"):
                logger.info(f"No data returned for chunk {from_date} to {to_date}.")
                return pd.DataFrame()

            df = pd.DataFrame(series_data)
            return df

        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout formatting chunk {from_date}-{to_date}: {e}. Retrying in {backoff}s...")
            time.sleep(backoff)
            retries += 1
            backoff *= 2
            continue
        except requests.exceptions.JSONDecodeError as e:
            logger.error(f"JSON Decode Error formatting chunk {from_date}-{to_date}: {e}")
            break  # Not resolving via retry typically if JSON is mangled, but could retry depending on context
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Error formatting chunk {from_date}-{to_date}: {e}")
            break  # Fatal network/DNS errors skip the current chunk

    logger.error(f"Max retries ({MAX_RETRIES}) reached for chunk {from_date} to {to_date}. Skipping gracefully.")
    return pd.DataFrame()


def fetch_historical_paginated(
    symbol: str,
    exchange_segment: str,
    instrument: str,
    start_date: datetime.date,
    end_date: datetime.date,
    output_dir: str = "data",
    client_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> None:
    """
    Main orchestrator handling pagination across the full target date range, 
    data cleaning (ffill), localisation to IST, and final parquet compression.
    """
    if not client_id or not access_token:
        client_id = os.getenv("DHAN_CLIENT_ID")
        access_token = os.getenv("DHAN_ACCESS_TOKEN")
        
    if not client_id or not access_token:
        logger.error("Dhan credentials missing. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN environments.")
        return

    # Pagination
    dfs: List[pd.DataFrame] = []
    current_start = start_date
    
    while current_start <= end_date:
        current_end = current_start + datetime.timedelta(days=DAYS_PER_CHUNK - 1)
        if current_end > end_date:
            current_end = end_date
            
        str_start = current_start.strftime("%Y-%m-%d")
        str_end = current_end.strftime("%Y-%m-%d")
        
        logger.info(f"Processing pagination chunk: {str_start} to {str_end} for {symbol}")
        
        df_chunk = fetch_chunk(
            client_id, access_token, symbol, exchange_segment, instrument, str_start, str_end
        )
        
        if not df_chunk.empty:
            dfs.append(df_chunk)
            
        current_start = current_end + datetime.timedelta(days=1)
        time.sleep(0.5)  # Politeness delay between valid chunks
        
    if not dfs:
        logger.warning(f"No overall data extracted for {symbol}. Exiting gracefully without saving.")
        return
        
    # Combine everything
    master_df = pd.concat(dfs, ignore_index=True)
    
    # Clean Data
    if 'start_Time' in master_df.columns:
        # Deduplicate on the target start_Time index to avoid corrupt OHLCV joins
        master_df.drop_duplicates(subset=['start_Time'], inplace=True)
        
        # Rigorous Timezone awareness to IST (Asia/Kolkata)
        # Dhan returns Indian market start time in epoch seconds or directly aligned integer formats depending on endpoint
        # Often it comes back as integer epoch or string
        try:
            # We assume epoch seconds initially. Convert to UTC then directly to IST.
            master_df['datetime'] = pd.to_datetime(master_df['start_Time'], unit='s', utc=True)
            master_df['datetime'] = master_df['datetime'].dt.tz_convert(IST_TZ)
            master_df.set_index('datetime', inplace=True)
            master_df.sort_index(inplace=True)
            # Remove old time col
            master_df.drop(columns=['start_Time'], inplace=True)
        except Exception as e:
            logger.error(f"Timestamp timezone conversion issue: {e}. Will gracefully fall back.")
    
    # Forward-fill any NaN values matching internal market structure constraints
    master_df.ffill(inplace=True)
    
    # Output to highly compressed parquet
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    file_path = os.path.join(output_dir, f"{symbol.lower().replace(' ', '_')}_historical.parquet")
    
    try:
        master_df.to_parquet(file_path, engine='pyarrow', compression='snappy')
        logger.info(f"Successfully saved cleanly formatted timezone-aware dataset to {file_path}")
        logger.info(f"Dataset shape: {master_df.shape}")
    except Exception as e:
        logger.error(f"Failed to save parquet dataset: {e}")

if __name__ == "__main__":
    # Example execution testing parameters:
    fetch_historical_paginated(
        symbol="NIFTY_50",         # Example Nifty index symbol layout equivalent
        exchange_segment="IDX_I",
        instrument="INDEX",
        start_date=datetime.date(2023, 1, 1),
        end_date=datetime.date(2023, 12, 31)
    )
