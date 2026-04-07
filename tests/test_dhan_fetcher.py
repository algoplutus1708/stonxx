"""
tests/test_dhan_fetcher.py
==========================
Strict pytest suite for Dhan API Historical Fetcher mimicking actual failures,
exponential backoffs, and validating dataframe conversion accuracy via mocking.
"""

import datetime
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest
from requests.exceptions import Timeout, RequestException

from dhan_historical_fetcher import fetch_chunk, fetch_historical_paginated, MAX_RETRIES


@patch("dhan_historical_fetcher.time.sleep", return_value=None)  # skip wait during testing
@patch("dhan_historical_fetcher.requests.post")
def test_mock_dhan_429_retry_success(mock_post, mock_sleep):
    """Test that the script retries on a 429 limit and eventually succeeds."""
    # We will simulate 3 Rate Limit failures and 1 success
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "status": "success",
        "data": {
            "start_Time": [1685601900],
            "open": [18000.0], 
            "high": [18005.0], 
            "low": [17990.0], 
            "close": [18000.0], 
            "volume": [1000]
        }
    }
    
    mock_post.side_effect = [mock_resp_429, mock_resp_429, mock_resp_429, mock_resp_200]
    
    df = fetch_chunk("CLIENT", "TOKEN", "SYM", "SEG", "INST", "2023-01-01", "2023-01-20")
    
    # 3 retries over limits + 1 successful = 4 network attempts
    assert mock_post.call_count == 4
    assert mock_sleep.call_count == 3
    assert not df.empty
    assert len(df) == 1
    assert df.loc[0, "start_Time"] == 1685601900


@patch("dhan_historical_fetcher.time.sleep", return_value=None)
@patch("dhan_historical_fetcher.requests.post")
def test_mock_dhan_fails_gracefully(mock_post, mock_sleep):
    """Test that it stops retrying gracefully and skips chunk after MAX_RETRIES."""
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    
    # Will throw consistently on all requests (1 initial + MAX_RETRIES)
    mock_post.side_effect = [mock_resp_500] * (MAX_RETRIES + 1)
    
    # Should safely return empty dataframe without crashing script
    df = fetch_chunk("CLIENT", "TOKEN", "SYM", "SEG", "INST", "2023-01-01", "2023-01-20")
    
    assert mock_post.call_count == MAX_RETRIES + 1
    assert df.empty


@patch("dhan_historical_fetcher.fetch_chunk")
def test_dataframe_output_tz_construction(mock_fetch_chunk, tmp_path):
    """Test dataframe assembly, ffill cleaning, and UTC->IST localization correctly formats."""
    # 1685601900 is 2023-06-01 06:45:00 UTC = 12:15:00 PM IST
    raw_df = pd.DataFrame({
        "start_Time": [1685601900, 1685601960],
        "open": [18000.0, float('nan')], # explicitly testing forward-fill mechanism
        "high": [18005.0, 18010.0],
        "low": [17990.0, 17995.0],
        "close": [18000.0, 18005.0],
        "volume": [1000, 1500]
    })
    mock_fetch_chunk.return_value = raw_df
    
    output_dir = tmp_path / "data"
    
    fetch_historical_paginated(
        symbol="NIFTY", 
        exchange_segment="IDX_I", 
        instrument="INDEX", 
        start_date=datetime.date(2023, 1, 1), 
        end_date=datetime.date(2023, 1, 1), # just enough for one chunk
        output_dir=str(output_dir), 
        client_id="MOCK_X", 
        access_token="MOCK_Y"
    )
    
    file_path = output_dir / "nifty_historical.parquet"
    assert file_path.exists(), "The parquet file was not saved."
    
    # Read back compressed parquet locally and verify structure
    df_loaded = pd.read_parquet(file_path)
    
    # 1. Validation of Timezone (IST localisation)
    assert df_loaded.index.tz is not None
    assert "Asia/Kolkata" in str(df_loaded.index.tz)
    
    # Index should be strictly exactly localised
    first_time = df_loaded.index[0]
    assert first_time.hour == 12
    assert first_time.minute == 15
    
    # 2. Validation of ffill completion
    # The float('nan') on the second Open candle should be correctly mapped to 18000.0 purely via forward fill parameter
    assert df_loaded.iloc[1]["open"] == 18000.0
