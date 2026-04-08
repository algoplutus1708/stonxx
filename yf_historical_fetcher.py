import yfinance as yf
import pandas as pd
import os

def fetch_data():
    ticker = "^NSEI"
    print(f"Fetching data for {ticker} (Daily, Max period)...")
    
    # Fetch data
    df = yf.download(tickers=ticker, interval="1d", period="max")
    
    if df.empty:
        print("No data fetched. Please check your connection or the ticker symbol.")
        return

    # Handle multi-index columns in newer yfinance versions
    if isinstance(df.columns, pd.MultiIndex):
        try:
            # Flatten by dropping the 'Ticker' level if it exists
            df.columns = df.columns.droplevel(1)
        except Exception:
            # Fallback to taking the first element of the tuple
            df.columns = [col[0] for col in df.columns]
            
    # Standardize column names to lowercase
    df.columns = [str(col).lower() for col in df.columns]
    
    # Ensure we only keep the desired columns
    cols_to_keep = ['open', 'high', 'low', 'close', 'volume']
    available_cols = [c for c in cols_to_keep if c in df.columns]
    df = df[available_cols]
    
    # Handle DatetimeIndex timezone
    # Convert to Asia/Kolkata (IST)
    if df.index.tz is None:
        # Usually yfinance returns naive dates for daily intervals aligned to the exchange timezone
        df.index = df.index.tz_localize("Asia/Kolkata")
    else:
        df.index = df.index.tz_convert("Asia/Kolkata")
        
    # Normalize to midnight (00:00:00) so it represents pure dates without intraday time fragments
    df.index = df.index.normalize()
    
    # Drop rows with NaN values
    df.dropna(inplace=True)
    
    # Save the output
    os.makedirs('data', exist_ok=True)
    output_path = 'data/nifty50_1d_yf.parquet'
    
    # Save to parquet (requires pyarrow or fastparquet)
    df.to_parquet(output_path)
    
    # Print the total number of rows downloaded
    print(f"Successfully downloaded and processed {len(df)} rows.")
    print(f"Data saved to {output_path}")

if __name__ == "__main__":
    fetch_data()
