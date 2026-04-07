"""
dhan_historical_fetcher.py
==========================
Standalone utility to fetch historical data from Dhan HQ API.
Built to enforce a strict Data Contract (lowercase open, high, low, close, volume)
to allow seamless switching with yfinance.
"""

import os
import time
import logging
import datetime
from pathlib import Path
from typing import Optional, List

import pandas as pd
import requests
from dotenv import load_dotenv

# Load env vars at the top where they belong
load_dotenv('.env.india')

# ── Configuration ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

DHAN_HISTORICAL_URL = "https://api.dhan.co/charts/historical"
IST_TZ = "Asia/Kolkata"
MAX_RETRIES = 5
DAYS_PER_CHUNK = 20  

# ── Core Fetching Logic ───────────────────────────────────────────────────────

def fetch_chunk(
    client_id: str,
    access_token: str,
    security_id: str,
    exchange_segment: str,
    instrument: str,
    interval: str,
    from_date: str,
    to_date: str
) -> pd.DataFrame:
    
    headers = {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # FIXED PAYLOAD: Uses securityId and explicitly requests the interval
    payload = {
        "securityId": security_id,
        "exchangeSegment": exchange_segment,
        "instrument": instrument,
        "interval": interval, 
        "expiryCode": 0,
        "fromDate": from_date,
        "toDate": to_date
    }

    retries = 0
    backoff = 1  

    while retries <= MAX_RETRIES:
        try:
            logger.debug(f"Fetching chunk {from_date} to {to_date} (Attempt {retries + 1})")
            response = requests.post(
                DHAN_HISTORICAL_URL,
                headers=headers,
                json=payload,
                timeout=15.0
            )

            if response.status_code in [429, 500, 502, 503, 504]:
                logger.warning(f"HTTP {response.status_code} for {from_date}-{to_date}. Retrying in {backoff}s...")
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

            series_data = data_json["data"]
            if not series_data or not series_data.get("start_Time"):
                logger.info(f"No data returned for chunk {from_date} to {to_date}.")
                return pd.DataFrame()

            return pd.DataFrame(series_data)

        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout formatting chunk: {e}. Retrying in {backoff}s...")
            time.sleep(backoff)
            retries += 1
            backoff *= 2
            continue
        except requests.exceptions.JSONDecodeError as e:
            logger.error(f"JSON Decode Error chunk {from_date}-{to_date}: {e}")
            break
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Error chunk {from_date}-{to_date}: {e}")
            break

    logger.error(f"Max retries reached for {from_date} to {to_date}. Skipping.")
    return pd.DataFrame()


def fetch_historical_paginated(
    security_id: str,
    exchange_segment: str,
    instrument: str,
    interval: str,
    start_date: datetime.date,
    end_date: datetime.date,
    output_dir: str = "data",
    filename: str = "dhan_data.parquet"
) -> None:
    
    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")
        
    if not client_id or not access_token:
        logger.error("Dhan credentials missing. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN.")
        return

    dfs: List[pd.DataFrame] = []
    current_start = start_date
    
    while current_start <= end_date:
        current_end = current_start + datetime.timedelta(days=DAYS_PER_CHUNK - 1)
        if current_end > end_date:
            current_end = end_date
            
        str_start = current_start.strftime("%Y-%m-%d")
        str_end = current_end.strftime("%Y-%m-%d")
        
        logger.info(f"Processing chunk: {str_start} to {str_end}")
        
        df_chunk = fetch_chunk(
            client_id, access_token, security_id, exchange_segment, instrument, interval, str_start, str_end
        )
        
        if not df_chunk.empty:
            dfs.append(df_chunk)
            
        current_start = current_end + datetime.timedelta(days=1)
        time.sleep(0.5) 
        
    if not dfs:
        logger.warning(f"No overall data extracted. Exiting without saving.")
        return
        
    master_df = pd.concat(dfs, ignore_index=True)
    
    # ── ENFORCING THE DATA CONTRACT ──
    if 'start_Time' in master_df.columns:
        master_df.drop_duplicates(subset=['start_Time'], inplace=True)
        
        try:
            master_df['datetime'] = pd.to_datetime(master_df['start_Time'], unit='s', utc=True)
            master_df['datetime'] = master_df['datetime'].dt.tz_convert(IST_TZ)
            master_df.set_index('datetime', inplace=True)
            master_df.sort_index(inplace=True)
            master_df.drop(columns=['start_Time'], inplace=True)
        except Exception as e:
            logger.error(f"Timestamp conversion issue: {e}")
            
    # Ensure columns match standard naming conventions expected by strategy
    master_df.rename(columns=lambda x: x.strip().lower(), inplace=True)
    master_df.ffill(inplace=True)
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    file_path = os.path.join(output_dir, filename)
    
    try:
        master_df.to_parquet(file_path, engine='pyarrow', compression='snappy')
        logger.info(f"[SUCCESS] Saved strictly formatted data to {file_path}")
        logger.info(f"Dataset shape: {master_df.shape}")
    except Exception as e:
        logger.error(f"Failed to save parquet dataset: {e}")

# ── SINGLE EXECUTION BLOCK ────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n[INIT] Dhan Historical Fetcher script loaded.")
    print("[WARNING] Data API access required. Ensure ToS is accepted on Dhan HQ.")
    
    fetch_historical_paginated(
        security_id="13", 
        exchange_segment="IDX_I",
        instrument="INDEX",
        interval="15", # Requesting 15-minute candles to match your strategy
        start_date=datetime.date.today() - datetime.timedelta(days=10),
        end_date=datetime.date.today(),
        filename="nifty50_15m_dhan.parquet" # Explicitly named so it doesn't overwrite YF data
    )